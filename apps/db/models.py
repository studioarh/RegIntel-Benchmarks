from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4


@dataclass
class DocumentChunk:
    """Lightweight representation of the SQLAlchemy DocumentChunk ORM model for showcase & diffing tests."""

    document_id: UUID
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    id: UUID = field(default_factory=uuid4)
    section_heading: str | None = None
    page_number: int | None = None
    primary_rule_code: str | None = None
    table_metadata: dict[str, Any] | None = None
