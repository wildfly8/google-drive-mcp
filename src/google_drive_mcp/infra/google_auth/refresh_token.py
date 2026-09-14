"""Request-scoped Google OAuth refresh-token credentials (Drive readonly)."""

from __future__ import annotations

import json
import uuid
from contextvars import ContextVar

from google.oauth2.credentials import Credentials

from google_drive_mcp.infra.config import Settings

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

_request_credentials: ContextVar[Credentials | None] = ContextVar(
    "google_drive_mcp_request_credentials", default=None
)


def mint_readonly_credentials(settings: Settings) -> Credentials:
    """Mint a new Credentials object for this request. Never a process global.

    Prefers ``GOOGLE_AUTHORIZED_USER_JSON`` (gcloud ADC blob) so a Cloud Agent
    login can be reused without a second OAuth consent. Falls back to the
    three-field refresh-token mint used by the original deploy path.
    """
    blob = settings.google_authorized_user_json.get_secret_value().strip()
    if blob:
        info = json.loads(blob)
        # Do not override ADC scopes with drive.readonly: the Cloud SDK OAuth
        # client rejects that unregistered scope on refresh. Use the grant
        # already on the blob (or omit scopes so the token endpoint reuses it).
        raw_scopes = info.get("scopes") or info.get("scope")
        if isinstance(raw_scopes, str):
            json_scopes = [item for item in raw_scopes.split() if item]
        elif isinstance(raw_scopes, list):
            json_scopes = [str(item) for item in raw_scopes if item]
        else:
            json_scopes = None
        creds = Credentials.from_authorized_user_info(info, scopes=json_scopes)
    else:
        creds = Credentials(
            token=None,
            refresh_token=settings.google_refresh_token.get_secret_value() or None,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id or None,
            client_secret=settings.google_client_secret.get_secret_value() or None,
            scopes=[DRIVE_READONLY_SCOPE],
        )
    # Unique per mint so isolation tests can distinguish objects.
    creds._mcp_request_key = str(uuid.uuid4())  # type: ignore[attr-defined]
    _request_credentials.set(creds)
    return creds


def current_credentials() -> Credentials | None:
    return _request_credentials.get()


def clear_request_credentials() -> None:
    _request_credentials.set(None)
