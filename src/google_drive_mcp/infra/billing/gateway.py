"""Billing port: is this Stripe customer entitled to MCP Connect?"""

from __future__ import annotations

from typing import Protocol


class BillingGateway(Protocol):
    def is_subscription_active(self, customer_id: str) -> bool: ...

    def create_checkout_url(self, *, success_url: str, cancel_url: str) -> str: ...

    def customer_id_from_checkout_session(self, session_id: str) -> tuple[str, bool] | None:
        """Paid customer id, and whether a duplicate checkout was released."""
        ...

    def active_customer_id_for_email(self, email: str) -> str | None: ...

    def get_passkey(self, customer_id: str) -> list[dict]: ...

    def save_passkey(self, customer_id: str, keys: list[dict]) -> None: ...


class InactiveBilling:
    """Paywall on but processor missing: nobody is entitled."""

    def is_subscription_active(self, customer_id: str) -> bool:
        return False

    def create_checkout_url(self, *, success_url: str, cancel_url: str) -> str:
        raise RuntimeError("payments_not_configured")

    def customer_id_from_checkout_session(self, session_id: str) -> tuple[str, bool] | None:
        return None

    def active_customer_id_for_email(self, email: str) -> str | None:
        return None

    def get_passkey(self, customer_id: str) -> list[dict]:
        return []

    def save_passkey(self, customer_id: str, keys: list[dict]) -> None:
        raise RuntimeError("payments_not_configured")
