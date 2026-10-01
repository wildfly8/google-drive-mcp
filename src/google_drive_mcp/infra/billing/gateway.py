"""Billing port: is this Stripe customer entitled to MCP Connect?"""

from __future__ import annotations

from typing import Protocol


class BillingUnavailable(RuntimeError):
    """The processor could not be asked. Callers fail closed but may retry later."""


class BillingGateway(Protocol):
    def subscription_state(self, customer_id: str) -> bool | None:
        """True or False when the processor answered; None when it could not be asked."""
        ...

    def is_subscription_active(self, customer_id: str) -> bool:
        """Fail-closed form of subscription_state: only a clear yes is True."""
        ...

    def create_checkout_url(self, *, success_url: str, cancel_url: str, reference: str) -> str:
        """Hosted Checkout that carries `reference` back (client_reference_id)."""
        ...

    def customer_id_from_checkout_session(self, session_id: str, *, reference: str) -> str | None:
        """The customer who paid in this Checkout Session, only if it carries `reference`.

        Never another customer, and never for a browser that did not start it.
        """
        ...

    def active_customer_id_for_email(self, email: str) -> str | None:
        """Active subscriber for an email. Only call after the inbox owner proved it."""
        ...

    def create_portal_url(self, customer_id: str, *, return_url: str) -> str | None:
        """Stripe customer portal (manage or cancel) for this customer, or None."""
        ...


class InactiveBilling:
    """Paywall on but processor missing: nobody is entitled."""

    def subscription_state(self, customer_id: str) -> bool | None:
        return False

    def is_subscription_active(self, customer_id: str) -> bool:
        return False

    def create_checkout_url(self, *, success_url: str, cancel_url: str, reference: str) -> str:
        raise RuntimeError("payments_not_configured")

    def customer_id_from_checkout_session(self, session_id: str, *, reference: str) -> str | None:
        return None

    def active_customer_id_for_email(self, email: str) -> str | None:
        return None

    def create_portal_url(self, customer_id: str, *, return_url: str) -> str | None:
        return None
