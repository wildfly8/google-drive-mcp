"""drive_find contract tests."""

from __future__ import annotations

from google_drive_mcp.mcp.tools import handle_tool


def test_find_includes_nested_doc_as_candidate_not_evidence(runtime, authz):
    result = handle_tool(
        runtime, "drive_find", {"folder_id": "folder-a"}, authz
    )
    assert result["status"] in {"COMPLETE", "PARTIAL"}
    ids = {c["file"]["id"] for c in result["candidates"]}
    assert "nested-doc" in ids
    for cand in result["candidates"]:
        assert cand["discovery_method"] == "find"
        assert "reason" in cand
        assert "content" not in cand
        assert "content" not in cand["file"]
        assert cand["file"]["source_url"] == f"drive:{cand['file']['id']}"
        assert not cand["file"]["source_url"].lower().startswith("http")
        assert "verified" not in cand
        assert "evidence" not in cand
    assert "trashed-doc" not in ids


def test_find_folder_includes_trashed_when_requested(runtime, authz):
    result = handle_tool(
        runtime,
        "drive_find",
        {"folder_id": "folder-a", "trashed": True},
        authz,
    )
    assert result["status"] in {"COMPLETE", "PARTIAL"}
    ids = {c["file"]["id"] for c in result["candidates"]}
    assert "nested-doc" in ids
    assert "trashed-doc" in ids


def test_find_name_query_skips_non_matching_siblings_and_does_not_fetch_parents():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.retrieval.find import drive_find

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for i in range(45):
        drive.add(
            FakeFile(
                id=f"noise-{i}",
                name=f"other-{i}.txt",
                mime_type=DOC_MIME,
                parents=["top"],
                content="unrelated",
            )
        )
    drive.add(FakeFile(id="nested", name="Logs", mime_type=FOLDER_MIME, parents=["top"]))
    drive.add(
        FakeFile(
            id="year-mdx",
            name="activity-2025.mdx",
            mime_type=DOC_MIME,
            parents=["nested"],
            content="body",
        )
    )
    result = drive_find(drive, folder_id="top", name_pattern="activity-2025")
    ids = [c["file"]["id"] for c in result["candidates"]]
    assert result["status"] == "COMPLETE"
    assert ids == ["year-mdx"]
    assert drive.parent_lookup_count == 0
    assert drive.metadata_get_count == 0


def test_find_max_results_counts_matches_only():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.retrieval.find import drive_find

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(
        FakeFile(id="a-notes", name="Notes A", mime_type=DOC_MIME, parents=["top"])
    )
    drive.add(
        FakeFile(id="b-notes", name="Notes B", mime_type=DOC_MIME, parents=["top"])
    )
    exact = drive_find(drive, folder_id="top", name_pattern="Notes", max_results=2)
    assert exact["status"] == "COMPLETE"
    assert {c["file"]["id"] for c in exact["candidates"]} == {"a-notes", "b-notes"}
    capped = drive_find(drive, folder_id="top", name_pattern="Notes", max_results=1)
    assert capped["status"] == "PARTIAL"
    assert capped["partial_reason"] == "max_files"
    assert len(capped["candidates"]) == 1


def test_find_folders_do_not_consume_max_results():
    from fakes.fake_drive import DOC_MIME, FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.retrieval.find import drive_find

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(FakeFile(id="f-dir", name="activity-dir", mime_type=FOLDER_MIME, parents=["top"]))
    drive.add(FakeFile(id="a-doc", name="activity-a", mime_type=DOC_MIME, parents=["f-dir"]))
    drive.add(FakeFile(id="b-doc", name="activity-b", mime_type=DOC_MIME, parents=["top"]))
    result = drive_find(drive, folder_id="top", name_pattern="activity", max_results=2)
    assert result["status"] == "COMPLETE"
    assert {c["file"]["id"] for c in result["candidates"]} == {"f-dir", "a-doc", "b-doc"}
    unfiltered = drive_find(drive, folder_id="top", max_results=2)
    assert unfiltered["status"] == "COMPLETE"
    assert {c["file"]["id"] for c in unfiltered["candidates"]} == {"f-dir", "a-doc", "b-doc"}


def test_find_counts_folders_when_asking_for_folders():
    from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.retrieval.find import drive_find

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    drive.add(FakeFile(id="d1", name="one", mime_type=FOLDER_MIME, parents=["top"]))
    drive.add(FakeFile(id="d2", name="two", mime_type=FOLDER_MIME, parents=["top"]))
    capped = drive_find(drive, folder_id="top", mime_type=FOLDER_MIME, max_results=1)
    assert capped["status"] == "PARTIAL"
    assert capped["partial_reason"] == "max_files"
    assert len(capped["candidates"]) == 1


def test_find_matching_folders_have_their_own_cap():
    from fakes.fake_drive import FOLDER_MIME, FakeDrive, FakeFile
    from google_drive_mcp.retrieval.find import drive_find

    drive = FakeDrive()
    drive.add(FakeFile(id="root", name="My Drive", mime_type=FOLDER_MIME, parents=[]))
    drive.add(FakeFile(id="top", name="Top", mime_type=FOLDER_MIME, parents=["root"]))
    for n in range(5):
        drive.add(FakeFile(id=f"d{n}", name=f"notes-{n}", mime_type=FOLDER_MIME, parents=["top"]))
    result = drive_find(drive, folder_id="top", name_pattern="notes", max_results=2)
    assert result["status"] == "PARTIAL"
    assert result["partial_reason"] == "max_files"
    assert len(result["candidates"]) == 2
