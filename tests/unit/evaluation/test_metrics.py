from src.evaluation.metrics import (
    compute_escalation_metrics,
    compute_recall_at_k,
    verify_citation_exact_match,
)


def test_recall_at_k_perfect_match():
    retrieved = ["chunk-1", "chunk-2", "chunk-3"]
    expected = ["chunk-1", "chunk-2"]
    assert compute_recall_at_k(retrieved, expected, k=2) == 1.0


def test_recall_at_k_partial_match():
    retrieved = ["chunk-1", "chunk-99", "chunk-3"]
    expected = ["chunk-1", "chunk-2"]
    assert compute_recall_at_k(retrieved, expected, k=2) == 0.5


def test_recall_at_k_cutoff_boundary():
    retrieved = ["chunk-99", "chunk-1"]
    expected = ["chunk-1"]

    assert compute_recall_at_k(retrieved, expected, k=1) == 0.0
    assert compute_recall_at_k(retrieved, expected, k=2) == 1.0


def test_recall_at_k_empty_expected():
    retrieved = ["chunk-1"]
    expected = []
    assert compute_recall_at_k(retrieved, expected, k=5) == 1.0


def test_verify_citation_exact_match():
    chunk_texts = [
        "Firms must respond\n  to eligible   complaints within 8 weeks.",
        "Under DISP rules, a final response letter is mandatory.",
    ]
    assert verify_citation_exact_match("respond to eligible complaints", chunk_texts)
    assert verify_citation_exact_match("respond\nto eligible complaints", chunk_texts)
    assert not verify_citation_exact_match("respond within 12 weeks", chunk_texts)
    assert not verify_citation_exact_match("", chunk_texts)
    assert not verify_citation_exact_match("   \n\t  ", chunk_texts)


def test_compute_escalation_metrics():
    expected = [True, True, True, False]
    predicted = [True, True, False, True]

    precision, recall = compute_escalation_metrics(expected, predicted)

    assert round(precision, 2) == 0.67
    assert round(recall, 2) == 0.67
