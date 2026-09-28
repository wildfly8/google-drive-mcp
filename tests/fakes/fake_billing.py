"""In-memory Stripe stand-in for contract tests."""

from __future__ import annotations


class FakeBilling:
    def __init__(self) -> None:
        self.active: set[str] = set()
        self.sessions: dict[str, str] = {}
        self.session_emails: dict[str, str] = {}
        self.emails: dict[str, str] = {}
        self.passkeys: dict[str, list[dict]] = {}
        self.released: list[str] = []
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

    def customer_id_from_checkout_session(self, session_id: str) -> tuple[str, bool] | None:
        customer = self.sessions.get(session_id)
        if not customer:
            return None
        email = self.session_emails.get(session_id)
        if email:
            existing = self.active_customer_id_for_email(email)
            if existing and existing != customer:
                self.active.discard(customer)
                self.released.append(customer)
                return existing, True
        return customer, False

    def active_customer_id_for_email(self, email: str) -> str | None:
        customer_id = self.emails.get(email.strip().lower())
        if customer_id and customer_id in self.active:
            return customer_id
        return None

    def get_passkey(self, customer_id: str) -> list[dict]:
        return list(self.passkeys.get(customer_id) or [])

    def save_passkey(self, customer_id: str, keys: list[dict]) -> None:
        self.passkeys[customer_id] = list(keys)
