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
        creds = Credentials.from_authorized_user_info(
            info,
            scopes=[DRIVE_READONLY_SCOPE],
        )
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
