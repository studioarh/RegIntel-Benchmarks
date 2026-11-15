# 0009. Evaluation Dataset Schema and Stratification

**Date:** 10 October 2026 
**Status:** Accepted  

## Context
The RegIntel system has transitioned from core pipeline extraction and human review queues (Week 3) to evaluation, benchmarking, and observability (Week 4). Prior verification relied on ad-hoc queries and functional unit tests. Manual spot checks cannot detect silent retrieval regressions, measure citation accuracy, or confirm that out-of-scope queries trigger human escalation.

To quantitatively evaluate retrieval recall, citation precision, and hallucination rates across pipeline iterations, the system requires an immutable, versioned 100-task benchmark and a strictly typed evaluation contract.

## Decision Drivers
- **Reproducibility:** A fixed 100-task benchmark provides identical inputs to compare baseline and optimized retrieval configurations.
- **Contract Enforcement:** Malformed test data, missing chunk identifiers, or invalid risk tiers must fail validation before running the test harness.
- **Controlled Refusal Testing:** The pipeline must handle failure safely; the benchmark must evaluate deliberate failure modes (missing evidence, out-of-scope topics) alongside standard retrieval.
- **Static Type Safety:** Schemas must adhere to Pydantic V2 conventions, compile under strict `mypy` flags, and enforce internal consistency between escalation flags and refusal reasons.

## Considered Alternatives
- **Ad-hoc CSV or JSON files:** Simple to generate, but lacks runtime schema validation, static typing, and logical consistency checks between escalation flags and refusal reasons.
- **Standard Public Benchmarks (SQuAD, HotpotQA):** Widely used, but lack UK financial regulatory domains, FCA handbook structures, database chunk IDs, and compliance escalation behavior.
- **Pydantic V2 Schemas with JSON Lines (JSONL):** Enforces strict serialization, allows row-by-row streaming during evaluation, and validates consistency using model validators.

## Decision
Adopted **Pydantic V2 Schema Validation with JSON Lines (JSONL)** storage for the 100-task benchmark dataset.

### 1. Schema Definition (`src/evaluation/schemas.py`)
Defined the `EvaluationSample` model with strict configuration:
- `id: UUID`: Unique sample identifier using `default_factory=uuid4`.
- `input_query: str`: Natural language compliance question (minimum length: 5).
- `doc_type: str`: Regulatory document category or classifier.
- `expected_chunk_ids: list[str]`: Target ground-truth database chunk IDs for retrieval recall scoring.
- `ground_truth_facts: list[str]`: Reference factual assertions for generation evaluation.
- `risk_tier: Literal["low", "medium", "high"]`: Stratification tag for impact-based metric grouping.
- `should_escalate: bool`: Expected human-in-the-loop escalation outcome.
- `expected_refusal_reason: str | None`: Explicit trigger category (`insufficient_evidence`, `out_of_domain`, or `None`).

Enforced data consistency with a model validator:
- If `should_escalate` is `True`, `expected_refusal_reason` must not be empty.
- If `should_escalate` is `False`, `expected_chunk_ids` must contain at least one ID.

### 2. Dataset Stratification (`data/evaluation/benchmark_100-3.jsonl` & `benchmark_100-2.jsonl`)
Curated exactly 100 tasks partitioned across four functional test profiles:

| Profile | Task Count | Risk Tier | Evaluation Objective |
| :--- | :--- | :--- | :--- |
| **Single-Document Extraction** | 40 | Low | Evaluates semantic retrieval recall and factual extraction on standard FCA handbook rules. |
| **Comparative / Version Diffs** | 30 | Medium | Tests multi-chunk retrieval and synthesis across Consultation Papers and Policy Statements. |
| **Weak Evidence Escalation** | 15 | Medium | Queries where evidence is omitted from the corpus; verifies `insufficient_evidence` escalation. |
| **Out-of-Domain Refusal** | 15 | High | Non-regulatory and unsupported topics; verifies immediate refusal and guardrail routing. |

## Consequences

### Positive
- Benchmark datasets can be parsed and validated programmatically in CI pipelines.
- Immutability (`frozen=True`) prevents data corruption during evaluation runs.
- Deliberate negative and weak-evidence test cases ensure refusal paths and citation precision are tested alongside happy-path extraction.

### Negative / Trade-offs
- Chunk IDs couple the dataset to the underlying database state; re-chunking documents requires updating expected chunk IDs.
- Curating 100 domain-specific regulatory tasks requires upfront verification effort.

## Validation
Dataset integrity is validated using `pytest` in `tests/unit/evaluation/test_dataset_validation.py`:
1. Asserts the benchmark file exists and loads exactly 100 records.
2. Asserts zero Pydantic validation errors during deserialization.
3. Asserts the quota distribution (70 standard queries, 15 weak-evidence queries, 15 out-of-domain queries).
4. Asserts all three risk tiers (`low`, `medium`, `high`) are present.