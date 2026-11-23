#!/usr/bin/env python3
"""Measure the required-kill list (specs/006-required-kills).

Every entry in definitions.py is one deliberately wrong change to this repository. The runner applies one
entry at a time to a throwaway copy of the repository, runs the test suite on the copy, and records whether
the suite failed (killed) or stayed green (survived). The repository itself is never modified.

  python scripts/required_kills/run.py --check
  python scripts/required_kills/run.py --run [--workers 3] [--only G1-01,G4-13] [--groups G1,G4]
  python scripts/required_kills/run.py --confirm
  python scripts/required_kills/run.py --report [--update-doc specs/006-required-kills/required-kills.md]

A run is void unless the unmutated suite passes on every worker (the null control) and the known-bad entry
(G1-01) is killed. --confirm re-runs each kill's test alone: a kill that does not repeat is a load flake or
an order dependence, and counts as a survivor. See README.md in this directory.

Exit status: 0 ok, 1 problems found, 2 null control failed, 3 known-bad control survived.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = HERE.parents[1]
DEFAULT_STATE = ".required-kills"
CONTROL = "G1-01"
FAIL_RE = re.compile(r"^(FAILED|ERROR) (.+?)(?: - (.*))?$", re.M)
IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", DEFAULT_STATE, "node_modules", "*.pyc"
)
PYTEST_BASE = ["-q", "--tb=no", "-p", "no:cacheprovider", "-rfE", "--ignore=tests/e2e"]
BEGIN, END = "<!-- required-kills:begin -->", "<!-- required-kills:end -->"


# ------------------------------------------------------------------------------ definitions


def load_definitions(path: Path):
    """The definitions module: MUTANTS (a list of entries) and GAMMAS (group id -> name)."""
    spec = importlib.util.spec_from_file_location("required_kills_definitions", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their annotations through sys.modules
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------------------ applying a change


def apply_edits(read, edits) -> dict[str, str]:
    """The new text of every file the edits touch. Each old text must occur exactly once."""
    current: dict[str, str] = {}
    for rel, old, new in edits:
        if rel not in current:
            current[rel] = read(rel)
        count = current[rel].count(old)
        if count != 1:
            raise ValueError(f"{rel}: old text occurs {count} times (must be once): {old[:80]!r}")
        current[rel] = current[rel].replace(old, new, 1)
    for rel, text in current.items():
        if rel.endswith(".py"):
            compile(text, rel, "exec")
    return current


def check_entry(repo: Path, entry, cache: dict[str, str] | None = None) -> list[str]:
    """Problems that keep an entry from applying to the tree at `repo` (none means it applies)."""
    cache = {} if cache is None else cache

    def read(rel: str) -> str:
        if rel not in cache:
            cache[rel] = (repo / rel).read_text(encoding="utf-8")
        return cache[rel]

    try:
        apply_edits(read, entry.edits)
    except (OSError, ValueError, SyntaxError) as exc:
        return [f"{entry.id}: {exc}"]
    return []


def apply(root: Path, edits) -> dict[str, str]:
    """Write the change under `root`; returns the original text of each file, for restore()."""
    originals: dict[str, str] = {}

    def read(rel: str) -> str:
        text = (root / rel).read_text(encoding="utf-8")
        originals.setdefault(rel, text)
        return text

    for rel, text in apply_edits(read, edits).items():
        (root / rel).write_text(text, encoding="utf-8")
    return originals


def restore(root: Path, originals: dict[str, str]) -> None:
    for rel, text in originals.items():
        (root / rel).write_text(text, encoding="utf-8")


# ----------------------------------------------------------------------------- running the suite


def parse_failures(output: str) -> list[dict]:
    return [
        {"kind": m.group(1), "test": m.group(2), "reason": (m.group(3) or "")[:160]}
        for m in FAIL_RE.finditer(output)
    ]


def run_pytest(python: str, root: Path, extra: list[str], *, timeout: int, deselect=()) -> dict:
    env = os.environ.copy()
    env.update(
        PYTHONPATH=f"{root}/src{os.pathsep}{root}/tests",
        PYTHONDONTWRITEBYTECODE="1",
        COLUMNS="250",
        NO_COLOR="1",
        # The suite is run on code that was changed on purpose. A test that checks the code against the
        # entries (tests/unit/test_required_kills_definitions.py) must stand aside, or it would "kill" them all.
        REQUIRED_KILLS_MEASURING="1",
    )
    cmd = [python, "-m", "pytest", *PYTEST_BASE, *[f"--deselect={d}" for d in deselect], *extra]
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
        output, rc, hung = proc.stdout + proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired as exc:
        raw = (exc.stdout or b"") + (exc.stderr or b"")
        output = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        rc, hung = None, True
    lines = output.strip().splitlines()
    return {
        "rc": rc,
        "hung": hung,
        "fails": parse_failures(output),
        "secs": round(time.monotonic() - started, 1),
        "tail": lines[-1] if lines else "",
    }


def classify(result: dict) -> str:
    if result["hung"]:
        return "killed-hang"
    if result["rc"] == 0:
        return "survived"
    if not result["fails"]:
        return "infra"
    if all(f["kind"] == "ERROR" for f in result["fails"]):
        return "killed-crash"
    return "killed"


def make_copy(repo: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(repo, dest, ignore=IGNORE)


def measure(python: str, root: Path, entry, *, maxfail: int, timeout: int, deselect=()) -> dict:
    """Apply the entry under `root`, run the suite, put the files back."""
    originals = apply(root, entry.edits)
    try:
        result = run_pytest(python, root, [f"--maxfail={maxfail}"], timeout=timeout, deselect=deselect)
        note = ""
        if result["hung"] and maxfail != 1:
            # A later test may loop for as long as the change lets it. Stop at the first failure instead.
            result = run_pytest(python, root, ["-x"], timeout=timeout, deselect=deselect)
            note = "re-run with -x: with more failures allowed the suite did not finish in time"
    finally:
        restore(root, originals)
    record = {
        "id": entry.id,
        "status": classify(result),
        "nfail": len(result["fails"]),
        "fails": result["fails"][:3],
        "secs": result["secs"],
        "tail": result["tail"],
    }
    if note:
        record["note"] = note
    return record


# ------------------------------------------------------------------------------------ results


def load_results(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                records[record["id"]] = record  # a later record replaces an earlier one
    return records


def write_results(path: Path, records: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records.values()), encoding="utf-8")


def state(record: dict | None) -> str:
    """killed, survived or pending. A kill that did not repeat when run alone is a survivor."""
    if record is None or record["status"] in ("infra", "invalid"):
        return "pending"
    if record["status"] == "survived":
        return "survived"
    if record["status"].startswith("killed"):
        return "survived" if record.get("confirmed") is False else "killed"
    return "pending"


# ---------------------------------------------------------------------------------- commands


def with_control(chosen, everything, control: str | None = CONTROL) -> list:
    """The chosen entries, with the known-bad control first (it is always measured)."""
    if control and all(e.id != control for e in chosen):
        return [e for e in everything if e.id == control] + list(chosen)
    return list(chosen)


def run_all(entries, *, repo, python, work, results, workers, maxfail, timeout, deselect, control=CONTROL) -> int:
    chosen = list(entries)
    work.mkdir(parents=True, exist_ok=True)
    paths = [work / f"w{i}" for i in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda p: make_copy(repo, p), paths))
        print(f"{workers} worker copies; null control on each (the suite as it is)...", flush=True)
        nulls = list(pool.map(lambda p: run_pytest(python, p, [], timeout=timeout, deselect=deselect), paths))
    for path, res in zip(paths, nulls):
        print(f"  null {path.name}: rc={res['rc']} {res['secs']}s {res['tail']}", flush=True)
    if any(res["rc"] != 0 for res in nulls):
        print("NULL CONTROL FAILED: the unmutated suite is not green under this load; nothing was measured")
        for res in nulls:
            for failure in res["fails"][:5]:
                print("   ", failure)
        return 2

    free: queue.Queue[Path] = queue.Queue()
    for path in paths:
        free.put(path)
    lock = threading.Lock()
    records = load_results(results)
    done = [0]

    def one(entry) -> None:
        root = free.get()
        try:
            try:
                record = measure(python, root, entry, maxfail=maxfail, timeout=timeout, deselect=deselect)
            except (OSError, ValueError, SyntaxError) as exc:
                record = {"id": entry.id, "status": "invalid", "error": str(exc)}
        finally:
            free.put(root)
        with lock:
            done[0] += 1
            records[entry.id] = record
            write_results(results, records)
            first = record["fails"][0]["test"].split("::", 1)[-1][:60] if record.get("fails") else ""
            print(f"[{done[0]}/{len(chosen)}] {entry.id:7} {record['status']:12} {first}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, chosen))
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)
    if control and state(records.get(control)) != "killed":
        print(f"RUN VOID: the known-bad entry {control} survived, so a green result proves nothing")
        return 3
    return 0


def confirm(entries, *, repo, python, work, results, workers, timeout, deselect) -> int:
    """Run each kill's test alone against its change. A kill that does not repeat is not a kill."""
    records = load_results(results)
    by_id = {e.id: e for e in entries}
    todo = [i for i, r in records.items() if r["status"].startswith("killed") and i in by_id]
    work.mkdir(parents=True, exist_ok=True)
    paths = [work / f"c{i}" for i in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda p: make_copy(repo, p), paths))
    free: queue.Queue[Path] = queue.Queue()
    for path in paths:
        free.put(path)
    lock = threading.Lock()

    def one(entry_id: str) -> None:
        entry, record = by_id[entry_id], records[entry_id]
        tests = [entry.killer] if entry.killer else [f["test"] for f in record.get("fails", [])]
        if not tests:
            return  # timed out with no failure on record: nothing to run alone
        root = free.get()
        try:
            originals = apply(root, entry.edits)
            try:
                result = run_pytest(python, root, tests, timeout=timeout, deselect=deselect)
            finally:
                restore(root, originals)
        finally:
            free.put(root)
        with lock:
            record["confirmed"] = result["rc"] != 0
            print(f"confirm {entry_id}: {'still fails alone' if record['confirmed'] else 'PASSES ALONE'}", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, sorted(todo)))
    write_results(results, records)
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)
    return 0


