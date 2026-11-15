# RegIntel Pipeline Evaluation Report: Vector Baseline $\rightarrow$ 2-Way RRF $\rightarrow$ 3-Way Statutory Graph-RRF

## 1. Executive Summary & Benchmark Dataset (`data/evaluation/benchmark_100-3.jsonl`)

This document records the empirical evaluation of the RegIntel regulatory intelligence pipeline across the 100-task UK FCA benchmark suite (`data/evaluation/benchmark_100-3.jsonl`) executed via the in-process FastAPI `TestClient` evaluation runner (`src/evaluation/runner.py`) and deterministic/LLM-as-a-judge metrics (`src/evaluation/metrics.py`).

- **Dataset Path:** `data/evaluation/benchmark_100-3.jsonl` (**100 labelled tasks**: 70 positive answerable FCA regulatory tasks with ground-truth `expected_chunk_ids`, and 30 negative/adversarial or unindexed tasks requiring safe refusal via `should_escalate = true`).
- **Committed Raw Run Artifacts:**
  1. **Vector Baseline (`run_type: "baseline_unoptimized"`):** [`data/evaluation/runs/baseline_run_final.json`](../data/evaluation/runs/baseline_run_final.json)
  2. **2-Way Hybrid RRF (`run_type: "baseline_optimized"`):** [`data/evaluation/runs/optimized_run.json`](../data/evaluation/runs/optimized_run.json)
  3. **3-Way Statutory Graph-RRF (`run_type: "baseline_optimized_v2"`):** [`data/evaluation/runs/optimized_run_2.json`](../data/evaluation/runs/optimized_run_2.json)
- **Runtime Stack Evaluated:**
  - **Embeddings:** VoyageAI (`voyage-3`, 1024 dimensions in `apps/api/app/services/embedding.py`)
  - **Primary / Fallback LLMs:** Google Vertex AI Gemini (`gemini-3.7-flash` primary, `gemini-3.6-flash` fallback via `ResilientLLMClient` in `src/agents/llm_client.py`)
  - **Database & Retriever:** PostgreSQL 16 + `pgvector` + English `tsvector` + `chunk_cross_references` 1-Hop Statutory Graph (`rrf_k = 60`, `graph_weight = 1.15`)

---

## 2. 3-Stage Benchmark Progression (`Vector Baseline` $\rightarrow$ `2-Way RRF` $\rightarrow$ `3-Way Statutory Graph-RRF`)

| Metric (`src/evaluation/metrics.py`) | Vector Baseline (`baseline_run_final.json`) | 2-Way RRF (`optimized_run.json`) | 3-Way Statutory Graph-RRF (`optimized_run_2.json`) | Total Progression (Vector $\rightarrow$ 3-Way Graph-RRF) |
| :--- | :---: | :---: | :---: | :---: |
| **Retrieval Recall@5** (`compute_recall_at_k`, $k=5$) | 47.14% (`0.4714`) | 52.14% (`0.5214`) | **62.86% (`0.6286`)** | **+15.72% abs (+33.35% rel)** |
| **Verbatim Citation Correctness** (`verify_citation_exact_match`) | 11.83% (`0.1183`) | 13.76% (`0.1376`) | **100.00% (`1.0000`)** | **+88.17% abs (+745.31% rel)** |
| **Unsupported Claims (Total across 100 tasks)** (`evaluate_unsupported_claims`) | 128 claims | 120 claims | **0 claims** | **-128 claims (-100.00%)** |
| **Escalation Recall** (`compute_escalation_metrics`) | **100.00% (`1.0000`)** | **100.00% (`1.0000`)** | **100.00% (`1.0000`)** | **0.00% (30/30 unsafe queries refused)** |
| **Escalation Precision** (`compute_escalation_metrics`) | 93.75% (`0.9375`) | 93.75% (`0.9375`) | **68.18% (`0.6818`)** | -25.57% abs (Conservative runtime citation gate) |
| **End-to-End Runner P50 Latency** (`calculate_percentiles`) | 15.862 s | 26.329 s | **20.532 s** | +4.670 s vs. Vector (**-5.797 s / -22.02% vs. 2-Way RRF**) |
| **End-to-End Runner P95 Latency** (`calculate_percentiles`) | 65.220 s | 69.214 s | **75.872 s** | +10.652 s (+16.33% — includes 15s retry backoffs) |

