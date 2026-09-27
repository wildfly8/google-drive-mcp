"""Stripe REST via httpx. Never logs secrets, PANs, or emails."""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx

from google_drive_mcp.infra.config import Settings

_STRIPE = "https://api.stripe.com"
_ENTITLED = frozenset({"active", "trialing"})


class StripeHttpGateway:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._client = client

    def _key(self) -> str:
        return self._settings.stripe_secret_key.get_secret_value().strip()

    def configured(self) -> bool:
        return bool(self._key() and self._settings.stripe_price_id.strip())

    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=20.0)

    def _auth(self) -> tuple[str, str]:
        return (self._key(), "")

    def is_subscription_active(self, customer_id: str) -> bool:
        if not customer_id or not self._key():
            return False
        owns = self._client is None
        http = self._http()
        try:
            response = http.get(
                f"{_STRIPE}/v1/subscriptions",
                params={"customer": customer_id, "status": "all", "limit": 10},
                auth=self._auth(),
            )
            if response.status_code != 200:
                return False
            data = response.json().get("data") or []
            return any(
                isinstance(item, dict) and str(item.get("status") or "") in _ENTITLED
                for item in data
            )
        except httpx.HTTPError:
            return False
        finally:
            if owns:
                http.close()

    def create_checkout_url(self, *, success_url: str, cancel_url: str) -> str:
        if not self.configured():
            raise RuntimeError("payments_not_configured")
        owns = self._client is None
        http = self._http()
        try:
            body = urlencode(
                {
                    "mode": "subscription",
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "line_items[0][price]": self._settings.stripe_price_id.strip(),
                    "line_items[0][quantity]": "1",
                }
            )
            response = http.post(
                f"{_STRIPE}/v1/checkout/sessions",
                content=body,
                headers={"content-type": "application/x-www-form-urlencoded"},
                auth=self._auth(),
            )
            response.raise_for_status()
            url = response.json().get("url")
            if not isinstance(url, str) or not url:
                raise RuntimeError("checkout_url_missing")
            return url
        finally:
            if owns:
                http.close()

    def customer_id_from_checkout_session(self, session_id: str) -> str | None:
        if not session_id or not self._key():
            return None
        owns = self._client is None
        http = self._http()
        try:
            response = http.get(
                f"{_STRIPE}/v1/checkout/sessions/{session_id}",
                auth=self._auth(),
            )
            if response.status_code != 200:
                return None
            payload = response.json()
            status = str(payload.get("status") or "")
            payment = str(payload.get("payment_status") or "")
            if status not in {"complete", "paid"} and payment not in {"paid", "no_payment_required"}:
                if status != "complete":
                    return None
            customer = payload.get("customer")
            if isinstance(customer, str) and customer.startswith("cus_"):
                return customer
            return None
        except httpx.HTTPError:
            return None
        finally:
            if owns:
                http.close()


def verify_stripe_signature(payload: bytes, header: str, secret: str, *, now: int | None = None) -> bool:
    """Stripe-Signature t=…,v1=… HMAC. Rejects stale timestamps."""
    if not secret or not header or not payload:
        return False
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        if "=" not in item:
            continue
        key, value = item.strip().split("=", 1)
        parts.setdefault(key, []).append(value)
    try:
        timestamp = int((parts.get("t") or [""])[0])
    except ValueError:
        return False
    v1 = (parts.get("v1") or [None])[0]
    if not v1:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > 300:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
