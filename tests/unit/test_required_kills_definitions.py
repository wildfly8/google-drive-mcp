"""The required-kill list as committed (specs/006-required-kills, scripts/required_kills/definitions.py).

Each entry is one exact text change to this repository, so it can go stale: when a line an entry changes
is itself changed, the entry no longer applies and the list no longer says what it says. These tests keep
the definitions, the code and the spec's list in step.

If one of them fails because you changed a line under src/ on purpose, update that entry in
scripts/required_kills/definitions.py and measure it again:

    python scripts/required_kills/run.py --run --only <id>
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "required_kills"
SPEC_LIST = ROOT / "specs" / "006-required-kills" / "required-kills.md"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rk = _load("required_kills_run", TOOL / "run.py")
defs = rk.load_definitions(TOOL / "definitions.py")
ENTRIES = defs.MUTANTS
ID = re.compile(r"G\d+-S?\d+")


def test_ids_are_unique_and_well_formed():
    ids = [e.id for e in ENTRIES]
    assert len(ids) == len(set(ids))
    assert all(ID.fullmatch(i) for i in ids)
    for entry in ENTRIES:
        assert entry.id.split("-")[0] == entry.gamma, f"{entry.id} is filed under {entry.gamma}"


@pytest.mark.skipif(
    os.environ.get("REQUIRED_KILLS_MEASURING") == "1",
    reason="the runner is changing the code on purpose while it measures",
)
def test_every_entry_applies_to_the_code_as_it_is():
    cache: dict[str, str] = {}
    problems = [p for e in ENTRIES for p in rk.check_entry(ROOT, e, cache)]
    assert not problems, (
        "A line a required-kill entry changes has itself changed. Update the entry in "
        "scripts/required_kills/definitions.py and measure it again "
        "(python scripts/required_kills/run.py --run --only <id>):\n" + "\n".join(problems)
    )


def test_classes_and_expectations_are_known():
    assert {e.sev for e in ENTRIES} <= {"must", "should", "may"}
    assert {e.expect for e in ENTRIES} <= {"kill", "survive"}
    assert all(e.title.strip() for e in ENTRIES)


def test_every_group_has_entries_and_every_entry_a_group():
    assert set(defs.GAMMAS) == {e.gamma for e in ENTRIES}
    assert all(name.strip() for name in defs.GAMMAS.values())


def test_an_entry_that_survives_says_why():
    for entry in ENTRIES:
        if entry.expect == "survive":
            assert entry.note.strip(), f"{entry.id} survives by design but gives no reason"


def test_the_known_bad_entry_exists_and_belongs_to_the_first_group():
    control = next(e for e in ENTRIES if e.id == rk.CONTROL)
    assert control.gamma == "G1" and control.expect == "kill" and control.sev == "must"


def test_a_second_order_entry_is_two_first_order_entries_together():
    first = [e for e in ENTRIES if "-S" not in e.id]
    second = [e for e in ENTRIES if "-S" in e.id]
    assert second, "the redundant layers need second-order entries"
    for entry in second:
        assert any(a.edits + b.edits == entry.edits for a in first for b in first if a is not b), (
            f"{entry.id} is not two first-order entries applied together"
        )


def test_a_named_killer_is_a_test_that_exists():
    for entry in ENTRIES:
        if entry.killer:
            path, _, name = entry.killer.partition("::")
            assert (ROOT / path).is_file(), f"{entry.id}: {path} is not a file"
            assert f"def {name}(" in (ROOT / path).read_text(), f"{entry.id}: no test {name} in {path}"


def _spec_section() -> tuple[str, str]:
    """The generated part of the spec's list: the tables per group, and the table of survivors."""
    section = SPEC_LIST.read_text().split(rk.BEGIN, 1)[1].split(rk.END, 1)[0]
    tables, survivors = section.split("## Survivors that are not gaps", 1)
    return tables, survivors


def test_the_spec_lists_exactly_these_entries():
    tables, survivors = _spec_section()
    listed = re.findall(r"^\| (G\d+-S?\d+) \|", tables, re.M)
    assert sorted(listed) == sorted(e.id for e in ENTRIES), "specs/006-required-kills/required-kills.md differs"
    for entry in ENTRIES:
        assert f"| {entry.id} | {entry.sev} | {rk._esc(entry.title)} |" in tables, f"{entry.id}: text differs"
    by_design = [e.id for e in ENTRIES if e.expect == "survive"]
    assert sorted(re.findall(r"^\| (G\d+-S?\d+) \|.*\*\*survives by design\*\*", tables, re.M)) == sorted(by_design)
    assert sorted(re.findall(r"^\| (G\d+-S?\d+) \|", survivors, re.M)) == sorted(by_design)


def test_the_spec_list_is_what_the_report_makes_from_its_own_table():
    """Every row of the committed list carries its killer or its reason, and nothing is marked unmeasured."""
    section = "".join(_spec_section())
    assert "not measured" not in section
    assert "**SURVIVES**" not in section
    assert "Unexpected survivors" not in section
