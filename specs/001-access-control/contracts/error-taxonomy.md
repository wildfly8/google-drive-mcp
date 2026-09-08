# Contract: Error taxonomy (shared wire)

Flat agent-visible categories. Access Control owns the first three; Retrieval Core owns the rest. One envelope shape for all.

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

## Mapping rules (Access Control)

| Condition | category |
| --- | --- |
| Missing/invalid MCP bearer | `AUTHENTICATION_ERROR` |
| Named resource outside this call’s RetrievalScope | `AUTHORIZATION_ERROR` |
| Google grant does not include the resource (including Google 404 / permission-as-404) | `FILE_NOT_FOUND` |

MUST NOT return `status: EMPTY` or `COMPLETE` for these failures.
MUST NOT include access tokens, refresh tokens, or unauthorized file metadata in `message`.
