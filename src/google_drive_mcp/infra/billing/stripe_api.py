"""Stripe REST via httpx.

This module never logs secrets, PANs, emails or customer ids: failures log only an
HTTP status or an exception type. An email lookup puts the address in the request
URL, and httpx logs request URLs at INFO, so `configure_logging` keeps httpx at
WARNING.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx

from google_drive_mcp.infra.config import Settings

_LOG = logging.getLogger("google_drive_mcp")
_STRIPE = "https://api.stripe.com"
_ENTITLED = frozenset({"active", "trialing"})
# Stripe asks clients to retry these; a blip must not read as "not subscribed".
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_DELAYS = (0.25, 0.75)


def _warn(event: str, *, http_status: int | None = None, error: str | None = None) -> None:
    # A status or an exception type only: never a customer id, email or Stripe message.
    extra: dict[str, object] = {"event": event}
    if http_status is not None:
        extra["http_status"] = http_status
    if error is not None:
        extra["error_category"] = error
    _LOG.warning(event, extra=extra)


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

    def _get_retrying(self, http: httpx.Client, url: str, params: dict) -> httpx.Response | None:
        """GET with short retries on Stripe rate limits, 5xx and connect errors."""
        for attempt in range(len(_RETRY_DELAYS) + 1):
            last = attempt == len(_RETRY_DELAYS)
            try:
                response = http.get(url, params=params, auth=self._auth())
            except (httpx.ConnectError, httpx.RemoteProtocolError):
                if last:
                    return None
            else:
                if response.status_code not in _RETRY_STATUS or last:
                    return response
            time.sleep(_RETRY_DELAYS[attempt])
        return None

    def subscription_state(self, customer_id: str) -> bool | None:
        """True or False when Stripe answered; None when Stripe could not be asked."""
        if not customer_id or not self._key():
            return False
        owns = self._client is None
        http = self._http()
        try:
            response = self._get_retrying(
                http,
                f"{_STRIPE}/v1/subscriptions",
                {"customer": customer_id, "status": "all", "limit": 10},
            )
            if response is None:
                _warn("stripe_subscription_check_failed", error="unreachable")
                return None
            if response.status_code in (400, 404):
                return False  # no such customer
            if response.status_code != 200:
                _warn("stripe_subscription_check_failed", http_status=response.status_code)
                return None
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                _warn("stripe_subscription_check_failed", http_status=200, error="no_data_list")
                return None
            return any(
                isinstance(item, dict) and str(item.get("status") or "") in _ENTITLED
                for item in data
            )
        except (httpx.HTTPError, ValueError) as exc:
            _warn("stripe_subscription_check_failed", error=type(exc).__name__)
            return None
        finally:
            if owns:
                http.close()

    def is_subscription_active(self, customer_id: str) -> bool:
        """Fails closed: anything but a clear active or trialing answer is False."""
        return self.subscription_state(customer_id) is True

    def create_portal_url(self, customer_id: str, *, return_url: str) -> str | None:
        """Stripe-hosted customer portal session; None if the portal is not set up."""
        if not customer_id.startswith("cus_") or not self._key():
            return None
        owns = self._client is None
        http = self._http()
        try:
            response = http.post(
                f"{_STRIPE}/v1/billing_portal/sessions",
                content=urlencode({"customer": customer_id, "return_url": return_url}),
                headers={"content-type": "application/x-www-form-urlencoded"},
                auth=self._auth(),
            )
            if response.status_code != 200:
                try:
                    code = (response.json().get("error") or {}).get("code")
                except (ValueError, AttributeError):
                    code = None
                _LOG.warning(
                    "stripe_portal_unavailable status=%s code=%s", response.status_code, code
                )
                return None
            url = response.json().get("url")
            return url if isinstance(url, str) and url.startswith("https://") else None
        except (httpx.HTTPError, ValueError):
            return None
        finally:
            if owns:
                http.close()

    def create_checkout_url(self, *, success_url: str, cancel_url: str, reference: str) -> str:
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
                    # Ties the session to the browser that started it.
                    "client_reference_id": reference,
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
        except httpx.HTTPStatusError as exc:
            _warn("stripe_checkout_failed", http_status=exc.response.status_code)
            raise
        except Exception as exc:
            _warn("stripe_checkout_failed", error=type(exc).__name__)
            raise
        finally:
            if owns:
                http.close()

    def customer_id_from_checkout_session(self, session_id: str, *, reference: str) -> str | None:
        """The customer who paid in this Checkout Session.

        Access always goes to the paying customer. An email typed into Checkout
        is not verified, so it never moves access to another customer. The
        session must carry this browser's reference, so a success link sent to
        someone else grants nothing.
        """
        if not session_id or not reference or not self._key():
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
            if status != "complete" or payment not in {"paid", "no_payment_required"}:
                return None
            carried = payload.get("client_reference_id")
            if not isinstance(carried, str) or not hmac.compare_digest(carried, reference):
                return None
            customer = payload.get("customer")
            if not isinstance(customer, str) or not customer.startswith("cus_"):
                return None
            return customer
        except httpx.HTTPError:
            return None
        finally:
            if owns:
                http.close()

    def active_customer_id_for_email(self, email: str) -> str | None:
        """Active subscriber for this receipt email.

        Stripe's list filter matches the stored email exactly, including case,
        so the address is also found through Search, which ignores case. The
        address goes in the query string; this method never logs it, and
        `configure_logging` keeps httpx from logging the request URL.
        """
        cleaned = email.strip()
        if "@" not in cleaned or len(cleaned) > 320 or not cleaned.isascii() or not self._key():
            return None
        owns = self._client is None
        http = self._http()
        try:
            lowered = cleaned.lower()
            seen: set[str] = set()

            def first_active(items: list) -> str | None:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    customer_id = str(item.get("id") or "")
                    stored = str(item.get("email") or "").strip().lower()
                    if not customer_id.startswith("cus_") or customer_id in seen:
                        continue
                    if stored and stored != lowered:
                        continue
                    seen.add(customer_id)
                    if self.is_subscription_active(customer_id):
                        return customer_id
                return None

            for candidate in dict.fromkeys([cleaned, lowered]):
                response = http.get(
                    f"{_STRIPE}/v1/customers",
                    params={"email": candidate, "limit": 10},
                    auth=self._auth(),
                )
                if response.status_code == 200:
                    found = first_active(response.json().get("data") or [])
                    if found:
                        return found
            if "'" not in lowered and "\\" not in lowered:
                response = http.get(
                    f"{_STRIPE}/v1/customers/search",
                    params={"query": f"email:'{lowered}'", "limit": 10},
                    auth=self._auth(),
                )
                if response.status_code == 200:
                    return first_active(response.json().get("data") or [])
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
