from __future__ import annotations


def embed_question(question: str) -> list[float]:
    """Stub interface for VoyageAI 1024-dim query embedding used by retrieve_chunks."""
    raise NotImplementedError(
        "Live VoyageAI embedding client resides in the private commercial monorepo."
    )
