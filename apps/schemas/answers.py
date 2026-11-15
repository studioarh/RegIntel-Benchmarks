from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, Field


class Citation(BaseModel):
    chunk_id: UUID = Field(description="UUID of the referenced context chunk")
    document_title: str = Field(description="Exact title of the document")
    source_url: AnyHttpUrl = Field(description="Canonical URL of the source")
    published_at: date | None = Field(
        default=None, description="ISO publication date YYYY-MM-DD or null"
    )
    excerpt: str = Field(
        min_length=1, description="VERBATIM exact substring copied from the chunk text"
    )
    is_within_window: bool = True
    primary_rule_code: str | None = Field(
        default=None,
        description="Primary FCA Handbook rule code defined by this chunk (e.g. CONC 3.3.1AR)",
    )
    referenced_rules: list[str] = Field(
        default_factory=list,
        description="1-hop statutory cross-referenced FCA rule codes linked from this chunk",
    )
    table_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Structured regulatory table headers and rows when the chunk contains a table",
    )


class AnswerStatus(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AnswerResponse(BaseModel):
    status: AnswerStatus
    answer: str | None = Field(
        default=None,
        description="The synthesis answer, or null if evidence is insufficient",
    )
    retrieved_chunk_ids: list[str] = Field(
        default_factory=list,
        description="The candidate chunk ids retrieved by the sql query from the database for this answer",
    )
    retrieved_chunk_excerpts: list[str] = Field(
        default_factory=list,
        description="The candidate chunk excerpts retrieved by the sql query from the database for this answer",
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="List of supporting citations for the answer",
    )
    confidence: Literal["low", "medium", "high"]
    reason: str | None = Field(
        default=None,
        description="Explanation if evidence was insufficient or confidence is low",
    )
    trace_id: str | UUID = Field(description="The exact trace_id provided in the input, unchanged")
