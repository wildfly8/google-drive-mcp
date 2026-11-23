"""scripts/required_kills/run.py: the runner that measures the required-kill list (specs/006).

An operator tool outside src/, like the sync script. It is tested on a tiny project of its own, so
that each decision it makes is checked: what counts as a kill, the two controls that void a run, the
re-run of each kill alone, and the report.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "required_kills_run", ROOT / "scripts" / "required_kills" / "run.py"
)
rk = importlib.util.module_from_spec(_spec)
sys.modules["required_kills_run"] = rk
_spec.loader.exec_module(rk)

MOD = textwrap.dedent(
    '''\
    def allowed(name):
        return name in {"kb", "kb-sub"}


    def pause():
        return 0
    '''
)
TESTS = textwrap.dedent(
    """\
    import time

    from pkg.mod import allowed, pause


    def test_kb_is_allowed():
        assert allowed("kb")


    def test_others_are_not():
        assert not allowed("elsewhere")


    def test_a_first_failure_comes_before_a_slow_test():
        assert pause() == 0


    def test_nothing_waits():
        time.sleep(pause())


    def test_the_runner_says_it_is_measuring():
        import os

        assert os.environ.get("REQUIRED_KILLS_MEASURING") == "1"
    """
)
MOD_PATH = "src/pkg/mod.py"


@dataclass
class Entry:
    id: str
    edits: list
    gamma: str = "G1"
    title: str = "a wrong change"
    sev: str = "must"
    expect: str = "kill"
    note: str = ""
    killer: str = ""
    extra: dict = field(default_factory=dict)


ALLOW_ALL = Entry("G1-01", [(MOD_PATH, 'return name in {"kb", "kb-sub"}', "return True")], title="allows anything")
SAME = Entry(
    "G1-02",
    [(MOD_PATH, '{"kb", "kb-sub"}', '{"kb", "kb-sub", "kb"}')],
    title="a repeated element in the set",
    expect="survive",
    note="the same set",
)
GAP = Entry("G1-03", [(MOD_PATH, '{"kb", "kb-sub"}', '{"kb", "kb-sub", "x"}')], title="allows one more name")
NOWHERE = Entry("G1-04", [(MOD_PATH, "this text is not in the file", "x")], title="anchors on nothing")
SLOW = Entry("G1-05", [(MOD_PATH, "return 0", "return 60")], title="a call that now takes a minute")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("")
    (root / MOD_PATH).write_text(MOD)
    (root / "tests").mkdir()
    (root / "tests" / "test_mod.py").write_text(TESTS)
    (root / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["src", "tests"]\n')
    return root


def _run(project: Path, tmp_path: Path, entries, **overrides):
    options = dict(
        repo=project,
        python=sys.executable,
        work=tmp_path / "work",
        results=tmp_path / "results.jsonl",
        workers=2,
        maxfail=3,
        timeout=60,
        deselect=[],
    )
    options.update(overrides)
    return rk.run_all(entries, **options), rk.load_results(options["results"])


# ---- applying a change -------------------------------------------------------------------


def test_a_change_is_written_once_and_put_back(project: Path):
    before = (project / MOD_PATH).read_text()
    originals = rk.apply(project, ALLOW_ALL.edits)
    assert "return True" in (project / MOD_PATH).read_text()
    rk.restore(project, originals)
    assert (project / MOD_PATH).read_text() == before


@pytest.mark.parametrize(
    ("old", "times"),
    [("this text is not in the file", 0), ("return", 2), ("name", 2)],
)
def test_an_old_text_that_is_absent_or_repeated_is_refused(project: Path, old: str, times: int):
    entry = Entry("X-1", [(MOD_PATH, old, "x")])
    problems = rk.check_entry(project, entry)
    assert len(problems) == 1 and f"occurs {times} times" in problems[0]
    with pytest.raises(ValueError):
        rk.apply(project, entry.edits)
    assert (project / MOD_PATH).read_text() == MOD, "a refused change leaves the file alone"


def test_a_change_that_breaks_the_syntax_is_refused(project: Path):
    entry = Entry("X-2", [(MOD_PATH, 'return name in {"kb", "kb-sub"}', "return name in {")])
    assert rk.check_entry(project, entry)
    with pytest.raises(SyntaxError):
        rk.apply(project, entry.edits)


def test_a_file_that_is_not_there_is_reported(project: Path):
    problems = rk.check_entry(project, Entry("X-3", [("src/pkg/missing.py", "a", "b")]))
    assert len(problems) == 1 and problems[0].startswith("X-3")


def test_a_second_edit_sees_the_first(project: Path):
    entry = Entry("X-4", [(MOD_PATH, "return 0", "return 1"), (MOD_PATH, "return 1", "return 2")])
    assert rk.check_entry(project, entry) == []
    rk.apply(project, entry.edits)
    assert "return 2" in (project / MOD_PATH).read_text()


# ---- reading a run -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"hung": True, "rc": None, "fails": []}, "killed-hang"),
        ({"hung": False, "rc": 0, "fails": []}, "survived"),
        ({"hung": False, "rc": 1, "fails": [{"kind": "FAILED"}]}, "killed"),
        ({"hung": False, "rc": 1, "fails": [{"kind": "ERROR"}]}, "killed-crash"),
        ({"hung": False, "rc": 1, "fails": [{"kind": "ERROR"}, {"kind": "FAILED"}]}, "killed"),
        ({"hung": False, "rc": 5, "fails": []}, "infra"),
        ({"hung": False, "rc": 2, "fails": []}, "infra"),
    ],
)
def test_what_counts_as_a_kill(result: dict, expected: str):
    assert rk.classify(result) == expected


def test_a_failing_test_keeps_its_whole_node_id():
    output = textwrap.dedent(
        """\
        FAILED tests/contract/test_a.py::test_x[not a folder] - AssertionError: assert 1 == 2
        FAILED tests/unit/test_b.py::test_y
        ERROR tests/unit/test_c.py - ImportError: no module named z
        """
    )
    assert rk.parse_failures(output) == [
        {"kind": "FAILED", "test": "tests/contract/test_a.py::test_x[not a folder]", "reason": "AssertionError: assert 1 == 2"},
        {"kind": "FAILED", "test": "tests/unit/test_b.py::test_y", "reason": ""},
        {"kind": "ERROR", "test": "tests/unit/test_c.py", "reason": "ImportError: no module named z"},
    ]


def test_a_kill_that_did_not_repeat_alone_is_a_survivor():
    assert rk.state({"status": "killed", "confirmed": True}) == "killed"
    assert rk.state({"status": "killed"}) == "killed"
    assert rk.state({"status": "killed", "confirmed": False}) == "survived"
    assert rk.state({"status": "killed-hang", "confirmed": False}) == "survived"
    assert rk.state({"status": "survived"}) == "survived"
    assert rk.state({"status": "infra"}) == "pending"
    assert rk.state(None) == "pending"


# ---- a whole run on a small project ------------------------------------------------------


@pytest.fixture(scope="module")
def small_run(tmp_path_factory):
    """One run of four entries over a small project, then one confirmation pass: shared by the
    tests below, because each run starts several test processes."""
    base = tmp_path_factory.mktemp("small_run")
    project = base / "project"
    (project / "src" / "pkg").mkdir(parents=True)
    (project / "src" / "pkg" / "__init__.py").write_text("")
    (project / MOD_PATH).write_text(MOD)
    (project / "tests").mkdir()
    (project / "tests" / "test_mod.py").write_text(TESTS)
    (project / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["src", "tests"]\n')
    entries = [ALLOW_ALL, SAME, GAP, NOWHERE]
    options = dict(
        repo=project,
        python=sys.executable,
        work=base / "work",
        results=base / "results.jsonl",
        workers=2,
        timeout=60,
        deselect=[],
    )
    code = rk.run_all(entries, maxfail=3, **options)
    before = rk.load_results(options["results"])
    options.pop("repo")
    confirm_code = rk.confirm(entries, repo=project, **options)
    return dict(
        project=project,
        entries=entries,
        code=code,
        confirm_code=confirm_code,
        before=json.loads(json.dumps(before)),
        after=rk.load_results(options["results"]),
    )


def test_a_run_kills_what_the_tests_catch(small_run):
    records = small_run["before"]
    assert small_run["code"] == 0
    assert records["G1-01"]["status"] == "killed"
    assert records["G1-01"]["fails"][0]["test"].endswith("::test_others_are_not")
    assert records["G1-02"]["status"] == "survived"
    assert records["G1-03"]["status"] == "survived"
    assert records["G1-04"]["status"] == "invalid" and "occurs 0 times" in records["G1-04"]["error"]
    assert (small_run["project"] / MOD_PATH).read_text() == MOD, "the project itself is never changed"


def test_the_report_says_what_was_killed_and_what_was_not(small_run):
    entries, gammas = small_run["entries"], {"G1": "Scope"}
    unconfirmed = rk.report(entries, gammas, small_run["before"])
    assert "| G1-01 | must | allows anything | `test_mod.py::test_others_are_not` (not re-run alone) |" in unconfirmed
    section = rk.report(entries, gammas, small_run["after"])
    assert "| G1-01 | must | allows anything | `test_mod.py::test_others_are_not` |" in section
    assert "| G1-02 | must | a repeated element in the set | **survives by design**: the same set |" in section
    assert "| G1-03 | must | allows one more name | **SURVIVES** |" in section
    assert "| G1-04 | must | anchors on nothing | not measured |" in section
    assert "| G1 Scope | 4 | 1 | 3 |" in section and "| **all** | **4** | **1** | **3** |" in section
    assert "Unexpected survivors (not marked by design): ['G1-03']" in section


def test_confirming_runs_each_kill_alone(small_run):
    assert small_run["confirm_code"] == 0
    after = small_run["after"]
    assert after["G1-01"]["confirmed"] is True
    assert "confirmed" not in after["G1-03"], "a survivor has no kill to confirm"


def test_a_kill_whose_test_passes_alone_does_not_count(project: Path, tmp_path: Path):
    """The failure seen in a full run came from somewhere else (load, or an earlier test). The
    entry's `killer` names the test that should kill it alone; here it does not."""
    stubborn = Entry(
        "G1-01",
        ALLOW_ALL.edits,
        killer="tests/test_mod.py::test_kb_is_allowed",  # passes with the change: not a killer
    )
    _run(project, tmp_path, [stubborn])
    rk.confirm(
        [stubborn],
        repo=project,
        python=sys.executable,
        work=tmp_path / "work",
        results=tmp_path / "results.jsonl",
        workers=1,
        timeout=60,
        deselect=[],
    )
    records = rk.load_results(tmp_path / "results.jsonl")
    assert records["G1-01"]["confirmed"] is False
    assert rk.state(records["G1-01"]) == "survived"
    assert "**SURVIVES** (its one failing test does not repeat alone)" in rk.report(
        [stubborn], {"G1": "Scope"}, records
    )


