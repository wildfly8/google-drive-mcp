"""Environment secrets. Values are never logged."""

from __future__ import annotations

import os
import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr

# Drive aliases that name a whole space rather than one folder.
DRIVE_SPACE_ALIASES = frozenset({"root", "appdatafolder"})
_FOLDER_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mcp_auth_token: SecretStr
    mcp_principal_id: str = Field(min_length=1)
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_refresh_token: SecretStr = SecretStr("")
    google_authorized_user_json: SecretStr = SecretStr("")
    drive_allowed_folder_id: str = ""
    mcp_public_url: str = "http://127.0.0.1"
    mcp_oauth_auto_approve: bool = False
    mcp_oauth_signing_key: SecretStr = SecretStr("")
    mcp_access_token_ttl_seconds: int = 3600
    mcp_refresh_token_ttl_seconds: int = 2592000
    mcp_authorization_code_ttl_seconds: int = 120
    mcp_subscription_required: bool = False
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_webhook_secret: SecretStr = SecretStr("")
    stripe_price_id: str = ""
    # Google Identity Platform key for emailed sign-in links (subscription restore).
    identity_toolkit_api_key: SecretStr = SecretStr("")

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("MCP_AUTH_TOKEN", "")
        principal = os.environ.get("MCP_PRINCIPAL_ID", "deployment")
        auto = os.environ.get("MCP_OAUTH_AUTO_APPROVE", "").strip().lower()
        paid = os.environ.get("MCP_SUBSCRIPTION_REQUIRED", "").strip().lower()
        return cls(
            mcp_auth_token=SecretStr(token),
            mcp_principal_id=principal,
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=SecretStr(os.environ.get("GOOGLE_CLIENT_SECRET", "")),
            google_refresh_token=SecretStr(os.environ.get("GOOGLE_REFRESH_TOKEN", "")),
            google_authorized_user_json=SecretStr(
                os.environ.get("GOOGLE_AUTHORIZED_USER_JSON", "")
            ),
            drive_allowed_folder_id=os.environ.get("DRIVE_ALLOWED_FOLDER_ID", "").strip(),
            mcp_public_url=os.environ.get("MCP_PUBLIC_URL", "").strip(),
            mcp_oauth_auto_approve=auto in {"1", "true", "yes"},
            mcp_oauth_signing_key=SecretStr(os.environ.get("MCP_OAUTH_SIGNING_KEY", "")),
            mcp_subscription_required=paid in {"1", "true", "yes"},
            stripe_secret_key=SecretStr(os.environ.get("STRIPE_SECRET_KEY", "")),
            stripe_webhook_secret=SecretStr(os.environ.get("STRIPE_WEBHOOK_SECRET", "")),
            stripe_price_id=os.environ.get("STRIPE_PRICE_ID", "").strip(),
            identity_toolkit_api_key=SecretStr(
                os.environ.get("IDENTITY_TOOLKIT_API_KEY", "").strip()
            ),
        )

    @classmethod
    def for_tests(cls) -> Settings:
        return cls(
            mcp_auth_token=SecretStr("test-token"),
            mcp_principal_id="deployment-1",
            google_client_id="test-client-id",
            google_client_secret=SecretStr("test-client-secret"),
            google_refresh_token=SecretStr("test-refresh-token"),
            mcp_public_url="http://127.0.0.1",
            mcp_oauth_auto_approve=True,
            # FakeDrive's top folder stands in for kb.
            drive_allowed_folder_id="root",
        )

    def require_allowed_folder(self) -> str:
        """Return the allow-list folder id, or raise ValueError.

        Only that folder and its descendants are readable, so the server must
        not start without one, or with an alias for a whole Drive space.
        """
        folder = self.drive_allowed_folder_id.strip()
        if not folder:
            raise ValueError(
                "DRIVE_ALLOWED_FOLDER_ID is not set. Set it to the kb folder id; "
                "nothing else is readable."
            )
        if folder.lower() in DRIVE_SPACE_ALIASES or not _FOLDER_ID_RE.fullmatch(folder):
            raise ValueError(
                "DRIVE_ALLOWED_FOLDER_ID must be one Drive folder id (the kb folder), "
                "not an alias such as root."
            )
        return folder

    def __repr__(self) -> str:
        return (
            f"Settings(mcp_principal_id={self.mcp_principal_id!r}, "
            f"drive_allowed_folder_id={self.drive_allowed_folder_id!r}, "
            f"mcp_public_url={self.mcp_public_url!r}, "
            "mcp_auth_token=***, google_*=***)"
        )

    __str__ = __repr__
