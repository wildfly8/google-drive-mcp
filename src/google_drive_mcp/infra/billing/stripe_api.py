"""Stripe REST via httpx. Never logs secrets, PANs, or emails."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode

import httpx

from google_drive_mcp.infra.config import Settings

_LOG = logging.getLogger("google_drive_mcp")
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

    def customer_id_from_checkout_session(self, session_id: str) -> tuple[str, bool] | None:
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
            if not isinstance(customer, str) or not customer.startswith("cus_"):
                return None
            email = _session_email(payload) or self._customer_email(http, customer)
            other = self._other_active_customer(http, email, customer) if email else None
            if other and self._release_new_subscription(http, customer):
                return other, True
            return customer, False
        except httpx.HTTPError:
            return None
        finally:
            if owns:
                http.close()

    def _customer_email(self, http: httpx.Client, customer_id: str) -> str | None:
        response = http.get(f"{_STRIPE}/v1/customers/{customer_id}", auth=self._auth())
        if response.status_code != 200:
            return None
        email = response.json().get("email")
        if isinstance(email, str) and "@" in email and len(email) <= 320:
            return email
        return None

    def _other_active_customer(
        self, http: httpx.Client, email: str, exclude: str
    ) -> str | None:
        response = http.get(
            f"{_STRIPE}/v1/customers",
            params={"email": email.strip(), "limit": 10},
            auth=self._auth(),
        )
        if response.status_code != 200:
            return None
        for item in response.json().get("data") or []:
            if not isinstance(item, dict):
                continue
            customer_id = str(item.get("id") or "")
            if not customer_id.startswith("cus_") or customer_id == exclude:
                continue
            if self._subscription_active(http, customer_id):
                return customer_id
        return None

    def _subscription_active(self, http: httpx.Client, customer_id: str) -> bool:
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

    def _release_new_subscription(self, http: httpx.Client, customer_id: str) -> bool:
        try:
            response = http.get(
                f"{_STRIPE}/v1/subscriptions",
                params={"customer": customer_id, "status": "all", "limit": 10},
                auth=self._auth(),
            )
            if response.status_code != 200:
                return False
            released = False
            for item in response.json().get("data") or []:
                if not isinstance(item, dict):
                    continue
                sub_id = str(item.get("id") or "")
                if not sub_id.startswith("sub_"):
                    continue
                if str(item.get("status") or "") not in _ENTITLED | {"incomplete", "past_due"}:
                    continue
                invoice_id = item.get("latest_invoice")
                if isinstance(invoice_id, str) and invoice_id.startswith("in_"):
                    self._refund_invoice(http, invoice_id)
                canceled = http.delete(
                    f"{_STRIPE}/v1/subscriptions/{sub_id}",
                    params={"invoice_now": "false", "prorate": "false"},
                    auth=self._auth(),
                )
                released = canceled.status_code in {200, 404}
            return released
        except httpx.HTTPError:
            _LOG.warning("stripe_duplicate_release_failed")
            return False

    def _refund_invoice(self, http: httpx.Client, invoice_id: str) -> None:
        response = http.get(f"{_STRIPE}/v1/invoices/{invoice_id}", auth=self._auth())
        if response.status_code != 200:
            return
        ref = _payment_ref(response.json())
        if ref is None:
            _LOG.warning("stripe_duplicate_refund_missing")
            return
        field, value = ref
        refunded = http.post(
            f"{_STRIPE}/v1/refunds",
            content=urlencode({field: value}),
            headers={"content-type": "application/x-www-form-urlencoded"},
            auth=self._auth(),
        )
        if refunded.status_code not in {200, 400}:
            _LOG.warning("stripe_duplicate_refund_failed")

    def active_customer_id_for_email(self, email: str) -> str | None:
        """Active subscriber for this receipt email. Does not log the address."""
        cleaned = email.strip()
        if "@" not in cleaned or len(cleaned) > 320 or not self._key():
            return None
        owns = self._client is None
        http = self._http()
        try:
            candidates = [cleaned]
            lowered = cleaned.lower()
            if lowered != cleaned:
                candidates.append(lowered)
            seen: set[str] = set()
            for candidate in candidates:
                response = http.get(
                    f"{_STRIPE}/v1/customers",
                    params={"email": candidate, "limit": 10},
                    auth=self._auth(),
                )
                if response.status_code != 200:
                    continue
                data = response.json().get("data") or []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    customer_id = str(item.get("id") or "")
                    if not customer_id.startswith("cus_") or customer_id in seen:
                        continue
                    seen.add(customer_id)
                    if self.is_subscription_active(customer_id):
                        return customer_id
            return None
        except httpx.HTTPError:
            return None
        finally:
            if owns:
                http.close()

    def get_passkey(self, customer_id: str) -> list[dict]:
        if not customer_id.startswith("cus_") or not self._key():
            return []
        owns = self._client is None
        http = self._http()
        try:
            response = http.get(f"{_STRIPE}/v1/customers/{customer_id}", auth=self._auth())
            if response.status_code != 200:
                return []
            raw = (response.json().get("metadata") or {}).get("pk")
            if not isinstance(raw, str) or not raw:
                return []
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            if not isinstance(data, list):
                return []
            return [item for item in data if isinstance(item, dict) and item.get("id")]
        except (httpx.HTTPError, json.JSONDecodeError):
            return []
        finally:
            if owns:
                http.close()

    def save_passkey(self, customer_id: str, keys: list[dict]) -> None:
        if not customer_id.startswith("cus_") or not self._key():
            raise RuntimeError("passkey_not_stored")
        payload = json.dumps(keys, separators=(",", ":"))
        if len(payload) > 500:
            raise RuntimeError("passkey_not_stored")
        owns = self._client is None
        http = self._http()
        try:
            response = http.post(
                f"{_STRIPE}/v1/customers/{customer_id}",
                content=urlencode({"metadata[pk]": payload}),
                headers={"content-type": "application/x-www-form-urlencoded"},
                auth=self._auth(),
            )
            response.raise_for_status()
        finally:
            if owns:
                http.close()


def _session_email(payload: dict) -> str | None:
    details = payload.get("customer_details")
    if not isinstance(details, dict):
        return None
    email = details.get("email")
    if isinstance(email, str) and "@" in email and len(email) <= 320:
        return email
    return None


def _payment_ref(payload: dict) -> tuple[str, str] | None:
    payment_intent = payload.get("payment_intent")
    if isinstance(payment_intent, dict):
        payment_intent = payment_intent.get("id")
    if isinstance(payment_intent, str) and payment_intent.startswith("pi_"):
        return "payment_intent", payment_intent
    charge = payload.get("charge")
    if isinstance(charge, dict):
        charge = charge.get("id")
    if isinstance(charge, str) and charge.startswith("ch_"):
        return "charge", charge
    payments = payload.get("payments")
    if isinstance(payments, dict):
        payments = payments.get("data")
    if isinstance(payments, list):
        for item in payments:
            if not isinstance(item, dict):
                continue
            payment = item.get("payment") if isinstance(item.get("payment"), dict) else item
            if not isinstance(payment, dict):
                continue
            nested = _payment_ref(payment)
            if nested:
                return nested
    return None


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
