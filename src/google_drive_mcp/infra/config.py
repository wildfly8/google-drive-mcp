"""Environment secrets. Values are never logged."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mcp_auth_token: SecretStr
    mcp_principal_id: str = Field(min_length=1)
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_refresh_token: SecretStr = SecretStr("")
    google_authorized_user_json: SecretStr = SecretStr("")

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("MCP_AUTH_TOKEN", "")
        principal = os.environ.get("MCP_PRINCIPAL_ID", "deployment")
        return cls(
            mcp_auth_token=SecretStr(token),
            mcp_principal_id=principal,
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=SecretStr(os.environ.get("GOOGLE_CLIENT_SECRET", "")),
            google_refresh_token=SecretStr(os.environ.get("GOOGLE_REFRESH_TOKEN", "")),
            google_authorized_user_json=SecretStr(
                os.environ.get("GOOGLE_AUTHORIZED_USER_JSON", "")
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
        )

    def __repr__(self) -> str:
        return (
            f"Settings(mcp_principal_id={self.mcp_principal_id!r}, "
            "mcp_auth_token=***, google_*=***)"
        )

    __str__ = __repr__
