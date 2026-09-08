# Contract: Authorization chain

Every MCP tool invocation MUST run this sequence. Retrieval tools MUST NOT call Drive **content** adapters (export, `get_media`, body-bearing list walks) until step 4 has passed.

```text
1. agent request
2. MCP authentication     → fail AUTHENTICATION_ERROR
3. MCP authorization      → fail AUTHORIZATION_ERROR (argument-level only; no Drive I/O)
     (construct RetrievalScope from this call’s folder_id / file_ids / file_id)
4. Google authorization   → fail FILE_NOT_FOUND
     (metadata-only files.get as needed)
     → fail AUTHORIZATION_ERROR if Google grants a caller-named file_id
        that is outside this call’s folder_id
5. resource (tool body: list / export / exact search)
```

## RetrievalScope construction

The type is defined in Retrieval Core (`specs/002-retrieval-core/data-model.md`). This context **enforces** it. Shared implementation: `src/google_drive_mcp/domain/retrieval_scope.py`.

From **this call’s** tool arguments only (v1 has no deployment-narrower allow-list):

| Arguments | `default_whole_grant` | Scope |
| --- | --- | --- |
| Neither `folder_id` nor `file_ids` / `file_id` | `true` | Whole Google grant for this deployment identity |
| Only `folder_id` | `false` | That folder (ls: immediate children; find/grep: folder + descendants) |
| Only `file_ids` or `file_id` | `false` | Exactly those ids |
| Both `folder_id` and `file_ids` | `false` | Intersection: named files that lie in the folder (including the folder id itself) |

`drive_ls` with omitted `folder_id` still uses `default_whole_grant = true`. Listing **projects** that grant onto My Drive `root`’s immediate children (Retrieval Core invariant). That projection is not an MCP authorization failure.

## Invariants

- Step N is not entered unless N-1 returned pass.
- Document body, agent rationale, and prior `ALLOW` results are not inputs to any step.
- Drive **content** adapters (export, `get_media`) are not invoked on steps 2–3 failure, nor on step-4 `FILE_NOT_FOUND` / `AUTHORIZATION_ERROR`.
- Step 4 MAY call metadata-only `files.get` (id, name, mime, parents). Contract tests MUST count content I/O separately from metadata I/O.
- Write/share/delete methods do not exist on the adapter (nothing to authorize).
- Domain helper `is_within_scope(file_id, scope, parent_lookup)` is the single descendant check used by this chain **and** by retrieval walks. `parent_lookup` is a port; production uses Drive metadata, tests may inject a map.

## MCP authorization (step 3) — no Drive I/O

Step 3 only builds the `RetrievalScope` object and rejects **argument-level** contradictions that do not require Drive:

- Unknown extra resource ids that are not tool arguments cannot appear (tools have no side channel).
- v1 has no ambient/deployment allow-list, so `default_whole_grant` and single-axis scopes **pass** step 3.
- `drive_read` (`file_id` only) therefore **never** returns `AUTHORIZATION_ERROR` in v1. A Google miss is `FILE_NOT_FOUND`.
- `drive_ls` / `drive_find` with only `folder_id` (or omitted folder) **never** return `AUTHORIZATION_ERROR` in v1 for “wrong folder.” A Google-missing folder is `FILE_NOT_FOUND`.

Step 3 MUST NOT walk parents and MUST NOT call the Drive adapter.

## Google authorization (step 4)

- Use only `drive.readonly`.
- On Google not-found or permission-denied-as-not-found: `FILE_NOT_FOUND`, no name/link/content.
- The MCP MUST NOT implement a second allow-list that could return **content** Google would deny.
- When the call names **both** `folder_id` and `file_ids` (v1 agent-visible: `drive_grep`; Access Control US1 stub/`evaluate_chain` uses the same arguments): for each named `file_id`, metadata `files.get` then `is_within_scope`.
  - Google does not grant the file → `FILE_NOT_FOUND` (no existence leak; do not mention the folder check).
  - Google grants the file but it is not the folder and not a descendant → `AUTHORIZATION_ERROR`. The caller already named both ids; implying existence of that named id is allowed.
- After `ALLOW`, later tool I/O can still 404 (race, export-only failure). Map those with the **same** `map_google_error()` as step 4 (`src/google_drive_mcp/domain/google_errors.py`). Retrieval Core MUST NOT invent a second 404 mapping.

## Reachable `AUTHORIZATION_ERROR` in v1 (per tool)

| Tool | `AUTHORIZATION_ERROR`? |
| --- | --- |
| `drive_read` | No |
| `drive_ls` | No |
| `drive_find` | No |
| `drive_grep` | Yes, only when **both** `folder_id` and `file_ids` are set and a named file is outside that folder after a granted metadata get |
| US1 stub / `evaluate_chain` (same args) | Same as `drive_grep`; used so Access Control can test AUTH before grep exists |
