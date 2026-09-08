# Contract: Error taxonomy (shared wire)

Flat agent-visible categories. Access Control owns the first three; Retrieval Core owns the rest. One envelope shape for all.

**Canonical copy.** Retrieval Core contracts MUST link here and MUST NOT define a second enum. Tool docs only add mapping rows.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://google-drive-mcp.local/contracts/error-envelope.json",
  "title": "ErrorEnvelope",
  "type": "object",
  "additionalProperties": false,
  "required": ["status", "category", "message"],
  "properties": {
    "status": { "const": "ERROR" },
    "category": {
      "type": "string",
      "enum": [
        "AUTHENTICATION_ERROR",
        "AUTHORIZATION_ERROR",
        "FILE_NOT_FOUND",
        "FILE_NOT_EXPORTABLE",
        "UNSUPPORTED_MIME_TYPE",
        "DRIVE_API_ERROR",
        "RATE_LIMITED",
        "RESOURCE_LIMIT",
        "TEMPORARY_STORAGE_ERROR",
        "SEARCH_ERROR",
        "INVALID_ARGUMENT"
      ]
    },
    "message": { "type": "string", "minLength": 1 },
    "request_id": { "type": "string" }
  }
}
```

Shared implementation: `ErrorEnvelope` in `src/google_drive_mcp/domain/errors.py`. Google HTTP mapping: `map_google_error()` in `src/google_drive_mcp/domain/google_errors.py` (used by the chain **and** by retrieval adapters for 404/403-as-404 and single-file 429). Walk 429 MUST be handled by the list/grep layer as completeness (`PARTIAL`), not by this mapper.

## Mapping rules (Access Control)

| Condition | category |
| --- | --- |
| Missing/invalid MCP bearer | `AUTHENTICATION_ERROR` |
| Caller-named `file_id` outside this call’s `folder_id` after Google **grants** metadata (see [authorization-chain.md](./authorization-chain.md)) | `AUTHORIZATION_ERROR` |
| Google grant does not include the resource (including Google 404 / permission-as-404), including post-`ALLOW` races | `FILE_NOT_FOUND` |

MUST NOT return `status: EMPTY` or `COMPLETE` for these failures.
MUST NOT include access tokens, refresh tokens, or unauthorized file metadata in `message`.

`FILE_NOT_FOUND` is dual-owned by design: Access Control raises it when Google’s grant does not include the resource (before or during the chain). After `ALLOW`, Retrieval Core raises the same category for a genuine miss or a later Google 404, **via the same mapper**. `map_google_error` also maps single-file HTTP 429 (no prefix) to `RATE_LIMITED`. It MUST NOT be used for list/find/grep walk 429.

## Mapping rules (Retrieval Core)

Completeness (`PARTIAL`) is **not** an `ErrorEnvelope`. See `specs/002-retrieval-core/contracts/result-status.md`.

| Condition | Result |
| --- | --- |
| Sustained Google rate-limit **cuts a list/find/grep walk short** (zero or more items already collected) | Tool success envelope with `status: PARTIAL`, `partial_reason: RATE_LIMITED`. **Do not** use `ErrorEnvelope.category = RATE_LIMITED`. **Do not** use `EMPTY` or `COMPLETE`. |
| Single-file read/export blocked by HTTP 429 with **no** usable prefix | `ErrorEnvelope` `RATE_LIMITED` |
| Prefix read within `max_bytes` / `max_export_size` | `status: PARTIAL`, `partial_reason: max_bytes` (not `RESOURCE_LIMIT`) |
| Export/download refused with **no** usable prefix (hard cap, not unsupported MIME) | `RESOURCE_LIMIT` |
| Cannot yield usable text | `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` |
| Bad argument shape, out-of-range budget, invalid regex | `INVALID_ARGUMENT` |
| Valid regex that fails at runtime inside the engine | `SEARCH_ERROR` |
| Tempfile create/cleanup failure | `TEMPORARY_STORAGE_ERROR` |
| Other Google/upstream failures | `DRIVE_API_ERROR` |