def test_a_run_is_void_when_the_known_bad_entry_survives(project: Path, tmp_path: Path):
    code, records = _run(project, tmp_path, [Entry("G1-01", SAME.edits)])
    assert code == 3
    assert records["G1-01"]["status"] == "survived"


def test_nothing_is_measured_when_the_unmutated_suite_fails(project: Path, tmp_path: Path):
    (project / "tests" / "test_broken.py").write_text("def test_broken():\n    assert False\n")
    code, records = _run(project, tmp_path, [ALLOW_ALL])
    assert code == 2
    assert records == {}


def test_the_known_bad_entry_is_always_measured(project: Path):
    chosen = rk.with_control([GAP], [ALLOW_ALL, SAME, GAP])
    assert [e.id for e in chosen] == ["G1-01", "G1-03"]
    assert [e.id for e in rk.with_control([ALLOW_ALL, GAP], [ALLOW_ALL, SAME, GAP])] == ["G1-01", "G1-03"]


def test_a_change_that_makes_a_later_test_wait_is_killed_at_the_first_failure(
    project: Path, tmp_path: Path
):
    """With several failures allowed, a suite that waits a minute in a later test never finishes.
    The runner then runs again stopping at the first failure."""
    entries = [ALLOW_ALL, SLOW]
    code, records = _run(project, tmp_path, entries, workers=1, timeout=4)
    assert code == 0
    slow = records["G1-05"]
    assert slow["status"] == "killed"
    assert slow["fails"][0]["test"].endswith("::test_a_first_failure_comes_before_a_slow_test")
    assert "-x" in slow["note"]


