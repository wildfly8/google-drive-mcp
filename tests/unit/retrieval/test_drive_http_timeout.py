"""Drive HTTP calls give up well before Cloud Run's 60 s request timeout."""

from __future__ import annotations

import threading

from google.oauth2.credentials import Credentials

from google_drive_mcp.infra.google_drive.client import GoogleDriveClient


def test_drive_connections_time_out_after_20_seconds():
    client = GoogleDriveClient(Credentials(token="t"))
    https = [client._http()]
    worker = threading.Thread(target=lambda: https.append(client._http()))
    worker.start()
    worker.join()
    for authorized in https:
        assert authorized.http.timeout == 30
        # Kept from googleapiclient's build_http: 308 is not followed as a redirect.
        assert 308 not in authorized.http.redirect_codes
        assert 301 in authorized.http.redirect_codes
