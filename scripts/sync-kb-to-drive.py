#!/usr/bin/env python3
"""Mirror the onto-kb repo into its Google Drive folder.

An operator tool: you run it from your own machine with your own Google sign-in. It is
not part of the server and is not in the container image. The server only reads Drive
and has no code path that writes to it (constitution Article V); this script is where
the kb content gets onto Drive.

What it does
  * Lists the Drive folder and the local folder and prints a plan. Without --apply that
    is all it does.
  * With --apply it creates the folders and files that are missing and updates a changed
    file in place. The Drive file keeps its id, so anything that refers to it still works.
  * It never deletes. A file that is only in Drive is listed; --trash moves it to the
    Drive trash, where it stays for 30 days and can be restored.
  * It only touches items inside the one folder you name, and refuses a Drive root, a
    trashed folder, or a folder with the wrong name.
  * It is safe to run again: a file whose content already matches is left alone.

Usage (from the server repo, with the kb folder's Drive id):
  uv run python scripts/sync-kb-to-drive.py --source ../onto-kb --folder-id <id>
  uv run python scripts/sync-kb-to-drive.py --source ../onto-kb --folder-id <id> --apply

The folder id is the last part of the folder's address in Drive, and is also the value
of DRIVE_ALLOWED_FOLDER_ID, which is the default for --folder-id.
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
FOLDER_MIME = "application/vnd.google-apps.folder"
FIELDS = "id,name,mimeType,md5Checksum,size,parents,trashed,modifiedTime"
PARENTS_PER_QUERY = 40  # Drive accepts this many 'x' in parents clauses in one query
RESUMABLE_OVER = 5 * 1024 * 1024
MAX_ATTEMPTS = 5
ALWAYS_EXCLUDED = (".*",)  # .git, .github, .gitignore, .DS_Store, ...

LOGIN_HELP = """\
Could not sign in to Google with Drive access. Either:

  1. Application-default credentials with the Drive scope:
       gcloud auth application-default login \\
         --scopes=https://www.googleapis.com/auth/drive,https://www.googleapis.com/auth/cloud-platform
     then run this script again; or
  2. Your gcloud login with Drive access:
       gcloud auth login --enable-gdrive-access
     then run this script again with --gcloud-token.

