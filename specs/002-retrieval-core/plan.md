# Implementation Plan: Retrieval Core

**Branch**: `main` (spec dir `002-retrieval-core`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-retrieval-core/spec.md`

**Upstream**: Access Control (`specs/001-access-control/`) — this feature never authenticates or authorizes; tools run only after `ALLOW`.

## Summary

Expose four read-only MCP tools — `drive_ls`, `drive_find`, `drive_read`, `drive_grep` — so an agent can iterate `discover → read → exact search` against live Google Drive. No RAG index, no persistent document copy. Candidates are not evidence; `DocumentContent` and `SearchMatch` with provenance play the evidence role (no separate Evidence class). Grep is deterministic over request-scoped bytes. Truncation and walk 429 are `PARTIAL`.

Technical approach: domain operations (discover/inspect/search) behind ports; Google Drive list/export/download and stdlib `re` are adapters (Article XII). `RetrievalScope.default_whole_grant` is the whole Google grant; a folder or file list narrows one call. `drive_ls` with omitted folder **projects** that grant onto My Drive `root` children (not the same universe as omitted-folder find/grep). `find`/`grep` on a folder include descendants via shared `is_within_scope`. Wire view-link field is `source_url`. Mixed-folder grep skips unsupported files (`PARTIAL`); single-id unsupported is a classified error.

Google 404/403-as-404 (and single-file 429 with no prefix) go through Access Control’s `map_google_error()`. Walk 429 is intercepted in list/grep as `PARTIAL` (`partial_reason: RATE_LIMITED`), not `ErrorEnvelope` `RATE_LIMITED`. AUTH folder∩file_ids on real `drive_grep` is replayed after the tool exists (Access Control already tested the same args on the stub).

## Technical Context

**Language/Version**: Python 3.12 (same package as Access Control)

**Primary Dependencies**: `mcp` 2.x; Google Drive v3 via `google-api-python-client` (adapter); stdlib `re` for exact search; `pydantic` for tool I/O

**Storage**: None persistent. Exports live in memory or `tempfile.TemporaryDirectory` deleted at end of the tool call.

**Testing**: pytest; contract tests from `contracts/`; integration tests against shared `tests/fakes/fake_drive.py`; AUTH replay on real `drive_grep`; `PARTIAL` including `max_execution_time`; optional live Drive smoke

**Target Platform**: Linux, Cloud Run Streamable HTTP MCP. Same process as Access Control.

**Project Type**: MCP web service (stateless)

**Performance Goals**: Correctness → retrieval quality → security → simplicity, then latency. Default budgets below; a usable prefix or partial listing is `PARTIAL`; a hard export refusal with no prefix is `RESOURCE_LIMIT`; a walk cut by 429 is `PARTIAL` (`partial_reason: RATE_LIMITED`). Never silent.

**Constraints**: Read-only adapter methods only. Drive export cap 10 MB; we cap below that. No embeddings. Tool names/meanings must not depend on a single LLM vendor.

**Scale/Scope**: One Drive identity; iterative tool calls; tens of files per operation by default, not a corpus index.

### Default resource budgets (plan-level, spec FR-104)

| Budget | Default |
| --- | --- |
| `max_files` | 40 |
| `max_bytes` per file / export | 5_000_000 |
| `max_bytes` per operation | 20_000_000 |
| `max_matches` | 50 |
| `max_execution_time` | 25 seconds |
| `max_context_lines` | 2 |
| `max_export_size` | 5_000_000 |

Sheets/Slides context: character window of 200 characters around a match when the representation is not line-oriented; Docs/plain text use `max_context_lines`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Fitness line (Art. XV) | Gate |
| --- | --- |
| Drive is authoritative | PASS — read/export at call time; no MCP-owned replica |
| the server is read-only | PASS — four tools only; no write code paths |
| document content is untrusted | PASS — content cannot change tool control flow |
| retrieval can iterate | PASS — tools are primitives; agent owns the loop |
| exact search is deterministic | PASS — stdlib `re` over retrieved bytes in-request |
| evidence carries provenance | PASS — `file_id` required on content-derived results |
| partiality is visible | PASS — `COMPLETE`/`PARTIAL`/`EMPTY`/`ERROR` |
| compute is ephemeral | PASS — discard exports after the operation |
| no hidden persistent state exists | PASS — no index, no cache |
| authorization is independently enforced | PASS — conformist; chain is upstream |
| agent reasoning and retrieval mechanics stay separate | PASS — no sufficiency/synthesis |
| no RAG index is required for correctness | PASS |

**Post-Phase 1 re-check:** Still PASS. Contracts are read/search/enumerate. Budgets and walk 429 emit `PARTIAL`. `map_google_error` is not used for walk 429. Export map is infrastructure, not a second source of truth. Evidence is a role, not a type.

## Project Structure

### Documentation (this feature)

```text
specs/002-retrieval-core/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/           # includes error-taxonomy.md pointer to Access Control
└── tasks.md
```

### Source Code (repository root)

```text
src/google_drive_mcp/
├── domain/
│   ├── errors.py
│   ├── google_errors.py     # shared mapper: 404/403-as-404; single-file 429; not walk 429
│   ├── budgets.py
│   ├── drive_file.py
│   ├── provenance.py
│   ├── retrieval_scope.py   # is_within_scope; implemented in Access Control T005
│   ├── candidates.py
│   ├── content.py
│   ├── matches.py
│   └── operation.py
├── retrieval/
│   ├── ports.py
│   ├── ls.py
│   ├── find.py
│   ├── read.py
│   └── grep.py
├── infra/
│   ├── google_drive/
│   │   ├── list.py          # files.list / get metadata; uses is_within_scope
│   │   └── export.py        # files.export / get_media
│   └── exact_search/
│       └── regex.py         # stdlib re, swappable port
├── mcp/
│   ├── server.py            # composition root (Access Control); mounts tools.py
│   └── tools.py             # drive_ls, drive_find, drive_read, drive_grep
tests/
├── fakes/
│   └── fake_drive.py        # same port as Access Control; populate store here
├── contract/
├── integration/
└── unit/
    └── retrieval/
```

**Structure Decision**: Same single package as Access Control. Retrieval owns `retrieval/`, Drive content adapters, exact-search adapter, and MCP tool registration. Access-control middleware wraps every tool. `mcp/server.py` remains the composition root (do not start a second server). One fake Drive: `tests/fakes/fake_drive.py`. Do not fork `RetrievalScope` or a second parent walk. T040 scans `infra/google_drive` for write methods.

## Complexity Tracking

> No constitution violations requiring justification.
