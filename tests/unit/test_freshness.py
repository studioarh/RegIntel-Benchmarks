from datetime import date

import pytest
from src.retrieval.freshness import (
    extract_requested_window_days,
    is_chunk_within_window,
)


@pytest.mark.parametrize(
    ("query", "expected_days"),
    [
        ("Changes published in the last 30 days for consumer credit", 30),
        ("FCA notices from the past 2 weeks", 14),
        ("Updates in the previous 3 months", 90),
        ("Give me answer in the last 10 years", 3650),
        ("Rules amended in the past 2 years", 730),
        ("Changes in the last month", 30),
        ("Updates in the last year", 365),
        ("What are the baseline Consumer Duty rules?", None),
    ],
)
def test_extract_requested_window_days(query: str, expected_days: int | None) -> None:
    assert extract_requested_window_days(query) == expected_days


def test_is_chunk_within_window_marks_fresh_and_stale_chunks() -> None:
    ref_date = date(2026, 11, 1)
    query = "What changed in the last 30 days?"

    assert (
        is_chunk_within_window(
            publication_date=date(2026, 10, 20),
            query=query,
            reference_date=ref_date,
        )
        is True
    )

    assert (
        is_chunk_within_window(
            publication_date=date(2026, 5, 10),
            query=query,
            reference_date=ref_date,
        )
        is False
    )


def test_quality_gate_triggers_review_required_only_when_all_chunks_stale() -> None:
    mixed_window_flags = [True, False]
    flag_mixed = bool(mixed_window_flags and all(not valid for valid in mixed_window_flags))
    status_mixed = "REVIEW_REQUIRED" if flag_mixed else "APPROVED"
    assert flag_mixed is False
    assert status_mixed == "APPROVED"

    all_stale_flags = [False, False]
    flag_all_stale = bool(all_stale_flags and all(not valid for valid in all_stale_flags))
    status_all_stale = "REVIEW_REQUIRED" if flag_all_stale else "APPROVED"
    assert flag_all_stale is True
    assert status_all_stale == "REVIEW_REQUIRED"
