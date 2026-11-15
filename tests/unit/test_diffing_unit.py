from __future__ import annotations

from uuid import uuid4

from apps.api.app.services.diffing import calculate_diff, get_relevant_chunks_for_diff
from apps.db.models import DocumentChunk


def test_identical_versions_produce_empty_diff() -> None:
    text = ["SYSC 15A.1.1R:", "Operational resilience requirements remain unchanged."]
    diff = calculate_diff(None, previous_document_text=text, new_document_text=text)
    assert len(diff.added_passages) == 0
    assert len(diff.removed_passages) == 0
    assert len(diff.modified_passages) == 0


def test_large_multi_section_document_exceeding_100k_chars_is_not_truncated() -> None:
    sections_v1 = [
        f"SYSC {i}.1.1R: Standard operational governance conduct rule number {i}. " + ("A" * 2500)
        for i in range(1, 55)
    ]
    sections_v2 = list(sections_v1)
    sections_v2[40] = (
        "SYSC 41.1.1R: Amended rule requiring explicit board-level incident attestation. "
        + ("B" * 2500)
    )

    old_doc = "\n\n".join(sections_v1)
    new_doc = "\n\n".join(sections_v2)
    assert len(new_doc) > 130_000

    diff = calculate_diff(uuid4(), previous_document_text=old_doc, new_document_text=new_doc)
    assert diff.was_truncated is False
    assert diff.change_detected is True
    assert len(diff.modified_passages) == 1
    assert "SYSC 41.1.1R: Amended rule" in diff.modified_passages[0].after


def test_interval_overlap_chunk_matching_identifies_modified_span() -> None:
    doc_id = uuid4()
    old_text = "PRIN 2A.1.1R: Intro.\n\nDISP 1.6.2R: Old 8-week rule."
    new_text = "PRIN 2A.1.1R: Intro.\n\nDISP 1.6.2R: Amended 4-week resolution rule."

    diff = calculate_diff(doc_id, previous_document_text=old_text, new_document_text=new_text)
    chunks = [
        DocumentChunk(
            document_id=doc_id,
            chunk_index=0,
            text="PRIN 2A.1.1R: Intro.",
            char_start=0,
            char_end=20,
        ),
        DocumentChunk(
            document_id=doc_id,
            chunk_index=1,
            text="DISP 1.6.2R: Amended 4-week resolution rule.",
            char_start=22,
            char_end=len(new_text),
        ),
    ]

    matched = get_relevant_chunks_for_diff(diff, chunks)
    assert len(matched) == 1
    assert matched[0].chunk_index == 1
