# Contract: Authorization chain

Every MCP tool invocation MUST run this sequence. Retrieval tools MUST NOT call Drive **content** adapters (export, `get_media`, body-bearing list walks) until step 4 has passed.

```text
1. agent request
2. MCP authentication     → fail AUTHENTICATION_ERROR (HTTP 401 on Streamable HTTP `/mcp`)
     (OAuth 2.1 access token issued by this origin; see mcp-auth.md.
      MCP_AUTH_TOKEN is the consent password and MUST fail this step if sent as Bearer.)
3. MCP authorization      → fail AUTHORIZATION_ERROR (argument-level only; no Drive I/O)
     (no DRIVE_ALLOWED_FOLDER_ID → no_allowed_folder; rewrite an omitted
      folder to it; construct RetrievalScope from this call’s
      folder_id / file_ids / file_id; still no folder or file → whole_grant_refused)
4. Google authorization   (metadata-only files.get / parent lookups)
     → fail AUTHORIZATION_ERROR if a named id is not proven to be
        DRIVE_ALLOWED_FOLDER_ID or a descendant (outside, missing, or
        not granted: one reply, outside_allowed_folder)
     → fail FILE_NOT_FOUND if an id already proven inside that folder
        then misses (race)
     → fail AUTHORIZATION_ERROR if a caller-named file_id is outside
        this call’s folder_id (file_outside_folder)
5. resource (tool body: list / export / exact search)
```

## RetrievalScope construction

The type is defined in Retrieval Core (`specs/002-retrieval-core/data-model.md`). This context **enforces** it. Shared implementation: `src/google_drive_mcp/domain/retrieval_scope.py`.

From **this call’s** tool arguments, after an omitted folder is rewritten to the
required deployment `DRIVE_ALLOWED_FOLDER_ID` (cannot grant more than Google):

| Arguments | `default_whole_grant` | Scope |
| --- | --- | --- |
| Neither `folder_id` nor `file_ids` / `file_id` (blank ids count as omitted) | `false` after the rewrite | `DRIVE_ALLOWED_FOLDER_ID` (`kb`). A scope still `true` is refused (`whole_grant_refused`) |
| Only `folder_id` | `false` | That folder (ls: immediate children; find/grep: folder + descendants) |
| Only `file_ids` or `file_id` | `false` | Exactly those ids |
| Both `folder_id` and `file_ids` | `false` | Intersection: named files that lie in the folder (including the folder id itself) |

`DRIVE_ALLOWED_FOLDER_ID` is required. The server does not start when it is unset, blank, an alias such as `root` or `appDataFolder`, or not a plain id. Step 3 returns `AUTHORIZATION_ERROR` (`reason_code: no_allowed_folder`) for every call when it is missing, before any Google call. Omitted `folder_id` on `drive_ls` / `drive_find` / `drive_grep` is rewritten to that folder (never My Drive `root`). A named folder or file id that is not proven to be that folder or a descendant MUST return `AUTHORIZATION_ERROR` (`reason_code: outside_allowed_folder`) with no content, whether Google grants it, does not grant it, or it does not exist. The reply is the same in each case, so it does not reveal whether the id exists.

There is no whole-Google-grant scope. A call that names no folder or file after the rewrite is refused (`whole_grant_refused`), and no retrieval path lists Drive without a named folder.

## Invariants

- Step N is not entered unless N-1 returned pass.
- Document body, agent rationale, and prior `ALLOW` results are not inputs to any step.
- Drive **content** adapters (export, `get_media`) are not invoked on steps 2–3 failure, nor on step-4 `FILE_NOT_FOUND` / `AUTHORIZATION_ERROR`.
- Step 4 MAY call metadata-only `files.get` (id, name, mime, parents). Contract tests MUST count content I/O separately from metadata I/O.
- Write/share/delete methods do not exist on the adapter (nothing to authorize).
- Domain helper `is_within_scope(file_id, scope, parent_lookup)` is the single descendant check used by this chain **and** by retrieval walks. `parent_lookup` is a port; production uses Drive metadata, tests may inject a map.

## MCP authorization (step 3) — no Drive I/O

Step 3 only builds the `RetrievalScope` object and rejects **argument-level** contradictions that do not require Drive:

- Each tool accepts only the argument keys its body reads (`TOOL_ARGUMENTS` in `mcp/tools.py`). Any other key is `INVALID_ARGUMENT` before the chain runs, so a `file_id` on `drive_ls` cannot pass the chain and then be ignored. Blank ids in `file_id` / `file_ids` do not count as named, so they cannot skip the rewrite.
- No `DRIVE_ALLOWED_FOLDER_ID` → `AUTHORIZATION_ERROR` (`no_allowed_folder`).
- A scope that is still `default_whole_grant` after the rewrite → `AUTHORIZATION_ERROR` (`whole_grant_refused`). Single-axis and folder ∩ file_ids scopes pass step 3.
- Whether a named id lies inside the allow-list folder is a Drive fact, so step 4 checks it.

Step 3 MUST NOT walk parents and MUST NOT call the Drive adapter.

## Google authorization (step 4)

- Use only `drive.readonly`.
- Allow-list first. For every named `folder_id` / `file_id` / `file_ids` entry, run `is_within_scope` against `DRIVE_ALLOWED_FOLDER_ID` with metadata parent lookups. An id not proven to be that folder or a descendant → `AUTHORIZATION_ERROR` (`outside_allowed_folder`), no name/link/content. A parent lookup that Google answers with 404 / permission-as-404 counts as not proven, so an id outside the folder, a missing id, and an ungranted id get the same reply. Other Google failures during the lookup go through `map_google_error()` (for example `DRIVE_API_ERROR`).
- Then metadata `files.get` on each named id. Google not-found or permission-denied-as-not-found on an id already proven inside the allow-list folder (race): `FILE_NOT_FOUND`, no name/link/content.
- The MCP MUST NOT implement a second allow-list that could return **content** Google would deny.
- When the call names **both** `folder_id` and `file_ids` (v1 agent-visible: `drive_grep`; Access Control `evaluate_chain` uses the same arguments): for each named `file_id`, metadata `files.get` then `is_within_scope`.
  - Google does not grant the file → already `AUTHORIZATION_ERROR` from the allow-list check (no existence leak; do not mention the folder check).
  - Google grants the file but it is not the folder and not a descendant → `AUTHORIZATION_ERROR` (`file_outside_folder`). The caller already named both ids and both are inside the allow-list folder; implying existence of that named id is allowed.
- After `ALLOW`, later tool I/O can still 404 (race, export-only failure). Map those with the **same** `map_google_error()` as step 4 (`src/google_drive_mcp/domain/google_errors.py`). Retrieval Core MUST NOT invent a second 404 mapping.

## Reachable `AUTHORIZATION_ERROR` in v1 (per tool)

| Tool | `AUTHORIZATION_ERROR`? |
| --- | --- |
| `drive_read` | Yes: `file_id` not proven inside `DRIVE_ALLOWED_FOLDER_ID` (outside it, missing, or not granted), or no allow-list |
| `drive_ls` | Yes: named `folder_id` not proven inside the allow-list folder, or no allow-list |
| `drive_find` | Same as `drive_ls` |
| `drive_grep` | Yes: a named folder or file not proven inside the allow-list folder; **both** `folder_id` and `file_ids` set and a named file is outside that folder after a granted metadata get; or no allow-list |
| `evaluate_chain` (same args) | Same as the tool with the same arguments, including folder∩file_ids; used so Access Control can test AUTH without owning grep |
