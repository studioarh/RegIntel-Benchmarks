# 0004. Validated Regulatory Fact Extraction

**Date:** 05 September 2026  
**Status:** Accepted  

## Context
After calculating a deterministic text diff between document versions, we must extract structured regulatory facts (obligations, deadlines, and affected sectors) relevant to UK consumer lending.

Relying on raw LLM outputs introduces two production risks:
1. **Schema Non-conformance:** The LLM may omit required fields, return malformed JSON, or produce zero extractable facts.
2. **Hallucinated Citations:** The model might generate believable claims but cite non-existent chunk IDs or reference text outside the retrieved evidence window.

In a regulated domain, silently dropping unverified claims or presenting ungrounded statements as fact introduces severe compliance risks.

## Decision
We enforce a two-stage validation gate on extracted changes before any fact can enter downstream briefing generation:

1. **Schema-Level Validation (Pydantic):**
   - The LLM output is bound to the `ChangeExtraction` schema using structured outputs.
   - We declare `facts: list[RegulatoryFact] = Field(min_length=1)` and `citation_chunk_ids: list[UUID] = Field(min_length=1)`. 
   - Empty fact lists or unparsed outputs raise a `ValidationError` and immediately halt automatic processing.

2. **Grounding & Evidence Bound Check:**
   - A deterministic post-processor checks every `citation_chunk_id` in each fact against the exact set of chunk IDs provided in the model's context window.
   - Any reference to an unknown or unsupplied chunk ID is recorded as a validation failure.

3. **Routing to Human Review:**
   - Validation failures do not silently prune invalid facts or attempt automated repair.
   - The workflow marks the entire run as `review_required`, records candidate extractions alongside descriptive error codes, and routes the document to the human review queue.

## Consequences

### Positive
- **Traceability:** Every published fact is strictly bounded to retrieved evidence with verifiable source chunk IDs.
- **Auditability:** Rejected extractions preserve both the candidate text and specific error diagnostics for human reviewers.
- **Fail-Safe Operation:** Downstream briefing generators never receive unverified or structurally invalid facts.

### Trade-offs & Risks
- **Higher Human-Review Rate:** Rejecting an entire extraction when a single citation is invalid increases human review workload compared to optimistic filtering.
- **Retrieval Dependency:** If the initial chunk retrieval is too narrow or misses context, the LLM will fail validation due to missing evidence rather than synthesizing a best-effort answer.
- **Latency & Processing Overhead:** Running dual-layer validation and serializing detailed error structures adds processing time before a report can be finalized.