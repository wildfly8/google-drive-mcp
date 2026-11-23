# Feature Specification: Required Kills (the suite must reject these wrong changes)

**Branch**: `main`

**Spec directory**: `specs/006-required-kills`

**Created**: 2026-11-23

**Status**: Drafted and measured by the agent, committed at the owner's request on 2026-11-23. The list in [required-kills.md](./required-kills.md) is a proposal the owner has not yet reviewed item by item (T009). The suite kills all but 11 of its 212 entries, and those 11 are marked as surviving by design (T001-T007). The runner and the exact mutant definitions are in `scripts/required_kills/` (T010).

**Input**: User description: "in light of above certifiable agentic AI engineering principle and constraint-based admissible generative modal transition structuralism, what're Required-kill list per invariant in this project?", then "write the closing tests for the real gaps" and "fix the race and commit the required-kills spec". The principle: an agent cannot be verified, but the boundary it works inside can. The human owns the boundary (the invariants, the anti-scenarios and a required-kill list per invariant); agents write code and tests inside it, and a harness the agent cannot edit checks that the tests catch the wrong changes.

**Constitution**: Bound to ratified v2.1.0, Articles I-XV. **PATCH** (Article XIV): this spec adds tests and documentation and changes no behavior or invariant. It does not amend the constitution. It lists, per invariant, the wrong changes a suite must catch.

**Bounded Context**: Verification (outside the running server; checks that the code the other five specs define keeps doing what they require)

## Clarifications

### Session 2026-11-23

- Q: What is a required kill? → A: A deliberately wrong change to the server code, small enough to read in one line, that the test suite must fail on. In modal-transition terms an invariant fixes which transitions are *must* (refuse an id outside kb, refuse an unpaid caller, report PARTIAL when a cap stopped the scan) and which are *may* (the order of independent work, speed). A required kill turns a *must* into a *may*, or removes it. Killing it means the suite rejects that inadmissible change.
- Q: Who owns the list? → A: The owner. The agent drafted this one and wrote the tests that close it, so both share the agent's reading of the invariants. That is the oracle problem; the owner's review of the list is the check that does not share it. The agent may propose entries, and may not remove or downgrade one to make the suite pass (FR-005).
- Q: Are all entries equal? → A: No. Each has a class. `must` flips a must-transition (safety, paywall, completeness). `should` makes the service worse or less faithful without being unsafe. `may` changes only speed or order.
- Q: What if no test can tell an entry from the real code? → A: It is either equivalent (the same behavior) or covered by a second layer that enforces the same property. It stays on the list, marked as surviving by design, with the reason. Removing the redundant layers together is its own entry (second order, id `S`) and must be killed.
- Q: Is the runner part of this spec? → A: Yes since 2026-11-23, at the owner's request. The runner and the exact old-to-new text of each entry are tooling in `scripts/required_kills/`, outside `src/` and the container image. The entries drift as the code changes, so a test fails when one no longer applies (FR-011).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The owner reviews and edits the list (Priority: P1)

The owner reads the entries for one invariant, sees what a wrong change would be and which test kills it, and adds, cuts or reclassifies entries.

**Why this priority**: The list is only worth anything if the person who owns the invariants has read it. Entries the owner never saw are the agent's opinion.

**Independent Test**: Open `required-kills.md`; for any invariant, every row names the wrong change in words, its class and the test that kills it (or why it survives).

**Acceptance Scenarios**:

1. **Given** an entry the owner thinks is missing, **When** it is added with its class, **Then** a mutant for it is written and a test that fails on it is added or named (FR-002, FR-006).
2. **Given** an entry the owner thinks is wrong, **When** it is removed or reclassified, **Then** the reason is recorded in the same commit (FR-005).

---

### User Story 2 - A wrong change to an invariant fails the suite (Priority: P1)

A later change by anyone, including an agent, that breaks one of the invariants on the list fails `pytest` before it can be pushed to `main`, which deploys.

**Why this priority**: A green suite is only evidence if it goes red when the code is wrong. The server holds the owner's Drive credential and takes payments.

**Independent Test**: Apply any one entry's change to a copy of the code and run `uv run pytest -q --ignore=tests/e2e`. It fails, and the failing test is the one named in the list.

**Acceptance Scenarios**:

