"""Billing port: is this Stripe customer entitled to MCP Connect?"""

from __future__ import annotations

from typing import Protocol


class BillingGateway(Protocol):
    def is_subscription_active(self, customer_id: str) -> bool: ...

    def create_checkout_url(self, *, success_url: str, cancel_url: str) -> str: ...

    def customer_id_from_checkout_session(self, session_id: str) -> str | None:
        """The customer who paid in this Checkout Session. Never another customer."""
        ...

    def active_customer_id_for_email(self, email: str) -> str | None:
        """Active subscriber for an email. Only call after the inbox owner proved it."""
        ...

    def create_portal_url(self, customer_id: str, *, return_url: str) -> str | None:
        """Stripe customer portal (manage or cancel) for this customer, or None."""
        ...


class InactiveBilling:
    """Paywall on but processor missing: nobody is entitled."""

    def is_subscription_active(self, customer_id: str) -> bool:
        return False

    def create_checkout_url(self, *, success_url: str, cancel_url: str) -> str:
        raise RuntimeError("payments_not_configured")

    def customer_id_from_checkout_session(self, session_id: str) -> str | None:
        return None

    def active_customer_id_for_email(self, email: str) -> str | None:
        return None

    def create_portal_url(self, customer_id: str, *, return_url: str) -> str | None:
        return None