If Google blocks the first, use the second (or the other way round)."""


class DriveError(Exception):
    """A Drive request that failed for good."""


class AuthError(DriveError):
    """The sign-in works but does not allow Drive writes."""


# ---- what is on disk ------------------------------------------------------------------


@dataclass(frozen=True)
class LocalFile:
    rel: str
    path: Path
    md5: str
    size: int


def md5_of(path: Path) -> str:
    # A change fingerprint compared with Drive's own md5Checksum; not a security check.
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _excluded(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch(name, pattern) for pattern in patterns)


def scan_local(source: Path, excludes: Iterable[str] = ()) -> dict[str, LocalFile]:
    """Every regular file under source, by path relative to it (always with '/')."""
    patterns = (*ALWAYS_EXCLUDED, *excludes)
    found: dict[str, LocalFile] = {}
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(d for d in dirnames if not _excluded(d, patterns))
        base = Path(dirpath)
        for name in sorted(filenames):
            path = base / name
            # A symlink could point outside the folder being mirrored.
            if _excluded(name, patterns) or path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(source).as_posix()
            found[rel] = LocalFile(rel, path, md5_of(path), path.stat().st_size)
    return found


def _ancestors(rel: str) -> list[str]:
    parts = rel.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


# ---- what is in Drive -----------------------------------------------------------------


@dataclass(frozen=True)
class RemoteItem:
    id: str
    name: str
    mime: str
    md5: str | None
    modified: str

    @property
    def is_folder(self) -> bool:
        return self.mime == FOLDER_MIME


def scan_remote(client: Any, root_id: str) -> dict[str, list[RemoteItem]]:
    """Every live item under the folder, by path. More than one item at a path means
    Drive holds duplicates (an upload that kept both files does this)."""
    items: dict[str, list[RemoteItem]] = {}
    level = {root_id: ""}
    seen = {root_id}
    while level:
        following: dict[str, str] = {}
        for entry in client.list_children(list(level)):
            parent = next((p for p in entry.get("parents") or [] if p in level), None)
            if parent is None:
                continue
            rel = f"{level[parent]}/{entry['name']}".lstrip("/")
            item = RemoteItem(
                id=entry["id"],
                name=entry["name"],
                mime=entry.get("mimeType", ""),
                md5=entry.get("md5Checksum"),
                modified=entry.get("modifiedTime", ""),
            )
            items.setdefault(rel, []).append(item)
            if item.is_folder and item.id not in seen:
                seen.add(item.id)
                following[item.id] = rel
        level = following
    return items


# ---- the plan -------------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    kind: str  # mkdir | create | update | skip | extra | trash | problem
    rel: str
    detail: str = ""


def make_plan(
    local: dict[str, LocalFile],
    remote: dict[str, list[RemoteItem]],
    *,
    trash_extras: bool = False,
) -> list[Action]:
    """Folders first (shallow first), then files, then anything only Drive has."""
    wanted_dirs = sorted(
        {d for rel in local for d in _ancestors(rel)}, key=lambda d: (d.count("/"), d)
    )
    blocked: set[str] = set()
    plan: list[Action] = []

    for rel in wanted_dirs:
        found = remote.get(rel, [])
        if any(rel == b or rel.startswith(b + "/") for b in blocked):
            continue
        if len(found) > 1:
            plan.append(Action("problem", rel, f"{len(found)} items with this name in Drive"))
            blocked.add(rel)
        elif found and not found[0].is_folder:
            plan.append(Action("problem", rel, "a file in Drive is where this folder belongs"))
            blocked.add(rel)
        elif not found:
            plan.append(Action("mkdir", rel))

    for rel in sorted(local):
        found = remote.get(rel, [])
        if any(rel.startswith(b + "/") for b in blocked):
            plan.append(Action("problem", rel, "its folder has a problem (see above)"))
        elif len(found) > 1:
            plan.append(Action("problem", rel, f"{len(found)} files with this name in Drive"))
        elif not found:
            plan.append(Action("create", rel))
        elif found[0].is_folder:
            plan.append(Action("problem", rel, "a folder in Drive is where this file belongs"))
        elif found[0].md5 is None:
            plan.append(Action("problem", rel, "not a plain file in Drive (Doc or shortcut)"))
        elif found[0].md5 == local[rel].md5:
            plan.append(Action("skip", rel))
        else:
            plan.append(Action("update", rel))

    problem_paths = {a.rel for a in plan if a.kind == "problem"}
    keep = set(local) | set(wanted_dirs)
    extra_folders: list[str] = []
    for rel in sorted(remote, key=lambda r: (r.count("/"), r)):
        if rel in keep or rel in problem_paths:
            continue
        if any(rel.startswith(p + "/") for p in problem_paths):
            continue  # inside a folder the plan could not make sense of: leave it alone
        if any(rel.startswith(f + "/") for f in extra_folders):
            continue  # inside a folder that is itself extra: trashing that covers it
        if any(item.is_folder for item in remote[rel]):
            extra_folders.append(rel)
        plan.append(Action("trash" if trash_extras else "extra", rel))
    return plan


# ---- talking to Drive -----------------------------------------------------------------


def _body(exc: Exception) -> str:
    content = getattr(exc, "content", b"") or b""
    return content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)


def _reason(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", "?")
    return f"HTTP {status}: {_body(exc)[:300]}".strip()


def _retryable(exc: Exception, *, server_errors: bool) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    text = _body(exc)
    if status == 429 or (status == 403 and "ateLimitExceeded" in text):
        return True  # Drive did not act on it, so asking again cannot double it
    return server_errors and status in (500, 502, 503, 504)


class DriveClient:
    """The few Drive calls this tool makes. Everything else is in this class's tests."""

    def __init__(self, service: Any, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._service = service
        self._sleep = sleep

    def _call(self, request: Any, *, server_errors: bool = True) -> Any:
        import httplib2
        from googleapiclient.errors import HttpError

        delay = 1.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return request.execute(num_retries=0)
            except (OSError, httplib2.HttpLib2Error) as exc:  # the network, not Drive
                if attempt < MAX_ATTEMPTS and server_errors:
                    self._sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                raise DriveError(f"network error: {exc}") from exc
            except HttpError as exc:
                if attempt < MAX_ATTEMPTS and _retryable(exc, server_errors=server_errors):
                    self._sleep(delay)
                    delay = min(delay * 2, 30.0)
                    continue
                text = _reason(exc)
                if getattr(exc.resp, "status", None) == 403 and "nsufficient" in text:
                    raise AuthError(text) from exc
                raise DriveError(text) from exc
        raise DriveError("unreachable")  # pragma: no cover

    def whoami(self) -> str:
        """The Google account the changes would be made as."""
        info = self._call(self._service.about().get(fields="user(emailAddress,displayName)"))
        user = info.get("user") or {}
        return user.get("emailAddress") or user.get("displayName") or "unknown"

    def get_item(self, file_id: str) -> dict:
        return self._call(
            self._service.files().get(fileId=file_id, fields=FIELDS, supportsAllDrives=True)
        )

    def list_children(self, parent_ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for start in range(0, len(parent_ids), PARENTS_PER_QUERY):
            chunk = parent_ids[start : start + PARENTS_PER_QUERY]
            clause = " or ".join(f"'{_escape(p)}' in parents" for p in chunk)
            token = None
            while True:
                response = self._call(
                    self._service.files().list(
                        q=f"({clause}) and trashed = false",
                        fields=f"nextPageToken, files({FIELDS})",
                        pageSize=1000,
                        pageToken=token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    )
                )
                out.extend(response.get("files", []))
                token = response.get("nextPageToken")
                if not token:
                    break
        return out

    def create_folder(self, name: str, parent_id: str) -> str:
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        made = self._call(
            self._service.files().create(body=body, fields="id", supportsAllDrives=True),
            server_errors=False,
        )
        return made["id"]

    def create_file(self, name: str, parent_id: str, path: Path, mime: str) -> str:
        body = {"name": name, "mimeType": mime, "parents": [parent_id]}
        made = self._call(
            self._service.files().create(
                body=body, media_body=_media(path, mime), fields="id", supportsAllDrives=True
            ),
            server_errors=False,  # a failed create may still have happened: never repeat it
        )
        return made["id"]

    def update_file(self, file_id: str, path: Path, mime: str) -> None:
        self._call(
            self._service.files().update(
                fileId=file_id, media_body=_media(path, mime), fields="id", supportsAllDrives=True
            )
        )

    def trash(self, file_id: str) -> None:
        self._call(
            self._service.files().update(
                fileId=file_id, body={"trashed": True}, fields="id", supportsAllDrives=True
            )
        )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _media(path: Path, mime: str) -> Any:
    from googleapiclient.http import MediaFileUpload

    return MediaFileUpload(str(path), mimetype=mime, resumable=path.stat().st_size > RESUMABLE_OVER)


def mime_for(path: Path) -> str:
    if path.suffix.lower() in (".md", ".markdown"):
        return "text/markdown"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


# ---- the safety checks and the run ----------------------------------------------------


def check_root(client: Any, folder_id: str, expect_name: str) -> dict:
    """Refuse anything but one ordinary folder below a Drive root, named as expected."""
    meta = client.get_item(folder_id)
    if meta.get("mimeType") != FOLDER_MIME:
        raise DriveError("that id is not a folder")
    if meta.get("trashed"):
        raise DriveError("that folder is in the Drive trash")
    if not meta.get("parents"):
        raise DriveError("that is a Drive root, not a folder inside one")
    if expect_name and meta.get("name") != expect_name:
        raise DriveError(
            f"the folder is named {meta.get('name')!r}, not {expect_name!r}. Check the id, "
            "or pass --expect-name with its real name (an empty value skips this check)"
        )
    return meta


@dataclass
class Outcome:
    done: int = 0
    failed: int = 0
    skipped_for_failure: int = 0


def apply_plan(
    client: Any,
    plan: list[Action],
    local: dict[str, LocalFile],
    remote: dict[str, list[RemoteItem]],
    root_id: str,
    say: Callable[[str], None],
) -> Outcome:
    folder_ids = {"": root_id}
    for rel, items in remote.items():
        if len(items) == 1 and items[0].is_folder:
            folder_ids[rel] = items[0].id
    out = Outcome()
    for action in plan:
        if action.kind not in ("mkdir", "create", "update", "trash"):
            continue
        rel = action.rel
        parent_rel, _, name = rel.rpartition("/")
        parent_id = folder_ids.get(parent_rel)
        if action.kind in ("mkdir", "create") and parent_id is None:
            out.skipped_for_failure += 1
            say(f"  not done   {rel}   (its folder could not be made)")
            continue
        try:
            if action.kind == "mkdir":
                folder_ids[rel] = client.create_folder(name, parent_id)
            elif action.kind == "create":
                client.create_file(name, parent_id, local[rel].path, mime_for(local[rel].path))
            elif action.kind == "update":
                client.update_file(remote[rel][0].id, local[rel].path, mime_for(local[rel].path))
            else:
                for item in remote[rel]:  # every item at an extra path, duplicates included
                    client.trash(item.id)
        except AuthError:
            raise  # every later write would fail the same way
        except DriveError as exc:
            out.failed += 1
            say(f"  FAILED     {rel}   {exc}")
            continue
        out.done += 1
        say(f"  {action.kind:<10} {rel}")
    return out


def _header(
    client: Any,
    meta: dict,
    folder_id: str,
    remote: dict[str, list[RemoteItem]],
    source: Path,
    local_count: int,
) -> list[str]:
    """Who is signed in, which folder, and what is in it: enough to spot the wrong
    account or the wrong folder named kb before --apply."""
    try:
        who = client.whoami() if hasattr(client, "whoami") else "unknown"
    except DriveError:
        who = "unknown"
    items = [item for found in remote.values() for item in found]
    files = sum(1 for item in items if not item.is_folder)
    newest = max((item.modified for item in items), default="")[:10] or "nothing"
    return [
        f"Signed in to Google as: {who}",
        f"Drive folder {meta['name']!r}: https://drive.google.com/drive/folders/{folder_id}",
        f"  it holds {files} files in {len(items) - files} folders; newest change {newest}",
        f"Local folder {source}: {local_count} files",
    ]


def _print_plan(plan: list[Action], say: Callable[[str], None], *, verbose: bool) -> None:
    counts: dict[str, int] = {}
    for action in plan:
        counts[action.kind] = counts.get(action.kind, 0) + 1
    shown = 0
    for action in plan:
        if action.kind == "skip":
            continue
        if shown >= 60 and not verbose:
            say("  ... (use -v to list every path)")
            break
        say(f"  {action.kind:<10} {action.rel}" + (f"   {action.detail}" if action.detail else ""))
        shown += 1
    order = ("mkdir", "create", "update", "skip", "extra", "trash", "problem")
    say("Plan: " + ", ".join(f"{counts[k]} {k}" for k in order if k in counts))


def _credentials(use_gcloud_token: bool) -> Any:
    if use_gcloud_token:
        from google.oauth2.credentials import Credentials

        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=True
        )
        return Credentials(token=result.stdout.strip())
    import google.auth

    credentials, _ = google.auth.default(scopes=[DRIVE_SCOPE])
    return credentials


def _build_client(use_gcloud_token: bool) -> DriveClient:
    from googleapiclient.discovery import build

    service = build(
        "drive", "v3", credentials=_credentials(use_gcloud_token), cache_discovery=False
    )
    return DriveClient(service)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mirror the onto-kb repo into its Google Drive folder.",
        epilog="Without --apply nothing is changed: you only see the plan.",
    )
    parser.add_argument("--source", required=True, type=Path, help="the local onto-kb folder")
    parser.add_argument(
        "--folder-id",
        default=os.environ.get("DRIVE_ALLOWED_FOLDER_ID", ""),
        help="Drive id of the kb folder (default: $DRIVE_ALLOWED_FOLDER_ID)",
    )
    parser.add_argument("--apply", action="store_true", help="make the changes")
    parser.add_argument(
        "--trash", action="store_true", help="move files that are only in Drive to the Drive trash"
    )
    parser.add_argument(
        "--expect-name", default="kb", help="refuse unless the Drive folder has this name"
    )
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="GLOB",
        help="also skip files and folders whose name matches (dot files are always skipped)",
    )
    parser.add_argument(
        "--max-files", type=int, default=1000,
        help="refuse to sync a folder with more files than this (a wrong --source guard)",
    )
    parser.add_argument(
        "--gcloud-token", action="store_true",
        help="sign in with `gcloud auth print-access-token` instead of application-default login",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="list every path")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    client: Any = None,
    say: Callable[[str], None] = print,
) -> int:
    args = parse_args(argv)
    source = args.source.expanduser()
    if not source.is_dir():
        say(f"--source {source} is not a folder")
        return 2
    if not args.folder_id.strip() or args.folder_id.strip() == "root":
        say("Give the kb folder's Drive id with --folder-id (or set DRIVE_ALLOWED_FOLDER_ID)")
        return 2
    local = scan_local(source, args.exclude)
    if not local:
        say(f"{source} holds no files to sync")
        return 2
    if len(local) > args.max_files:
        say(f"{source} holds {len(local)} files, more than --max-files {args.max_files}. "
            "Is --source the onto-kb folder?")
        return 2

    try:
        if client is None:
            client = _build_client(args.gcloud_token)
    except Exception as exc:  # DefaultCredentialsError, a missing gcloud, a failed token
        say(f"{type(exc).__name__}: {exc}\n\n{LOGIN_HELP}")
        return 2
    folder_id = args.folder_id.strip()
    try:
        meta = check_root(client, folder_id, args.expect_name)
        remote = scan_remote(client, folder_id)
    except AuthError as exc:
        say(f"{exc}\n\n{LOGIN_HELP}")
        return 2
    except DriveError as exc:
        say(f"Cannot use the Drive folder: {exc}")
        return 2

    for line in _header(client, meta, folder_id, remote, source, len(local)):
        say(line)
    plan = make_plan(local, remote, trash_extras=args.trash)
    _print_plan(plan, say, verbose=args.verbose)
    problems = sum(1 for a in plan if a.kind == "problem")
    extras = sum(1 for a in plan if a.kind == "extra")
    changes = [a for a in plan if a.kind in ("mkdir", "create", "update", "trash")]
    if extras:
        say(f"{extras} item(s) are only in Drive and were left alone (--trash moves them to the "
            "Drive trash).")

    if not args.apply:
        say("Nothing was changed. Run again with --apply to make these changes."
            if changes else "Nothing to change.")
        return 1 if problems else 0
    if not changes:
        say("Drive already matches." if not problems else "Nothing to change except the problems.")
        return 1 if problems else 0

    say("Applying:")
    try:
        outcome = apply_plan(client, plan, local, remote, folder_id, say)
    except AuthError as exc:
        say(f"{exc}\n\n{LOGIN_HELP}")
        return 2
    say(f"Done: {outcome.done} changed, {outcome.failed} failed, "
        f"{outcome.skipped_for_failure} not attempted, {problems} left for you to fix.")
    return 1 if (outcome.failed or outcome.skipped_for_failure or problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