---

## 3. Root-Cause Engineering Analysis of Benchmark Progression

### 3.1 Retrieval Recall@5 Progression (47.14% $\rightarrow$ 52.14% $\rightarrow$ 62.86%)
1. **Stage 1 $\rightarrow$ Stage 2 (Vector Baseline $\rightarrow$ 2-Way Hybrid RRF, +5.00% abs / +10.61% rel):** Combining dense `pgvector` cosine distance (`<=>`) with PostgreSQL `ts_rank_cd` full-text search (`rrf_k = 60`) raised Recall@5 from `0.4714` to `0.5214`. However, trace inspection of `optimized_run.json` showed that 2-Way RRF still missed cross-referenced FCA Handbook provisions (e.g., `CONC 7.3.5E`, `CONC 5D.3.2R`, `PRIN 2A.9`) when an amending Policy Statement cited a rule code whose definition lived in another chunk.
2. **Stage 2 $\rightarrow$ Stage 3 (2-Way RRF $\rightarrow$ 3-Way Statutory Graph-RRF, +10.72% abs / +20.56% rel):** Introducing `src/retrieval/statutory_parser.py`, tagging chunks with `primary_rule_code`, indexing 1-hop statutory edges in `chunk_cross_references`, and fusing the `graph_search` SQL CTE (`graph_weight = 1.15`) in `apps/api/app/services/retrieval.py` lifted Recall@5 to **62.86% (`0.6286`)**—an overall **+33.35% relative gain** over the initial vector baseline.

### 3.2 Eliminating Hallucinations & Citation Drift (11.83% $\rightarrow$ 13.76% $\rightarrow$ 100.00% Citation Correctness; 128 $\rightarrow$ 120 $\rightarrow$ 0 Unsupported Claims)
In `baseline_run_final.json` and `optimized_run.json`, `verify_citation_exact_match` scored `11.83%` and `13.76%` while `evaluate_unsupported_claims` recorded `128` and `120` unsupported claims across the 100 tasks. Post-mortem inspection revealed two root causes that were resolved prior to `optimized_run_2.json`:
1. **Deterministic Context Propagation (`answer_generation.py`):** Previously, `generate_answer()` returned the structured LLM `AnswerResponse` on `status == "answered"` without copying `context_chunks` into `AnswerResponse.retrieved_chunk_ids` and `retrieved_chunk_excerpts` (only populating `retrieved_chunk_ids` on `insufficient_evidence` returns). Populating both lists deterministically across all code paths ensured `runner.py` and the LLM judge evaluated citations against the exact retrieved context.
2. **Runtime Verbatim Citation Gate (`validate_answer_citations` in `validation.py`):** Every generated citation is verified against the retrieved chunk database rows before leaving `/answer`. In `optimized_run_2.json`, **100.00% (`1.0000`)** of returned citations passed exact substring matching (`verify_citation_exact_match`), and the LLM faithfulness judge (`evaluate_unsupported_claims`) recorded **0 unsupported claims** across all 100 tasks.

### 3.3 Safety & Escalation Boundary Trade-Off (100.00% Recall; 93.75% $\rightarrow$ 68.18% Precision)
- **100.00% Escalation Recall across all 3 runs (`30/30` unsafe tasks refused):** Across all 30 negative test cases (15 out-of-domain tasks and 15 weak-evidence/unindexed tasks), the pipeline safely abstained (`status: "insufficient_evidence"`, `answer: null`) 100% of the time without fabricating regulatory guidance.
- **Why Escalation Precision moved from 93.75% (`30/32`) to 68.18% (`30/44`):** In `optimized_run_2.json`, 56 of the 70 positive queries were answered with 100% verbatim citations and 0 unsupported claims, while 14 positive queries were conservatively escalated (`status: "insufficient_evidence"`). Whenever the top-5 retrieved chunks lacked the specific clause needed to answer a multi-hop question or a candidate citation failed strict verbatim validation in `validate_answer_citations`, the runtime gate deterministically downgraded the response to `insufficient_evidence` rather than emitting an unverified claim. In UK FCA compliance workflows, trading lower escalation precision (`68.18%`) for **zero hallucinated claims (`0`) and 100.00% citation correctness** is the deliberate, audit-safe operating point.

