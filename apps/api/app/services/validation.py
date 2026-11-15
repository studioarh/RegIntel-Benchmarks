import logging
import re
from typing import Any
from uuid import UUID

from config.config import settings

from apps.schemas.answers import AnswerResponse, AnswerStatus

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def validate_retrieval_quality(candidates: list[dict[str, Any]]) -> tuple[bool, str | None]:

    if not candidates:
        return False, "no retrieval candidates found"

    threshold = settings.similarity_threshold

    strong = [
        c
        for c in candidates
        if float(c.get("similarity", 0.0)) >= threshold or float(c.get("rrf_score", 0.0)) >= 0.015
    ]

    if len(strong) < settings.min_credible_chunks:
        return (
            False,
            "Too few high-similarity chunks to support a reliable answer.",
        )

    return True, None


def validate_answer_citations(
    answer: AnswerResponse, retrieved_chunks: list[dict[str, Any]]
) -> tuple[bool, str | None]:
    if answer.status == AnswerStatus.ANSWERED:
        if not answer.citations:
            return False, "Answered response must contain at least one citation."
    else:
        return True, None

    chunk_text_by_id = {UUID(str(c["chunk_id"])): str(c["text"]) for c in retrieved_chunks}

    for citation in answer.citations:
        chunk_text = chunk_text_by_id.get(citation.chunk_id)
        if chunk_text is None:
            return (
                False,
                f"Citation references chunk_id {citation.chunk_id} which was not part of the retrieval set.",
            )

        norm_excerpt = _normalize_whitespace(citation.excerpt)
        norm_chunk = _normalize_whitespace(chunk_text)

        if not norm_excerpt or norm_excerpt not in norm_chunk:
            return (
                False,
                f"Citation excerpt for chunk {citation.chunk_id} is not a verbatim substring of the stored chunk text.",
            )

    return True, None
