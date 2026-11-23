"""The second layers behind the allow-list hold on their own (Article I, VII).

Drive's search index can be stale or over-broad: a listing may return a folder that is not
under the one asked about, or a trashed file although trashed files were excluded. The first
layer (the query) is tested elsewhere. Each test here feeds a listing that ignores the
filter and checks that the layer behind it still holds.
"""

from __future__ import annotations

import pytest

from fakes.fake_drive import FakeDrive
from google_drive_mcp.domain.retrieval_scope import folder_tree, is_inside_tree
from google_drive_mcp.infra.config import Settings
from google_drive_mcp.retrieval.find import drive_find
from google_drive_mcp.retrieval.grep import drive_grep


def test_the_folder_tree_leaves_out_a_folder_that_is_not_under_the_frontier():
    def over_broad(_parent_ids: list[str]) -> list[dict]:
        # Ignores the parents it was asked about, as a stale index can.
        return [
            {"id": "kb-child", "parents": ["kb"]},
            {"id": "stray", "parents": ["elsewhere"]},
            {"id": "kb-grandchild", "parents": ["kb-child"]},
            {"id": "stray-child", "parents": ["stray"]},
        ]

    tree = folder_tree("kb", over_broad)
    assert set(tree) == {"kb-child", "kb-grandchild"}
    # A file whose only parent is the stray folder is therefore not inside kb.
    assert is_inside_tree("file-x", ["stray"], "kb", tree) is False
    assert is_inside_tree("file-y", ["kb-grandchild"], "kb", tree) is True


class OverBroadDrive(FakeDrive):
    """Lists trashed files and ignores every filter it is given."""

    def list_children(self, folder_id, budget=None, *, include_trashed=False, list_filter=None):
        return super().list_children(folder_id, budget, include_trashed=True, list_filter=None)


def test_a_trashed_file_the_listing_returned_anyway_is_not_searched():
    drive = OverBroadDrive.sample()
    assert drive.files["trashed-doc"].trashed
    grep = drive_grep(drive, pattern="trashed only", folder_id="folder-a")
    assert grep["matches"] == []
    find = drive_find(drive, name_pattern="Deleted", folder_id="folder-a")
    assert find["candidates"] == []


@pytest.mark.parametrize(
    ("value", "words"),
    [
        ("", "is not set"),
        ("   ", "is not set"),
        ("root", "not an alias"),
        ("AppDataFolder", "not an alias"),
        ("two words", "not an alias"),
    ],
)
def test_startup_says_what_to_set_when_the_allow_list_is_missing_or_an_alias(value, words):
    settings = Settings.for_tests().model_copy(update={"drive_allowed_folder_id": value})
    with pytest.raises(ValueError, match=words):
        settings.require_allowed_folder()
