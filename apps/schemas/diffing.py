from uuid import UUID

from pydantic import BaseModel, Field


class ModifiedPassage(BaseModel):
    before: str
    after: str


class DocumentDiff(BaseModel):
    previous_document_id: UUID | None = None
    has_prior_version: bool = True
    change_detected: bool = False
    status_message: str | None = None
    added_passages: list[str] = []
    removed_passages: list[str] = []
    modified_passages: list[ModifiedPassage] = Field(default_factory=list)
    changed_spans: list[tuple[int, int]] = Field(default_factory=list)
    was_truncated: bool = False
