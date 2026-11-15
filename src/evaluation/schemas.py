from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluationSample(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    input_query: str = Field(min_length=5)
    doc_type: str = Field(min_length=2)
    expected_chunk_ids: list[str] = Field(default_factory=list)
    ground_truth_facts: list[str] = Field(default_factory=list)
    risk_tier: Literal["low", "medium", "high"]
    should_escalate: bool
    expected_refusal_reason: str | None = None

    @model_validator(mode="after")
    def validate_escalation_consistency(self) -> Self:
        if self.should_escalate and not self.expected_refusal_reason:
            raise ValueError(
                "When should_escalate is True, expected_refusal_reason must be provided."
            )

        if not self.should_escalate and not self.expected_chunk_ids:
            raise ValueError(
                "When should_escalate is False, at least one expected_chunk_id is required."
            )
        return self