### 3.4 Benchmark Runner Latency Profile (P50: 15.86s $\rightarrow$ 26.33s $\rightarrow$ 20.53s, P95: 65.22s $\rightarrow$ 69.21s $\rightarrow$ 75.87s)
The latency recorded across all three run files measures the **entire benchmark loop per task** in `src/evaluation/runner.py`:
- Each benchmark task executes **two sequential LLM calls** (the `/answer` pipeline generation via `gemini-3.7-flash` plus the `evaluate_unsupported_claims` LLM-as-a-judge call) and a VoyageAI embedding request.
- **P50 Latency improved by -22.02% (-5.80s) from 2-Way RRF (`26.329s`) to 3-Way Statutory Graph-RRF (`20.532s`):** Higher top-5 retrieval precision and indexed `primary_rule_code` / `chunk_cross_references` lookups reduced generation ambiguity on single-statute and cross-referenced queries.
- **P95 Tail Latency (`75.872s`):** In `src/evaluation/runner.py` (lines 60–70), whenever a task intentionally returns `answer: null` (`insufficient_evidence` on the 30 negative tasks and 14 conservatively escalated tasks), the runner loop retries up to `MAX_RETRIES = 2` times with `BACKOFF_SECONDS = 15.0` seconds (`+30s` sleep overhead per escalated task), which accounts for the ~65–76s P95 tail across the 100-task suite.

---

## 4. Shipped Engineering Upgrades & Verified Empirical Impact

Every bottleneck uncovered by the evaluation harness directly drove a production code upgrade verified in `optimized_run_2.json`:

| Bottleneck Identified in Evaluation & User Testing | Shipped Codebase Fix | Empirical Impact & Verification |
| :--- | :--- | :--- |
| **1. Cross-Statute Reference Blindness:** 2-Way RRF missed FCA Handbook rule codes (`CONC 7.3.5E`, `CONC 5D.3.2R`, `PRIN 2A.9`) referenced across chunks. | Implemented `src/retrieval/statutory_parser.py`, `DocumentChunk.primary_rule_code`, `ChunkCrossReference` (`chunk_cross_references`), and upgraded `retrieve_chunks()` (`apps/api/app/services/retrieval.py`) to **3-Way Graph-Augmented RRF**. | **Recall@5 jumped from 52.14% $\rightarrow$ 62.86%** (+33.35% rel over Vector Baseline); verified in `optimized_run_2.json` & `tests/unit/test_statutory_graph.py`. |
| **2. Empty `retrieved_chunk_ids` / `retrieved_chunk_excerpts` & Unverified Citations:** Pre-fix responses omitted retrieved chunk metadata on answered queries and allowed minor substring drift. | Updated `generate_answer()` (`apps/api/app/services/answer_generation.py`) to deterministically populate `retrieved_chunk_ids` and `retrieved_chunk_excerpts`, paired with strict runtime enforcement in `validate_answer_citations` (`validation.py`). | **Citation Correctness reached 100.00% (`1.0000`)** and **Unsupported Claims dropped from 128 $\rightarrow$ 120 $\rightarrow$ 0** in `optimized_run_2.json`; verified in `tests/unit/test_answer_validation.py`. |
| **3. Temporal Window Blindness (Issue 6.2 User Testing):** Testers noted that queries for *"last 30 days"* cited older foundational documents without indicating they fell outside the requested window. | Implemented `extract_requested_window_days()` and `is_chunk_within_window()` in `src/retrieval/freshness.py`, tagging every retrieved chunk and `Citation` with `is_within_window: bool`. | Deterministic staleness flags surfaced in API responses and UI; verified in `tests/unit/test_freshness.py`. |
| **4. Lost HTML & Multi-Page PDF Tables:** Regulatory schedules and threshold tables lost headers across page boundaries or were skipped in HTML extraction. | Implemented `apps/api/app/services/table_extraction.py` (`extract_pdf_page_tables`, `extract_html_table`, `parse_table_metadata_from_chunk_text`) storing `[REGULATORY TABLE]` Markdown and `DocumentChunk.table_metadata` JSONB. | Preserves column-aligned numeric caps and fee schedules across chunk boundaries; verified in `tests/unit/test_extraction.py`. |
