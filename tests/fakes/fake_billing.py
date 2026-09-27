"""In-memory Stripe stand-in for contract tests."""

from __future__ import annotations


class FakeBilling:
    def __init__(self) -> None:
        self.active: set[str] = set()
        self.sessions: dict[str, str] = {}
        self.checkouts = 0

    def is_subscription_active(self, customer_id: str) -> bool:
        return customer_id in self.active

    def create_checkout_url(self, *, success_url: str, cancel_url: str) -> str:
        self.checkouts += 1
        sid = f"cs_test_{self.checkouts}"
        cus = f"cus_test_{self.checkouts}"
        self.sessions[sid] = cus
        self.active.add(cus)
        return success_url.replace("{CHECKOUT_SESSION_ID}", sid)

    def customer_id_from_checkout_session(self, session_id: str) -> str | None:
        return self.sessions.get(session_id)
