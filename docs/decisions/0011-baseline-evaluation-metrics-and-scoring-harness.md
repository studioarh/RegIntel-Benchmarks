# 0011. Baseline Evaluation Metrics and Scoring Harness

**Date:** 17 October 2026 
**Status:** Accepted  

## Context
With the 100-task benchmark dataset established (ADR 0009) and observability instrumentation configured (ADR 0010), the RegIntel pipeline required an automated harness to run the benchmark against the unoptimized Week 3 pipeline. 

Prior testing relied on ad-hoc API queries, which could not quantify retrieval accuracy, detect fabricated citations, or evaluate whether ungrounded requests reliably trigger human escalation. Establishing a reproducible baseline before introducing hybrid search, reranking, or query decomposition requires an end-to-end evaluation runner and deterministic scoring metrics.

## Decision Drivers
- **Contract Fidelity:** The evaluation runner must test the actual HTTP API contract (`/answer`) rather than mocking internal functions.
- **Deterministic Verification:** Citation precision and retrieval recall must be calculated using exact-match string and set logic rather than nondeterministic LLM judgments.
- **Structured Judge Integration:** Hallucination and factual consistency checks must use an LLM-as-a-judge with typed Pydantic outputs and consistent temperature settings.
- **Resilience During Benchmark Execution:** High-volume evaluation runs must tolerate intermittent rate limits and persist incremental results without failing mid-run.

## Considered Alternatives
1. **Third-Party Evaluation Frameworks (e.g., Ragas, DeepEval):** Offer pre-built evaluation loops, but introduce heavy third-party abstractions that obscure low-level SQL/pgvector queries, custom human review routing, and verbatim citation matching.
2. **Direct Service Function Invocation:** Avoids HTTP overhead by importing Python functions directly, but skips FastAPI request parsing, header validation, dependency injection, and error handler serialization.
3. **In-Process FastAPI `TestClient` Execution:** Executes full route validation, dependency injection, and serialization in-process, testing the end-to-end API without requiring an external web server process.

## Decision
Implemented an in-process evaluation harness using FastAPI `TestClient`, deterministic metric algorithms, and an LLM-as-a-judge scoring layer.

### 1. Architectural Changes to Pipeline Contracts
To support structured evaluation and deterministic parsing, several runtime components were standardized:
- **Typed Route Contract:** Changed the return type of `call_llm` and `generate_answer` from raw `str` to a structured `AnswerResponse` Pydantic model.
- **Strict Citation Model:** Defined the `Citation` schema with verbatim excerpt requirements:
  ```python
  class Citation(BaseModel):
      chunk_id: UUID = Field(description="UUID of the referenced context chunk")
      document_title: str = Field(description="Exact title of the document")
      source_url: AnyHttpUrl = Field(description="Canonical URL of the source")
      published_at: date | None = Field(
          default=None, description="ISO publication date YYYY-MM-DD or null"
      )
      excerpt: str = Field(
          min_length=1,
          description="VERBATIM exact substring copied from the chunk text",
      )
  ```
- **Input Query Normalization:** Added whitespace and punctuation stripping in `answer.py` (`payload.question.strip().rstrip("?! \t\n")`) to ensure consistent retrieval behavior across identical queries.

### 2. Metric Specifications (`src/evaluation/metrics.py`)
- **Retrieval Recall@5:** Measures the proportion of gold-standard chunk IDs present in the top-5 retrieved chunks:
  $$\text{Recall@}5 = \frac{|\text{retrieved chunks}[:5] \cap \text{expected chunks}|}{|\text{expected chunks}|}$$
  Excluded negative samples (where expected chunks are empty) from penalty calculations.
- **Verbatim Citation Exact Match:** Confirms that each cited `excerpt` string is a literal substring of the retrieved chunk texts via `verify_citation_exact_match`.
- **LLM-as-a-Judge Faithfulness (`evaluate_unsupported_claims`):** Analyzes the generated answer against the retrieved chunks using `call_structured_completion` returning `JudgeFaithfulnessResult`. Handled empty or `None` answers as vacuously supported (`all_claims_supported=True`, `unsupported_claim_count=0`) to prevent penalizing deliberate refusals.
- **Escalation Precision and Recall:** Measures the classification accuracy of routing unevidenced or out-of-scope requests to `insufficient_evidence`.
- **Latency Percentiles:** Computes exact P50 and P95 execution response times across the benchmark suite.

### 3. Automated Runner Harness (`src/evaluation/runner.py`)
- **Transport Layer:** Employs FastAPI `TestClient(app)` to exercise the `/answer` endpoint directly.
- **Fault-Tolerant Execution:** Implements linear retry backoff (`MAX_RETRIES = 2`, `BACKOFF_SECONDS = 15.0`) for rate-limit handling.
- **Progress Persistence:** Writes intermediate task results to `data/evaluation/runs/baseline_run_temp_final.json` after each query, preventing progress loss if interrupted.
- **Artifact Generation:** Stores final aggregated performance metrics and per-task traces to `data/evaluation/runs/baseline_run_final.json`.

## Consequences

### Positive
- **Reproducible Baseline:** Establishes fixed performance baselines for retrieval recall, citation validity, hallucination rate, and tail latency across 100 test cases.
- **Verification of Safe Refusal:** Verifies that out-of-scope and weak-evidence queries escalate to human review without failing or generating false claims.
- **Isolated Judge Execution:** Keeps judge prompts and schemas decoupled from the core application layer while reusing shared LLM client infrastructure.

### Negative / Trade-offs
- Running 100 full API queries with an LLM judge takes several minutes and consumes external model tokens.
- Verbatim citation matching strictly requires character-exact substrings; small whitespace or formatting variations in the model output are treated as invalid citations.

## Validation
- Verified unit test suite in `tests/unit/evaluation/test_metrics.py` covering boundary cases: perfect match, partial match, cutoff boundaries, and empty inputs.
- Executed `runner.py` across `data/evaluation/benchmark_100-2.jsonl`, generating verified baseline summary metrics in `data/evaluation/runs/baseline_run_final.json`.