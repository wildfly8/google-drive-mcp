# Required kills: the runner

The list of wrong changes the test suite must reject is in
[`specs/006-required-kills/required-kills.md`](../../specs/006-required-kills/required-kills.md), and what it
means and who owns it is in [`spec.md`](../../specs/006-required-kills/spec.md). This directory holds the
tooling that measures it. It is outside `src/` and the container image on purpose: the server has no
code that edits code.

| file | what it is |
|---|---|
| `definitions.py` | every entry as data: an id (`G4-13`), a group, a class, a one-line description, and the exact text edits |
| `run.py` | applies one entry at a time to a copy of the repository, runs the suite on the copy, records killed or survived |

The runner uses only the standard library and the repository's own test environment (`uv sync`, then
`uv run python scripts/required_kills/run.py ...`). It never edits the repository: every change is made in
a throwaway copy.

## Commands

```
run.py --check                       every entry applies to the code as it is (old text once, code compiles)
run.py --run [--workers 3] [--only G1-01,G4-13] [--groups G1,G4]
run.py --confirm                     re-run each kill's test alone against its change
run.py --report [--update-doc specs/006-required-kills/required-kills.md]
```

Results go to `.required-kills/results.jsonl` (ignored by git); a later record for an entry replaces an
earlier one, so `--only` can re-measure a few entries. A full run is 212 entries, about 12 minutes with
three workers on four cores. `--check` takes a second and runs in the suite (see below).

## What makes a run count

1. **Null control.** The unmutated suite must pass on every worker, under the same load. If it does not, the
   run stops and nothing is measured. A flaky test shows up here first.
2. **Known-bad control.** Entry `G1-01` (any id the lookup returns is allowed) is always measured, and must
   be killed. If it survives, the run is void: a green result would prove nothing.
3. **Confirmation.** `--confirm` runs each kill's failing test alone against the same change. A kill that does
   not repeat was a load flake or an order dependence, and counts as a survivor. For an entry whose failures
   only happen after other tests have run, name the test that kills it alone in its `killer=` field.

Statuses in the results: `killed` (a test failed), `killed-crash` (only errors, no failed test: weaker),
`killed-hang` (the suite did not finish in time), `survived`, `invalid` (the entry does not apply), `infra`
(the run produced no verdict). With `--maxfail 3` (the default) a change that makes a *later* test wait for
minutes would hang the run, so a timeout is followed by one more run that stops at the first failure.

## Adding or changing an entry

1. Write it in `definitions.py`: an id in its group, a class (`must`, `should`, `may`), a one-line title, and
   the edits. Each old text must occur exactly once in its file. `run.py --check` says if it does not.
2. `run.py --run --only <id>`. If it survives, write a test that fails on the change and passes on the real
   code, and measure again. If no test can tell the change from the real code (equivalent, unreachable, or a
   second layer enforces the same property), mark it `expect="survive"` with the reason in `SURVIVOR_NOTES`,
   and add a second-order entry that removes the redundant layers together.
3. `run.py --confirm`, then `run.py --report --update-doc specs/006-required-kills/required-kills.md`.

Adding an entry is the owner's decision, and an agent may not remove or downgrade one to make the suite pass
(spec 006, FR-005).

## Kept in step by the suite

`tests/unit/test_required_kills_definitions.py` fails when an entry no longer applies to the code (a line it
changes was edited), when the committed list and the definitions differ, or when an entry that survives has no
reason. If you edit a line under `src/` on purpose and it fails, update that entry and measure it again. While the
runner measures, it sets `REQUIRED_KILLS_MEASURING=1` and the first of those checks skips itself: the code is
changed on purpose then, and the check would "kill" every entry.
`tests/unit/test_required_kills_runner.py` tests the runner on a small project of its own.
