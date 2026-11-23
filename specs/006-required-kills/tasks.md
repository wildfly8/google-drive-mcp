---
description: "Task list for Required Kills"
---

# Tasks: Required Kills

**Spec**: [spec.md](./spec.md) | **List**: [required-kills.md](./required-kills.md)

**Prerequisites**: spec.md, required-kills.md. There is no plan, research, data model or contracts file: the work adds tests and one list, and changes no behavior (PATCH, Article XIV).

**Organization**: One phase of work done on 2026-11-23, then the items that need the owner.

## Format: `[ID] [Story] Description`

- **[Story]**: US1-US3 map to the spec user stories
- Commit ids are in this repository

---

## Phase 1: Implemented (2026-11-23)

- [x] T001 [US1] Draft the list: 14 invariant groups and 208 entries from the constitution and the code, each a one-line wrong change with a class (FR-001, FR-002)
- [x] T002 [US2] Measure the 431-test suite against every entry on throwaway copies of the repo, with a null control and a known-bad control: 128 of 208 killed, 80 survived (FR-007)
- [x] T003 [US2] Re-run every kill alone: five were load flakes of one existing test and count as survivors; one (G7-01) is killed directly by `test_the_memo_lasts_one_call` (FR-007)
- [x] T004 [US2] Close the real gaps: 203 tests in 22 files, each passing on the real code and failing on the entry it was written for; 71 of the 80 survivors killed (34fe4a7, eb7e378) (FR-006)
- [x] T005 [US2] Fix found by T004: `redact()` replaced only the first word after `Authorization:`, so a Basic or Token credential kept its secret; it now takes the whole header value (34fe4a7)
- [x] T006 [US1] Mark the survivors that are not gaps (equivalent, unreachable, or enforced by a second layer) with their reasons, and add four second-order entries for the redundant layers (FR-004)
- [x] T007 [US2] Final measurement of all 212 entries against 636 tests with nothing excluded, under three parallel workers, then every kill re-run alone (SC-001, SC-002, SC-003). The rate-limit test counts requests up to the limit, so entry G11-20 (a limit raised a thousandfold) made it run for minutes instead of failing; `tests/contract/test_limits_pinned.py` now pins the rate limits and request caps by value, sorted before that test, and G11-18 to G11-20 were re-measured (638 tests)
- [x] T008 [US2] Fix found by T002: `_Fetching.__exit__` cancelled lookups that had not started when the check was refused, against its own rule that every named id gets one lookup. It no longer cancels them; `tests/unit/access_control/test_fetching.py` fails on the old code every time and passes on the fix, and `test_a_refused_call_still_looks_up_every_named_id` waits for in-flight lookups (300 runs under CPU load, 0 failures; it failed 3 in 120 before) (f222497) (FR-008)

## Phase 2: Needs the owner

- [ ] T009 [US1] Review the list item by item: add what is missing, cut or reclassify what is wrong, and decide which `should` and `may` entries matter (FR-005)
- [ ] T010 [US3] Decide whether the runner and the exact old-to-new text of every mutant move into the repository (outside `src/` and the image), so entries can be re-measured after a change; today they are outside it (FR-010)
- [ ] T011 [US3] Decide whether a change under `src/` should re-measure its invariant's entries before it is pushed, and where the owner's approval of an edit to the list is recorded (FR-005)