def check_all(entries, repo: Path) -> int:
    cache: dict[str, str] = {}
    problems = [p for e in entries for p in check_entry(repo, e, cache)]
    ids = [e.id for e in entries]
    problems += [f"{i}: duplicate id" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for problem in problems:
        print("BAD ", problem)
    print(f"{len(entries)} entries, {len(problems)} problems")
    return 1 if problems else 0


# ------------------------------------------------------------------------------------ report


def _killer(entry, record: dict) -> str:
    node = entry.killer or record["fails"][0]["test"]
    path, _, name = node.partition("::")
    base = re.sub(r"\[.*$", "", name)  # the parametrization is not part of the test's name
    return f"{Path(path).name}::{base}"


def _cell(entry, record: dict | None) -> str:
    s = state(record)
    if s == "pending":
        return "not measured"
    if s == "survived":
        if entry.expect == "survive":
            return f"**survives by design**: {entry.note}"
        return "**SURVIVES**" + (" (its one failing test does not repeat alone)" if record["status"] != "survived" else "")
    if not entry.killer and not record.get("fails"):
        return "killed (timed out; no failing test on record)"
    return f"`{_killer(entry, record)}`" + ("" if "confirmed" in record else " (not re-run alone)")


def _esc(text: str) -> str:
    return text.replace("|", "/")


def report(entries, gammas: dict[str, str], records: dict[str, dict]) -> str:
    lines: list[str] = []
    tally = []
    survivors = []
    for group, name in gammas.items():
        members = [e for e in entries if e.gamma == group]
        if not members:
            continue
        killed = 0
        lines += [f"\n## {group}. {name}\n", "| id | class | the wrong change the suite must reject | killed by |", "|---|---|---|---|"]
        for entry in members:
            record = records.get(entry.id)
            s = state(record)
            killed += s == "killed"
            if s == "survived":
                survivors.append(entry)
            lines.append(f"| {entry.id} | {entry.sev} | {_esc(entry.title)} | {_esc(_cell(entry, record))} |")
        tally.append((group, name, len(members), killed))
    total, killed_total = sum(t[2] for t in tally), sum(t[3] for t in tally)
    head = ["## Tally", "", "| invariant | entries | killed | survive by design |", "|---|---|---|---|"]
    head += [f"| {g} {_esc(n)} | {c} | {k} | {c - k} |" for g, n, c, k in tally]
    head += [f"| **all** | **{total}** | **{killed_total}** | **{total - killed_total}** |"]
    tail = ["", "## Survivors that are not gaps", "", "| id | the wrong change | why no test tells it from the real code |", "|---|---|---|"]
    tail += [f"| {e.id} | {_esc(e.title)} | {_esc(e.note)} |" for e in survivors]
    unexpected = [e.id for e in survivors if e.expect != "survive"]
    if unexpected:
        tail += ["", f"**Unexpected survivors (not marked by design): {unexpected}**"]
    return "\n".join(head + lines + tail).rstrip() + "\n"


def update_doc(path: Path, section: str) -> None:
    text = path.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{path}: the markers {BEGIN} and {END} are missing")
    before, rest = text.split(BEGIN, 1)
    _, after = rest.split(END, 1)
    path.write_text(f"{before}{BEGIN}\n\n{section}\n{END}{after}", encoding="utf-8")


# ------------------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="every entry applies to the current tree")
    mode.add_argument("--run", action="store_true", help="measure the entries against the suite")
    mode.add_argument("--confirm", action="store_true", help="re-run each kill's test alone")
    mode.add_argument("--report", action="store_true", help="print the tables from the results")
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--definitions", type=Path, default=HERE / "definitions.py")
    ap.add_argument("--results", type=Path, help=f"default: <repo>/{DEFAULT_STATE}/results.jsonl")
    ap.add_argument("--work", type=Path, help="where the worker copies go (default: a temporary directory)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default="", help="comma-separated entry ids")
    ap.add_argument("--groups", default="", help="comma-separated group ids")
    ap.add_argument("--maxfail", type=int, default=3, help="failures to collect per entry (1 stops at the first)")
    ap.add_argument("--timeout", type=int, default=240, help="seconds one suite run may take")
    ap.add_argument("--deselect", action="append", default=[], help="a test node id to leave out (repeatable)")
    ap.add_argument("--update-doc", type=Path, help="with --report: rewrite the section between the markers")
    args = ap.parse_args(argv)

    definitions = load_definitions(args.definitions)
    repo = args.repo.resolve()
    results = args.results or repo / DEFAULT_STATE / "results.jsonl"
    only = {i for i in args.only.split(",") if i}
    groups = {g for g in args.groups.split(",") if g}
    entries = [e for e in definitions.MUTANTS if (not only or e.id in only) and (not groups or e.gamma in groups)]

    if args.check:
        return check_all(definitions.MUTANTS, repo)
    if args.report:
        section = report(definitions.MUTANTS, definitions.GAMMAS, load_results(results))
        if args.update_doc:
            update_doc(args.update_doc, section)
            print(f"updated {args.update_doc}")
        else:
            print(section)
        return 0

    own_work = args.work is None
    work = args.work or Path(tempfile.mkdtemp(prefix="required-kills-"))
    try:
        common = dict(repo=repo, python=args.python, work=work, results=results, workers=args.workers,
                      timeout=args.timeout, deselect=args.deselect)
        if args.run:
            return run_all(with_control(entries, definitions.MUTANTS), maxfail=args.maxfail, **common)
        return confirm(definitions.MUTANTS if not only and not groups else entries, **common)
    finally:
        if own_work:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
