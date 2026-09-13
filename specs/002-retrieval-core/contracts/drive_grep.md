# Contract: `drive_grep`

Deterministic exact search over bytes retrieved **in this call**. Folder scope is recursive. Not Drive `fullText`.

Must run Access Control chain first.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["pattern"],
  "properties": {
    "pattern": { "type": "string", "minLength": 1, "description": "Exact phrase in exported bytes (literal unless regex=true). Short term of art, not the whole user question. Not Drive fullText." },
    "file_ids": { "type": "array", "items": { "type": "string" } },
    "folder_id": { "type": "string" },
    "case_sensitive": { "type": "boolean", "default": true },
    "regex": { "type": "boolean", "default": false },
    "context_lines": { "type": "integer", "minimum": 0, "maximum": 10, "default": 2 },
    "max_matches": { "type": "integer", "minimum": 1, "maximum": 50 }
  }
}
```

If both `file_ids` and `folder_id` omitted → `default_whole_grant`, still budgeted (`PARTIAL` expected on large drives). `regex=false` → literal (`re.escape`). Invalid regex or out-of-range budgets → `INVALID_ARGUMENT`. Runtime engine failure after a valid compile → `SEARCH_ERROR`.

When **both** `folder_id` and `file_ids` are set: Access Control step 4 metadata-checks each named id. Granted file outside the folder → `AUTHORIZATION_ERROR`. Ungranted → `FILE_NOT_FOUND`.

## Output (success)

```json
{
  "type": "object",
  "required": ["status", "matches"],
  "properties": {
    "status": { "enum": ["COMPLETE", "PARTIAL", "EMPTY"] },
    "partial_reason": { "type": "string" },
    "matches": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["file_id", "file_name", "mime_type", "modified_time", "source_url", "retrieved_at", "pattern", "matched_text", "location"],
        "properties": {
          "file_id": { "type": "string" },
          "file_name": { "type": "string" },
          "mime_type": { "type": "string" },
          "modified_time": { "type": "string" },
          "source_url": { "type": "string" },
          "retrieved_at": { "type": "string" },
          "pattern": { "type": "string" },
          "matched_text": { "type": "string" },
          "location": { "type": "object" },
          "context": { "type": "string" }
        }
      }
    }
  }
}
```

No matches after complete search → `EMPTY`, `matches: []` (never fabricate). Identical bytes + identical params in this request → identical `matches`. Content discarded after the call. Walk cut by Google 429 → `PARTIAL`, `partial_reason: RATE_LIMITED` (even if `matches` is empty).

## Unsupported files

| Target | Result |
| --- | --- |
| Only `file_ids`, and every named file is unsupported / not exportable | `ERROR` / `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` |
| `folder_id` or `default_whole_grant` walk: mix of searchable and unsupported | Skip unsupported, search the rest, `PARTIAL` with `partial_reason` noting skips |
| Walk: every target unsupported | `ERROR` / `UNSUPPORTED_MIME_TYPE` or `FILE_NOT_EXPORTABLE` |