# ---- the command line --------------------------------------------------------------------

DEFINITIONS = textwrap.dedent(
    '''\
    from dataclasses import dataclass

    GAMMAS = {"G1": "Scope"}


    @dataclass
    class Mutant:
        id: str
        gamma: str
        title: str
        edits: list
        sev: str = "must"
        expect: str = "kill"
        note: str = ""
        killer: str = ""


    MUTANTS = [
        Mutant("G1-01", "G1", "allows anything",
               [("src/pkg/mod.py", 'return name in {"kb", "kb-sub"}', "return True")]),
    ]
    '''
)


def test_the_command_line_checks_runs_and_reports(project: Path, tmp_path: Path, capsys):
    definitions = tmp_path / "definitions.py"
    definitions.write_text(DEFINITIONS)
    results = tmp_path / "results.jsonl"
    base = ["--repo", str(project), "--definitions", str(definitions), "--results", str(results)]

    assert rk.main(["--check", *base]) == 0
    assert "1 entries, 0 problems" in capsys.readouterr().out

    assert rk.main(["--run", "--workers", "1", "--work", str(tmp_path / "w"), *base]) == 0
    assert json.loads(results.read_text().splitlines()[0])["status"] == "killed"

    assert rk.main(["--confirm", "--workers", "1", "--work", str(tmp_path / "w"), *base]) == 0
    capsys.readouterr()
    assert rk.main(["--report", *base]) == 0
    assert "| **all** | **1** | **1** | **0** |" in capsys.readouterr().out


def test_the_report_can_rewrite_the_section_between_the_markers(tmp_path: Path):
    doc = tmp_path / "doc.md"
    doc.write_text(f"intro, kept\n\n{rk.BEGIN}\n\nold section\n\n{rk.END}\n\nhistory, kept\n")
    rk.update_doc(doc, "new section\n")
    text = doc.read_text()
    assert text.startswith("intro, kept\n") and text.endswith("\nhistory, kept\n")
    assert "new section" in text and "old section" not in text
    again = doc.read_text()
    rk.update_doc(doc, "new section\n")
    assert doc.read_text() == again, "rewriting the same section changes nothing"
    doc.write_text("no markers here\n")
    with pytest.raises(SystemExit):
        rk.update_doc(doc, "x")
