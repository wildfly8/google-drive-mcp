# Contract: `drive_grep`

Deterministic exact search over bytes retrieved **in this call**. Folder scope is recursive. Not Drive `fullText`.

## Input

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["pattern"],
  "properties": {
    "pattern": { "type": "string", "minLength": 1 },
    "file_ids": { "type": "array", "items": { "type": "string" } },
    "folder_id": { "type": "string" },
    "case_sensitive": { "type": "boolean", "default": true },
    "regex": { "type": "boolean", "default": false },
    "context_lines": { "type": "integer", "minimum": 0, "maximum": 10, "default": 2 },
    "max_matches": { "type": "integer", "minimum": 1, "maximum": 50 }
  }
}
```

If both `file_ids` and `folder_id` omitted → default whole grant, still budgeted (`PARTIAL` expected on large drives). `regex=false` → literal (`re.escape`). Invalid regex → `INVALID_ARGUMENT`.

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
        "required": ["file_id", "file_name", "mime_type", "modified_time", "source_url", "retrieved_at", "pattern", "matched_text"],
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

No matches after complete search → `EMPTY`, `matches: []` (never fabricate). Identical bytes + identical params in this request → identical `matches`. Content discarded after the call.

Unsupported files in a folder walk: skip with a note in `partial_reason` or per-file error list without failing the whole grep, unless every target is unsupported — then `ERROR` / `UNSUPPORTED_MIME_TYPE`. Prefer continuing and `PARTIAL` if some files were skipped as unsupported while others were searched.
