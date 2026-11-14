"""Threads that start side by side fetch the access token once, not once each.

Credentials are minted for every call without a token, and the first request fetches it.
The access check and the download workers now start together, so the client must make the
rest wait for the first fetch, and share its failure.
"""

from __future__ import annotations

import threading
import time

import pytest
from google.auth import credentials as google_credentials
from google.auth.exceptions import RefreshError

from google_drive_mcp.infra.google_drive.client import GoogleDriveClient


class SlowCredentials(google_credentials.Credentials):
    """google-auth credentials whose refresh takes a moment and is counted."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.refreshes = 0
        self.fail = fail
        self._count_lock = threading.Lock()

    def refresh(self, request) -> None:
        with self._count_lock:
            self.refreshes += 1
        time.sleep(0.05)
        if self.fail:
            raise RefreshError("invalid_grant")
        self.token = "t"


def _client(creds: SlowCredentials) -> GoogleDriveClient:
    client = GoogleDriveClient(creds)  # type: ignore[arg-type]
    return client


def _ask_from_many_threads(client: GoogleDriveClient, count: int = 10):
    outcomes: list[object] = []
    barrier = threading.Barrier(count)

    def ask() -> None:
        barrier.wait()
        try:
            client._http()
            outcomes.append("ok")
        except RefreshError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=ask) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def test_ten_threads_starting_together_fetch_the_token_once():
    creds = SlowCredentials()
    outcomes = _ask_from_many_threads(_client(creds))
    assert outcomes == ["ok"] * 10
    assert creds.refreshes == 1


def test_a_failed_fetch_is_shared_not_repeated():
    creds = SlowCredentials(fail=True)
    outcomes = _ask_from_many_threads(_client(creds))
    assert len(outcomes) == 10 and all(isinstance(o, RefreshError) for o in outcomes)
    assert creds.refreshes == 1


def test_a_valid_token_is_not_fetched_again():
    creds = SlowCredentials()
    creds.token = "already"
    _ask_from_many_threads(_client(creds), count=4)
    assert creds.refreshes == 0


def test_each_call_has_its_own_client_and_so_its_own_token_fetch():
    first, second = SlowCredentials(), SlowCredentials()
    _client(first)._http()
    _client(second)._http()
    assert (first.refreshes, second.refreshes) == (1, 1)


def test_a_failure_surfaces_through_the_adapters_own_error_mapping():
    from google_drive_mcp.domain.google_errors import GoogleApiError

    client = _client(SlowCredentials(fail=True))
    with pytest.raises(GoogleApiError):
        client.get_metadata("any-id")