1. **Given** the real code, **When** the suite runs, **Then** it passes (the null control, FR-007).
2. **Given** an entry whose class is `must`, **When** its change is applied, **Then** at least one test fails (FR-003).
3. **Given** a test named as the killer of an entry, **When** it is run alone against the entry's change, **Then** it fails; a test that fails only after other tests have run is not the killer (FR-007).

---

### User Story 3 - The list is measured again after a change (Priority: P2)

After a change to code under an invariant, the entries for that invariant are applied again, so a test that was deleted or weakened shows up.

**Why this priority**: Tests rot. A required kill that was killed once can stop being killed.

**Independent Test**: `python scripts/required_kills/run.py --run --groups G4`, then `--confirm` (FR-007), over one invariant's entries.

**Acceptance Scenarios**:

1. **Given** a weakened test, **When** the entries it kills are applied again, **Then** at least one survives and the run reports it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every constitutional invariant that code can break has a group of required kills in [required-kills.md](./required-kills.md): G1 scope, G2 read-only, G3 authentication, G4 paywall, G5 completeness, G6 exactness and determinism, G7 ephemerality and isolation, G8 provenance and citation, G9 failure taxonomy, G10 secrets and logs, G11 abuse limits, G12 documents are data, G13 speed, G14 the OAuth and identity surface.
- **FR-002**: Each entry has an id, a class, the wrong change in one line a reader can check against the code, and the test that kills it now (or the reason it survives).
- **FR-003**: Every `must` entry is killed by the suite, or is marked as surviving by design with its reason (FR-004).
- **FR-004**: An entry that the suite cannot tell from the real code stays on the list, marked as surviving by design, with the reason (equivalent, unreachable, or enforced by a second layer). Removing two redundant layers together is a second-order entry and must be killed.
- **FR-005**: Adding, removing or reclassifying an entry is the owner's decision. An agent may propose, and may not remove or downgrade an entry to make the suite pass.
- **FR-006**: A test written to close an entry passes on the unmodified code and fails on the entry's change.
- **FR-007**: A measurement is void unless the unmodified suite passes under the same load (the null control) and a known-bad entry (G1-01) is killed. Every kill is re-run alone, and a kill that does not repeat is counted as a survivor.
- **FR-008**: A test whose result depends on thread timing does not count as a kill. The access check's lookups used to be cancelled on a refusal, so `test_a_refused_call_still_looks_up_every_named_id` failed about 3 times in 120 runs under load and produced false kills; the lookups are no longer cancelled and the test waits for them (T008).
- **FR-009**: The list is not a proof. A threat that is not on it is not covered, and a killed entry means a test notices that change, not that the invariant holds in every other case.
- **FR-010**: The runner and the exact mutant definitions are tooling, kept outside `src/` and the container image, in `scripts/required_kills/` (`run.py`, `definitions.py`, `README.md`). The runner never edits the repository: every change is made in a throwaway copy. It implements FR-007, and its own behavior is tested (`tests/unit/test_required_kills_runner.py`).
- **FR-011**: The definitions are kept in step with the code and with the list. A test fails when an entry's old text no longer occurs exactly once, when the list in [required-kills.md](./required-kills.md) and the definitions name different entries, and when an entry that survives gives no reason (`tests/unit/test_required_kills_definitions.py`). A deliberate edit to a guarded line therefore means updating that entry and measuring it again.

### Key Entities

- **Invariant**: a line of the constitution that code can break (Articles I-XV).
- **Required kill (entry)**: one wrong change, with an id (`G4-13`), a class, a one-line description and its killer.
- **Killer**: the test that fails on the entry's change.
- **Survivor by design**: an entry no test can tell from the real code, with the reason.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All `must` entries are killed or marked as surviving by design. At the time of writing 201 of 212 are killed and 11 are marked (9 first-order, 2 second-order).
- **SC-002**: Each recorded killer still fails when run alone against its entry's change.
- **SC-003**: The unmodified suite passes under three parallel measurement workers, with no test excluded.

## Assumptions

- The mutants and their measurement are an aid to the owner's review. They do not replace it.
- Entries describe the code as of this commit. When the code under an invariant changes, its entries are re-measured (User Story 3), and the entry text is updated where it no longer matches; the suite fails until it is (FR-011).
- Out of scope: running the mutants in CI, property-based tests, and any change to the constitution.
