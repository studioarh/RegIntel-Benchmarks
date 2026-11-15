from __future__ import annotations

import math
import re
from collections.abc import Sequence

from pydantic import BaseModel, Field

MODEL_PRICING_PER_1M: dict[str, dict[str, float]] = {
    "gemini-3.7-flash": {
        "input": 0.75,
        "output": 3.75,
    },
    "gemini-2.5-flash": {
        "input": 0.15,
        "output": 0.60,
    },
}


def calculate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model_key: str = "gemini-3.7-flash",
) -> float:
    pricing = MODEL_PRICING_PER_1M.get(model_key, MODEL_PRICING_PER_1M["gemini-3.7-flash"])
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]

    return round(input_cost + output_cost, 6)


def calculate_percentiles(latencies: Sequence[float]) -> tuple[float, float]:
    if not latencies:
        return 0.0, 0.0

    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)

    p50_idx = int(n / 2)
    p50 = sorted_latencies[min(p50_idx, n - 1)]

    p95_idx = math.ceil(n * 0.95) - 1
    p95 = sorted_latencies[min(max(p95_idx, 0), n - 1)]

    return round(p50, 3), round(p95, 3)


def compute_recall_at_k(
    retrieved_chunk_ids: list[str], expected_chunk_ids: list[str], k: int
) -> float:
    if not expected_chunk_ids:
        return 1.0
    if k <= 0:
        return 0.0

    top_k = set(retrieved_chunk_ids[:k])
    expected = set(expected_chunk_ids)
    hits = len(top_k.intersection(expected))
    return hits / len(expected)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def verify_citation_exact_match(cited_excerpt: str, retrieved_chunk_texts: list[str]) -> bool:
    clean_citation = _normalize_whitespace(cited_excerpt)
    if not clean_citation:
        return False
    return any(
        clean_citation in _normalize_whitespace(chunk_text) for chunk_text in retrieved_chunk_texts
    )


class ClaimVerification(BaseModel):
    claim: str
    is_supported: bool
    reason: str


class JudgeFaithfulnessResult(BaseModel):
    all_claims_supported: bool
    unsupported_claim_count: int
    claims: list[ClaimVerification] = Field(default_factory=list)


def compute_escalation_metrics(
    expected_escalations: list[bool], predicted_escalations: list[bool]
) -> tuple[float, float]:
    true_positives = sum(
        1
        for exp, pred in zip(expected_escalations, predicted_escalations, strict=True)
        if exp and pred
    )

    predicted_positives = sum(1 for pred in predicted_escalations if pred)
    actual_positives = sum(1 for exp in expected_escalations if exp)

    precision = true_positives / predicted_positives if predicted_positives > 0 else 0.0
    recall = true_positives / actual_positives if actual_positives > 0 else 0.0

    return precision, recall
