"""One-time OAuth consent for drive.readonly.

Headless (Cloud Agent): prints a Google URL; open it on your laptop and paste the
code. Local with a browser: run_local_server.

Never commit the token. The bootstrap script stores it in Secret Manager.
"""

from __future__ import annotations

import os
import sys

SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Install google-auth-oauthlib first: pip install google-auth-oauthlib", file=sys.stderr)
        return 1
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", file=sys.stderr)
        return 1
    config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost", "urn:ietf:wg:oauth:2.0:oob"],
        }
    }
    flow = InstalledAppFlow.from_client_config(config, scopes=[SCOPE])
    if os.environ.get("DISPLAY") and os.environ.get("OAUTH_CONSOLE") != "1":
        creds = flow.run_local_server(port=0, prompt="consent")
    else:
        creds = flow.run_console(prompt="consent")
    if not creds.refresh_token:
        print("No refresh token returned. Re-run with consent prompt.", file=sys.stderr)
        return 1
    print(creds.refresh_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
