"""Emailed sign-in links (Google Identity Platform) that prove inbox ownership.

Used only to continue an existing subscription in another browser. Google sends
the email; this server never stores the address. The Identity Platform user
created by a successful sign-in is deleted right away.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from google_drive_mcp.infra.config import Settings

_LOG = logging.getLogger("google_drive_mcp")
_IDENTITY = "https://identitytoolkit.googleapis.com/v1"


class EmailLinkPort(Protocol):
    def configured(self) -> bool: ...

    def send_link(self, email: str, continue_url: str) -> bool:
        """Ask Google to email a one-time sign-in link to this address."""
        ...

    def verified_email(self, email: str, oob_code: str) -> str | None:
        """The email, lower-cased, when the link's code was issued for it."""
        ...


class InactiveEmailLink:
    def configured(self) -> bool:
        return False

    def send_link(self, email: str, continue_url: str) -> bool:
        return False

    def verified_email(self, email: str, oob_code: str) -> str | None:
        return None


class IdentityPlatformEmailLink:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client

    def _key(self) -> str:
        return self._settings.identity_toolkit_api_key.get_secret_value().strip()

    def configured(self) -> bool:
        return bool(self._key())

    def _post(self, method: str, body: dict) -> httpx.Response | None:
        owns = self._client is None
        http = self._client or httpx.Client(timeout=15.0)
        try:
            return http.post(f"{_IDENTITY}/{method}", params={"key": self._key()}, json=body)
        except httpx.HTTPError:
            return None
        finally:
            if owns:
                http.close()

    def send_link(self, email: str, continue_url: str) -> bool:
        if not self._key():
            return False
        response = self._post(
            "accounts:sendOobCode",
            {
                "requestType": "EMAIL_SIGNIN",
                "email": email,
                "continueUrl": continue_url,
                "canHandleCodeInApp": True,
            },
        )
        if response is None or response.status_code != 200:
            _LOG.warning("email_link_send_failed")
            return False
        return True

    def verified_email(self, email: str, oob_code: str) -> str | None:
        if not self._key() or not email or not oob_code:
            return None
        response = self._post(
            "accounts:signInWithEmailLink", {"email": email, "oobCode": oob_code}
        )
        if response is None or response.status_code != 200:
            return None
        data = response.json()
        verified = str(data.get("email") or "").strip().lower()
        id_token = data.get("idToken")
        if isinstance(id_token, str) and id_token:
            # Keep no record of the address on Google's side either.
            self._post("accounts:delete", {"idToken": id_token})
        if not verified or verified != email.strip().lower():
            return None
        return verified
