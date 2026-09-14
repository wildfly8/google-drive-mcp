"""Client ID Metadata Documents (CIMD) for ChatGPT and Claude connectors.

Hosts prefer CIMD over DCR: ``client_id`` is an HTTPS metadata URL. Fetching
that document on demand means Cloud Run scale-to-zero does not drop the host's
registration (in-memory DCR still applies to Inspector and other DCR clients).

Only ``chatgpt.com``, ``claude.ai``, and ``claude.com`` hosts are fetched, to
avoid using ``client_id`` as SSRF. CIMD clients are treated as public
(``token_endpoint_auth_method=none``); this server does not verify
``private_key_jwt``.

Claude's published CIMD has no ``scope`` field. The MCP SDK still rejects
``scope=drive.read`` on ``/authorize`` unless the client record lists that
scope — Claude always sends it from this server's ``scopes_supported``.
CIMD clients are therefore granted ``drive.read``.

If the metadata origin is unreachable from Cloud Run, a same-shape public
client is synthesized so authorize still accepts that host's redirect URIs.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from mcp.shared.auth import InvalidScopeError, OAuthClientInformationFull
from pydantic import AnyUrl

from google_drive_mcp.infra.mcp_auth.tokens import MCP_OAUTH_SCOPE

ALLOWED_CIMD_HOSTS = frozenset(
    {
        "chatgpt.com",
        "www.chatgpt.com",
        "claude.ai",
        "www.claude.ai",
        "claude.com",
        "www.claude.com",
    }
)
_CHATGPT_HOSTS = frozenset({"chatgpt.com", "www.chatgpt.com"})
_CLAUDE_HOSTS = frozenset({"claude.ai", "www.claude.ai", "claude.com", "www.claude.com"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
CLAUDE_WEB_REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def _https_cimd_client_id(client_id: str) -> bool:
    parsed = urlparse(client_id)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and host in ALLOWED_CIMD_HOSTS and bool(parsed.path)


def cimd_redirect_allowed(uri: str) -> bool:
    parsed = urlparse(uri.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if parsed.scheme == "https" and host in _CHATGPT_HOSTS:
        return path.startswith("/connector/oauth/") or path == "/connector_platform_oauth_redirect"
    if parsed.scheme == "https" and host in _CLAUDE_HOSTS:
        return path == "/api/mcp/auth_callback"
    if parsed.scheme == "http" and host in _LOOPBACK_HOSTS:
        return path == "/callback" or path.startswith("/callback/")
    return False


class CimdPublicClient(OAuthClientInformationFull):
    """Public CIMD client; redirect URIs follow ChatGPT/Claude/Codex allowlists."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None and cimd_redirect_allowed(str(redirect_uri)):
            return redirect_uri
        return super().validate_redirect_uri(redirect_uri)

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        if requested_scope is None:
            return None
        requested = [part for part in requested_scope.split(" ") if part]
        if not requested:
            return None
        if MCP_OAUTH_SCOPE in requested:
            return [MCP_OAUTH_SCOPE]
        raise InvalidScopeError(f"Client was not registered with scope {requested[0]}")


ChatGptCimdClient = CimdPublicClient


def _callback_id_from_client_id(client_id: str) -> str | None:
    parts = [p for p in urlparse(client_id).path.split("/") if p]
    if len(parts) < 2 or parts[-1] != "client.json":
        return None
    return parts[-2]


def _cimd_client_record(client_id: str, *, redirects: list[str], name: str) -> CimdPublicClient:
    return CimdPublicClient.model_validate(
        {
            "client_id": client_id,
            "client_name": name,
            "redirect_uris": redirects,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "web",
            "scope": MCP_OAUTH_SCOPE,
        }
    )


def _cimd_fallback(client_id: str) -> CimdPublicClient | None:
    if not _https_cimd_client_id(client_id):
        return None
    host = (urlparse(client_id).hostname or "").lower()
    if host in _CLAUDE_HOSTS:
        redirects = [
            CLAUDE_WEB_REDIRECT,
            "https://claude.com/api/mcp/auth_callback",
            "http://127.0.0.1/callback",
            "http://localhost/callback",
        ]
        name = "Claude"
    else:
        callback_id = _callback_id_from_client_id(client_id) or "chatgpt"
        redirects = [
            f"https://chatgpt.com/connector/oauth/{callback_id}",
            "https://chatgpt.com/connector_platform_oauth_redirect",
            f"http://127.0.0.1/callback/{callback_id}",
            "http://127.0.0.1/callback",
        ]
        name = "ChatGPT"
    return _cimd_client_record(client_id, redirects=redirects, name=name)


def as_cimd_public_client(client: OAuthClientInformationFull) -> CimdPublicClient:
    payload = client.model_dump()
    payload["token_endpoint_auth_method"] = "none"
    payload["scope"] = MCP_OAUTH_SCOPE
    payload.pop("client_secret", None)
    return CimdPublicClient.model_validate(payload)


async def fetch_cimd_client(client_id: str) -> CimdPublicClient | None:
    if not _https_cimd_client_id(client_id):
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as http:
            response = await http.get(client_id, headers={"accept": "application/json"})
    except httpx.HTTPError:
        return _cimd_fallback(client_id)
    if response.status_code != 200:
        return _cimd_fallback(client_id)
    try:
        data = response.json()
    except ValueError:
        return _cimd_fallback(client_id)
    if not isinstance(data, dict):
        return _cimd_fallback(client_id)
    payload = dict(data)
    payload["client_id"] = client_id
    payload["token_endpoint_auth_method"] = "none"
    payload["scope"] = MCP_OAUTH_SCOPE
    payload.pop("client_secret", None)
    try:
        return as_cimd_public_client(OAuthClientInformationFull.model_validate(payload))
    except Exception:
        return _cimd_fallback(client_id)
