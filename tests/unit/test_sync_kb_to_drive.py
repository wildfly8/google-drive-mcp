"""scripts/sync-kb-to-drive.py: mirror the kb folder into Drive without surprises.

The script is an operator tool that writes to Drive, so it lives outside src/ (the server
has no write path) and is tested here against an in-memory Drive.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httplib2
import pytest
from googleapiclient.errors import HttpError

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("sync_kb_to_drive", ROOT / "scripts" / "sync-kb-to-drive.py")
sync = importlib.util.module_from_spec(_spec)
sys.modules["sync_kb_to_drive"] = sync
_spec.loader.exec_module(sync)

FOLDER = sync.FOLDER_MIME
MD = "text/markdown"


class FakeDrive:
    """An in-memory Drive folder. Records every write; computes md5 like Drive does."""

    def __init__(self, name: str = "kb") -> None:
        self.items: dict[str, dict] = {}
        self.writes: list[tuple] = []
        self.fail_folder: str | None = None
        self.auth_error_on_write = False
        self._n = 0
        self.root_id = self._add("ROOT", name, FOLDER, ["MYDRIVE"])

    def _add(self, fid: str | None, name: str, mime: str, parents: list[str], md5=None) -> str:
        self._n += 1
        fid = fid or f"id{self._n}"
        self.items[fid] = {
            "id": fid, "name": name, "mimeType": mime, "parents": parents,
            "md5Checksum": md5, "trashed": False, "modifiedTime": f"2026-11-0{self._n % 9 + 1}",
        }
        return fid

    # --- test helpers ---
    def put(self, rel: str, content: bytes | None = b"x", *, mime: str = MD) -> str:
        parent = self.root_id
        *dirs, name = rel.split("/")
        for d in dirs:
            existing = [i for i in self.items.values()
                        if i["name"] == d and parent in i["parents"] and i["mimeType"] == FOLDER]
            parent = existing[0]["id"] if existing else self._add(None, d, FOLDER, [parent])
        md5 = sync.hashlib.md5(content, usedforsecurity=False).hexdigest() if content is not None else None
        return self._add(None, name, mime, [parent], md5)

    def live(self) -> list[dict]:
        return [i for i in self.items.values() if not i["trashed"]]

    # --- what the script calls ---
    def whoami(self):
        return "owner@example.test"

    def get_item(self, file_id):
        if file_id not in self.items:
            raise sync.DriveError("HTTP 404: not found")
        return dict(self.items[file_id])

    def list_children(self, parent_ids):
        return [dict(i) for i in self.live() if set(parent_ids) & set(i["parents"])]

    def create_folder(self, name, parent_id):
        if name == self.fail_folder:
            raise sync.DriveError("HTTP 500: boom")
        self.writes.append(("folder", name, parent_id))
        return self._add(None, name, FOLDER, [parent_id])

    def create_file(self, name, parent_id, path, mime):
        if self.auth_error_on_write:
            raise sync.AuthError("HTTP 403: Insufficient Permission")
        self.writes.append(("create", name, parent_id))
        md5 = sync.md5_of(path)
        return self._add(None, name, mime, [parent_id], md5)

    def update_file(self, file_id, path, mime):
        self.writes.append(("update", file_id))
        self.items[file_id]["md5Checksum"] = sync.md5_of(path)

    def trash(self, file_id):
        self.writes.append(("trash", file_id))
        self.items[file_id]["trashed"] = True


def make_kb(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def run(src: Path, drive: FakeDrive, *flags: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = sync.main(
        ["--source", str(src), "--folder-id", "ROOT", *flags], client=drive, say=lines.append
    )
    return code, lines


KB = {"README.md": "# kb", "chatgpt/index.md": "idx", "chatgpt/2025/a.md": "a", "b.md": "b"}


# ---- reading the local folder ---------------------------------------------------------


def test_scan_local_skips_dot_entries_symlinks_and_excluded_names(tmp_path):
    make_kb(tmp_path, {"a.md": "a", "sub/b.md": "b", ".git/config": "c", ".gitignore": "g",
                       "sub/.hidden": "h", "skip.tmp": "t"})
    (tmp_path / "link.md").symlink_to(tmp_path / "a.md")
    found = sync.scan_local(tmp_path, ["*.tmp"])
    assert sorted(found) == ["a.md", "sub/b.md"]
    assert found["a.md"].md5 == sync.hashlib.md5(b"a", usedforsecurity=False).hexdigest()


def test_mime_for():
    assert sync.mime_for(Path("x.md")) == "text/markdown"
    assert sync.mime_for(Path("x.txt")) == "text/plain"
    assert sync.mime_for(Path("x.unknownext")) == "application/octet-stream"


# ---- the plan and the run -------------------------------------------------------------


def test_the_first_sync_makes_folders_before_files_then_a_second_changes_nothing(tmp_path):
    src = make_kb(tmp_path, KB)
    drive = FakeDrive()
    code, lines = run(src, drive, "--apply")
    assert code == 0, lines
    kinds = [w[0] for w in drive.writes]
    assert kinds[:2] == ["folder", "folder"] and set(kinds[2:]) == {"create"}
    assert [w[1] for w in drive.writes[:2]] == ["chatgpt", "2025"]  # shallow first
    # a.md went into the 2025 folder, which went into chatgpt
    folders = {i["name"]: i for i in drive.live() if i["mimeType"] == FOLDER}
    a = next(i for i in drive.live() if i["name"] == "a.md")
    assert a["parents"] == [folders["2025"]["id"]]
    assert folders["2025"]["parents"] == [folders["chatgpt"]["id"]]
    before = list(drive.writes)
    code, lines = run(src, drive, "--apply")
    assert code == 0 and drive.writes == before
    assert any("already matches" in line for line in lines)


def test_a_changed_file_is_updated_in_place_so_its_id_is_kept(tmp_path):
    src = make_kb(tmp_path, {"README.md": "new text", "b.md": "b"})
    drive = FakeDrive()
    readme_id = drive.put("README.md", b"old text")
    drive.put("b.md", b"b")
    code, lines = run(src, drive, "--apply")
    assert code == 0, lines
    assert drive.writes == [("update", readme_id)]
    assert sum(1 for i in drive.live() if i["name"] == "README.md") == 1


def test_without_apply_nothing_is_written(tmp_path):
    src = make_kb(tmp_path, KB)
    drive = FakeDrive()
    code, lines = run(src, drive)
    assert code == 0 and drive.writes == []
    assert any("Nothing was changed" in line for line in lines)
    assert any(line.startswith("Plan: ") and "4 create" in line for line in lines)


def test_the_preview_names_the_account_the_folder_and_what_it_holds(tmp_path):
    # A sync that lands in another account or another folder named kb looks like a success
    # unless the output says which account and which folder it changed.
    src = make_kb(tmp_path, KB)
    drive = FakeDrive()
    drive.put("README.md", b"r")
    drive.put("chatgpt/x.md", b"x")
    code, lines = run(src, drive)
    text = "\n".join(lines)
    assert code == 0
    assert "Signed in to Google as: owner@example.test" in text
    assert "https://drive.google.com/drive/folders/ROOT" in text
    assert "it holds 2 files in 1 folders" in text
    assert f"Local folder {src}: 4 files" in text


def test_a_failed_account_lookup_does_not_stop_the_preview(tmp_path):
    src = make_kb(tmp_path, KB)
    drive = FakeDrive()

    def refuse():
        raise sync.DriveError("HTTP 500")

    drive.whoami = refuse  # type: ignore[method-assign]
    code, lines = run(src, drive)
    assert code == 0
    assert any("Signed in to Google as: unknown" in line for line in lines)


def test_files_only_in_drive_are_left_alone_unless_trash_is_given(tmp_path):
    src = make_kb(tmp_path, {"a.md": "a"})
    drive = FakeDrive()
    drive.put("a.md", b"a")
    stray = drive.put("old/notes.md", b"n")
    code, lines = run(src, drive, "--apply")
    assert code == 0 and drive.writes == []
    assert any("only in Drive" in line for line in lines)
    code, lines = run(src, drive, "--apply", "--trash")
    folder = next(i for i in drive.items.values() if i["name"] == "old")
    # the extra folder is trashed once; what is inside it is not listed separately
    assert drive.writes == [("trash", folder["id"])]
    assert drive.items[stray]["trashed"] is False


def test_trash_takes_every_item_at_an_extra_path(tmp_path):
    src = make_kb(tmp_path, {"a.md": "a"})
    drive = FakeDrive()
    drive.put("a.md", b"a")
    first = drive.put("stray.md", b"1")
    second = drive.put("stray.md", b"2")
    code, _ = run(src, drive, "--apply", "--trash")
    assert code == 0
    assert drive.writes == [("trash", first), ("trash", second)]


def test_nothing_inside_a_folder_with_a_problem_is_trashed(tmp_path):
    src = make_kb(tmp_path, {"chatgpt/a.md": "a"})
    drive = FakeDrive()
    drive.put("chatgpt/a.md", b"a")
    drive.put("chatgpt/stray.md", b"s")
    # a second folder with the same name makes the path ambiguous
    drive._add(None, "chatgpt", FOLDER, [drive.root_id])
    code, lines = run(src, drive, "--apply", "--trash")
    assert code == 1
    assert drive.writes == []
    assert any("items with this name" in line for line in lines)


def test_duplicates_and_clashes_are_reported_not_guessed(tmp_path):
    src = make_kb(tmp_path, {"README.md": "r", "dup.md": "d", "asfile": "x", "doc.md": "g",
                             "ok.md": "ok", "adir/x.md": "x"})
    drive = FakeDrive()
    drive.put("README.md", b"r")
    drive.put("dup.md", b"d")
    drive.put("dup.md", b"d2")                       # a second upload that kept both
    drive.put("asfile/inner.md", b"i")                # a folder where a file belongs
    drive.put("adir", b"i")                           # a file where a folder belongs
    drive.put("doc.md", None, mime="application/vnd.google-apps.document")  # no md5: a Doc
    code, lines = run(src, drive, "--apply")
    assert code == 1
    text = "\n".join(lines)
    assert "2 files with this name" in text
    assert "a folder in Drive is where this file belongs" in text
    assert "a file in Drive is where this folder belongs" in text
    assert "not a plain file" in text
    # the file that was fine was still created, and no problem path was written to
    assert [w[1] for w in drive.writes if w[0] == "create"] == ["ok.md"]


def test_a_folder_that_cannot_be_made_skips_its_files_and_the_run_goes_on(tmp_path):
    src = make_kb(tmp_path, KB)
    drive = FakeDrive()
    drive.fail_folder = "chatgpt"
    code, lines = run(src, drive, "--apply")
    assert code == 1
    created = {w[1] for w in drive.writes if w[0] == "create"}
    assert created == {"README.md", "b.md"}
    text = "\n".join(lines)
    assert "FAILED" in text and "its folder could not be made" in text


def test_a_write_permission_error_stops_the_run_and_shows_how_to_sign_in(tmp_path):
    src = make_kb(tmp_path, KB)
    drive = FakeDrive()
    drive.auth_error_on_write = True
    code, lines = run(src, drive, "--apply")
    assert code == 2
    assert any("gcloud auth application-default login" in line for line in lines)


# ---- the safety checks ----------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.items["ROOT"].update(mimeType=MD), "not a folder"),
        (lambda d: d.items["ROOT"].update(trashed=True), "trash"),
        (lambda d: d.items["ROOT"].update(parents=[]), "Drive root"),
        (lambda d: d.items["ROOT"].update(name="Work"), "named 'Work'"),
    ],
)
def test_check_root_refuses_the_wrong_folder(mutate, message):
    drive = FakeDrive()
    mutate(drive)
    with pytest.raises(sync.DriveError, match=message):
        sync.check_root(drive, "ROOT", "kb")


def test_check_root_accepts_the_kb_folder_and_the_name_check_can_be_skipped():
    drive = FakeDrive()
    assert sync.check_root(drive, "ROOT", "kb")["name"] == "kb"
    drive.items["ROOT"]["name"] = "Anything"
    assert sync.check_root(drive, "ROOT", "")["name"] == "Anything"


def test_a_refused_folder_changes_nothing(tmp_path):
    src = make_kb(tmp_path, KB)
    drive = FakeDrive(name="Work")
    code, lines = run(src, drive, "--apply")
    assert code == 2 and drive.writes == []
    assert any("Cannot use the Drive folder" in line for line in lines)


def test_argument_guards(tmp_path):
    src = make_kb(tmp_path / "kb", KB)
    drive = FakeDrive()
    say: list[str] = []
    assert sync.main(["--source", str(src)], client=drive, say=say.append) == 2  # no folder id
    assert sync.main(["--source", str(src), "--folder-id", "root"], client=drive,
                     say=say.append) == 2
    assert sync.main(["--source", str(tmp_path / "missing"), "--folder-id", "ROOT"],
                     client=drive, say=say.append) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sync.main(["--source", str(empty), "--folder-id", "ROOT"], client=drive,
                     say=say.append) == 2
    assert sync.main(["--source", str(src), "--folder-id", "ROOT", "--max-files", "2"],
                     client=drive, say=say.append) == 2
    assert drive.writes == []


def test_the_folder_id_defaults_to_the_servers_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIVE_ALLOWED_FOLDER_ID", "ROOT")
    src = make_kb(tmp_path, {"a.md": "a"})
    drive = FakeDrive()
    assert sync.main(["--source", str(src)], client=drive, say=lambda _: None) == 0


def test_a_failed_sign_in_shows_both_ways_to_fix_it(tmp_path, monkeypatch):
    from google.auth.exceptions import DefaultCredentialsError

    def refuse(_use_gcloud):
        raise DefaultCredentialsError("no credentials")

    monkeypatch.setattr(sync, "_build_client", refuse)
    lines: list[str] = []
    src = make_kb(tmp_path, {"a.md": "a"})
    code = sync.main(["--source", str(src), "--folder-id", "ROOT"], say=lines.append)
    text = "\n".join(lines)
    assert code == 2
    assert "gcloud auth application-default login" in text
    assert "--enable-gdrive-access" in text and "--gcloud-token" in text


# ---- the real Drive wrapper -----------------------------------------------------------


def http_error(status: int, reason: str = "") -> HttpError:
    body = ('{"error": {"errors": [{"reason": "%s"}]}}' % reason).encode()
    return HttpError(httplib2.Response({"status": str(status)}), body)


def client_with(service=None):
    sleeps: list[float] = []
    return sync.DriveClient(service or MagicMock(), sleep=sleeps.append), sleeps


def test_whoami_asks_drive_who_is_signed_in():
    client, _ = client_with()
    about = client._service.about.return_value.get.return_value
    about.execute.return_value = {"user": {"emailAddress": "me@example.test"}}
    assert client.whoami() == "me@example.test"
    about.execute.return_value = {"user": {"displayName": "Me"}}
    assert client.whoami() == "Me"
    about.execute.return_value = {}
    assert client.whoami() == "unknown"


def test_listing_batches_parents_and_follows_pages():
    client, _ = client_with()
    files = client._service.files.return_value
    files.list.return_value.execute.side_effect = [
        {"files": [{"id": "1"}], "nextPageToken": "p2"},
        {"files": [{"id": "2"}]},
        {"files": [{"id": "3"}]},
    ]
    parents = [f"p{n}" for n in range(45)]
    out = client.list_children(parents)
    assert [f["id"] for f in out] == ["1", "2", "3"]
    queries = [c.kwargs["q"] for c in files.list.call_args_list]
    assert queries[0].count(" in parents") == 40 and queries[2].count(" in parents") == 5
    assert all(q.endswith(") and trashed = false") for q in queries)
    assert files.list.call_args_list[1].kwargs["pageToken"] == "p2"


def test_a_query_escapes_quotes_in_ids():
    client, _ = client_with()
    client._service.files.return_value.list.return_value.execute.return_value = {"files": []}
    client.list_children(["a'b"])
    assert "'a\\'b' in parents" in client._service.files.return_value.list.call_args.kwargs["q"]


def test_create_update_and_trash_ask_drive_for_the_right_thing(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("hello")
    client, _ = client_with()
    files = client._service.files.return_value
    files.create.return_value.execute.return_value = {"id": "NEW"}
    assert client.create_folder("chatgpt", "P") == "NEW"
    assert files.create.call_args.kwargs["body"] == {
        "name": "chatgpt", "mimeType": FOLDER, "parents": ["P"]}
    assert client.create_file("a.md", "P", path, MD) == "NEW"
    body = files.create.call_args.kwargs["body"]
    assert body == {"name": "a.md", "mimeType": MD, "parents": ["P"]}
    assert files.create.call_args.kwargs["media_body"].mimetype() == MD
    client.update_file("EXISTING", path, MD)
    update = files.update.call_args.kwargs
    assert update["fileId"] == "EXISTING" and "body" not in update  # content only: id, name kept
    client.trash("GONE")
    assert files.update.call_args.kwargs == {
        "fileId": "GONE", "body": {"trashed": True}, "fields": "id", "supportsAllDrives": True}


def test_creating_never_repeats_after_a_server_error_but_updating_does(tmp_path):
    path = tmp_path / "a.md"
    path.write_text("hello")
    client, _ = client_with()
    files = client._service.files.return_value
    files.create.return_value.execute.side_effect = [http_error(503), {"id": "never"}]
    with pytest.raises(sync.DriveError, match="HTTP 503"):
        client.create_file("a.md", "P", path, MD)
    assert files.create.return_value.execute.call_count == 1  # it may have happened
    files.create.return_value.execute.side_effect = [http_error(503), {"id": "never"}]
    with pytest.raises(sync.DriveError):
        client.create_folder("f", "P")
    files.update.return_value.execute.side_effect = [http_error(503), {"id": "EXISTING"}]
    client.update_file("EXISTING", path, MD)  # same bytes again: safe to repeat
    assert files.update.return_value.execute.call_count == 2


def test_rate_limits_are_retried_with_a_growing_pause():
    client, sleeps = client_with()
    request = MagicMock()
    request.execute.side_effect = [http_error(429), http_error(403, "userRateLimitExceeded"), {"id": "x"}]
    assert client._call(request) == {"id": "x"}
    assert sleeps == [1.0, 2.0]


def test_a_failed_create_is_never_repeated_on_a_server_error():
    client, sleeps = client_with()
    request = MagicMock()
    request.execute.side_effect = [http_error(503)]
    with pytest.raises(sync.DriveError, match="HTTP 503"):
        client._call(request, server_errors=False)
    assert request.execute.call_count == 1 and sleeps == []


def test_a_server_error_on_a_repeatable_call_is_retried_then_given_up():
    client, sleeps = client_with()
    request = MagicMock()
    request.execute.side_effect = [http_error(500)] * 10
    with pytest.raises(sync.DriveError):
        client._call(request)
    assert request.execute.call_count == sync.MAX_ATTEMPTS
    assert len(sleeps) == sync.MAX_ATTEMPTS - 1


def test_network_errors_are_retried_for_repeatable_calls_and_reported_cleanly():
    client, _ = client_with()
    request = MagicMock()
    request.execute.side_effect = [OSError("reset"), {"ok": True}]
    assert client._call(request) == {"ok": True}
    request.execute.side_effect = [OSError("down")] * 10
    with pytest.raises(sync.DriveError, match="network error"):
        client._call(request)


def test_insufficient_scope_is_an_auth_error():
    client, _ = client_with()
    request = MagicMock()
    request.execute.side_effect = [http_error(403, "insufficientPermissions")]
    with pytest.raises(sync.AuthError):
        client._call(request)


# ---- it stays out of the server -------------------------------------------------------


def test_the_server_neither_imports_the_sync_tool_nor_ships_it():
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text()
        assert "sync-kb-to-drive" not in text and "sync_kb_to_drive" not in text
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "COPY src ./src" in dockerfile and "scripts" not in dockerfile
