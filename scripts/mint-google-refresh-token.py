#!/usr/bin/env python3
"""One-time local OAuth consent for drive.readonly. Run on a machine with a browser.

Does not deploy. Prints the refresh token once; store it in Secret Manager as
GOOGLE_REFRESH_TOKEN. Do not commit the value or paste it into chat.

  pip install google-auth-oauthlib
  export GOOGLE_CLIENT_ID=...
  export GOOGLE_CLIENT_SECRET=...
  python scripts/mint-google-refresh-token.py
"""

from __future__ import annotations

import os
import sys

SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def main() -> int:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Install google-auth-oauthlib on the machine that has a browser.", file=sys.stderr)
        return 1
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the environment.", file=sys.stderr)
        return 1
    config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(config, scopes=[SCOPE])
    creds = flow.run_local_server(port=0, prompt="consent")
    if not creds.refresh_token:
        print("No refresh token returned. Re-consent with prompt=consent.", file=sys.stderr)
        return 1
    print("Store this value in Secret Manager secret GOOGLE_REFRESH_TOKEN, then delete the terminal scrollback.")
    print(creds.refresh_token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
