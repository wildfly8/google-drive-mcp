# Contract: Authorization chain

Every MCP tool invocation MUST run this sequence. Retrieval tools MUST NOT call Drive adapters until step 4 has passed.

```text
1. agent request
2. MCP authentication     → fail AUTHENTICATION_ERROR
3. MCP authorization      → fail AUTHORIZATION_ERROR
     (RetrievalScope: named folder/file list vs resource ids)
4. Google authorization   → fail FILE_NOT_FOUND
5. resource
```

## Invariants

- Step N is not entered unless N-1 returned pass.
- Document body, agent rationale, and prior `ALLOW` results are not inputs to any step.
- Google adapter is not invoked on steps 2–3 failure.
- Write/share/delete methods do not exist on the adapter (nothing to authorize).

## MCP authorization (step 3)

Given tool arguments:

- If `file_ids` or `folder_id` is present, each named id MUST lie inside the call’s RetrievalScope.
- Default scope (none named) is the whole Google grant; step 3 then passes through to Google for each resource actually touched.
- A `file_id` that is not a descendant of a stated `folder_id` (when folder_id was the scope) is `AUTHORIZATION_ERROR`.

## Google authorization (step 4)

- Use only `drive.readonly`.
- On Google not-found or permission-denied-as-not-found: `FILE_NOT_FOUND`, no name/link/content.
- The MCP MUST NOT implement a second allow-list that could return content Google would deny.
