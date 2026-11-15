from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    similarity_threshold: float = 0.55
    min_credible_chunks: int = 1
    answer_context_count: int = 5


settings = Settings()
