"""Security headers on every HTML page and every response that sets a cookie."""

from __future__ import annotations

from typing import Any

# No default-src, script-src or form-action: /setup has an inline script and
# Checkout and the portal are form redirects to Stripe.
_HTML_HEADERS = (
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"frame-ancestors 'none'; base-uri 'none'; object-src 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
)


def _shared_cacheable(cache_control: bytes) -> bool:
    directives = {part.split(b"=")[0].strip() for part in cache_control.lower().split(b",")}
    return not directives & {b"no-store", b"private"}


class SecurityHeadersMiddleware:
    """Pure ASGI. Adds only headers the response does not set itself."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                found = {key.lower(): value for key, value in headers}
                if b"set-cookie" in found and _shared_cacheable(found.get(b"cache-control", b"")):
                    # A cookie (the renewed entitlement too) must never sit in a shared
                    # cache, even on a reply that is otherwise public (OAuth metadata).
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                    found[b"cache-control"] = b"no-store"
                # Pages that set their own (consent, email link) keep them.
                if found.get(b"content-type", b"").lower().startswith(b"text/html"):
                    for name, value in _HTML_HEADERS:
                        if name not in found:
                            headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
