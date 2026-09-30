"""Google credentials for the temporary kb write tools (DRIVE_WRITE_ENABLED).

Kept apart from refresh_token.py so the read path only ever asks for
drive.readonly. The Google grant behind these secrets must include the drive
scope, or Google refuses every write.
"""

from __future__ import annotations

from google.oauth2.credentials import Credentials

from google_drive_mcp.infra.config import Settings
from google_drive_mcp.infra.google_auth.refresh_token import build_credentials

DRIVE_WRITE_SCOPE = "https://www.googleapis.com/auth/drive"


def mint_write_credentials(settings: Settings) -> Credentials:
    return build_credentials(settings, refresh_scopes=[DRIVE_WRITE_SCOPE])
