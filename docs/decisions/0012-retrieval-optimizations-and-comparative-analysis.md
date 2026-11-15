# 0012. Retrieval Optimizations and 3-Stage Benchmark Comparative Analysis

**Date:** 18 October 2026 
**Status:** Accepted 

## Context
Following the baseline evaluation established in ADR 0011, the retrieval and citation validation pipeline underwent two iterative optimization stages across the 100-task FCA benchmark (`data/evaluation/benchmark_100-2.jsonl` and `data/evaluation/benchmark_100-3.jsonl`):
1. **Stage 2 (2-Way Hybrid RRF — `optimized_run.json`):** Replaced vector-only cosine distance with 2-Way Reciprocal Rank Fusion (`rrf_k = 60`) combining dense VoyageAI embeddings (`<=>`) and PostgreSQL full-text search (`ts_rank_cd`), alongside structured constraint prompting.
2. **Stage 3 (3-Way Statutory Graph-RRF & Runtime Citation Gate — `optimized_run_2.json`):** Added UK FCA statutory rule parsing (`src/retrieval/statutory_parser.py`), 1-hop `chunk_cross_references` SQL graph traversal (`graph_weight = 1.15`), deterministic `retrieved_chunk_ids` / `retrieved_chunk_excerpts` response population (`answer_generation.py`), and runtime verbatim citation gating (`validate_answer_citations` in `validation.py`).

## Decision
1. **Implemented 2-Way then 3-Way Statutory Graph-Augmented RRF:** Fused dense vector distance (`<=>`), lexical full-text search (`plainto_tsquery`), and 1-hop statutory cross-reference edges (`chunk_cross_references`) in PostgreSQL using $k=60$ and $\text{graph\_weight}=1.15$.
2. **Enforced Deterministic Citation Context & Runtime Gating:** Guaranteed `retrieved_chunk_ids` and `retrieved_chunk_excerpts` population on every `/answer` response and rejected any generated answer whose citation fails verbatim substring validation.
3. **Standardized 3-Stage Benchmark Comparison:** Recorded full 100-task run artifacts in `data/evaluation/runs/baseline_run_final.json`, `data/evaluation/runs/optimized_run.json`, and `data/evaluation/runs/optimized_run_2.json` (detailed in `docs/evaluation-results.md`).

| Metric | Vector Baseline (`baseline_run_final.json`) | 2-Way RRF (`optimized_run.json`) | 3-Way Statutory Graph-RRF (`optimized_run_2.json`) |
| :--- | :---: | :---: | :---: |
| **Retrieval Recall@5** | 47.14% (`0.4714`) | 52.14% (`0.5214`) | **62.86% (`0.6286`)** |
| **Verbatim Citation Correctness** | 11.83% (`0.1183`) | 13.76% (`0.1376`) | **100.00% (`1.0000`)** |
| **Unsupported Claims (Total / 100 tasks)** | 128 claims | 120 claims | **0 claims** |
| **Escalation Recall** | **100.00% (`1.0000`)** | **100.00% (`1.0000`)** | **100.00% (`1.0000`)** |
| **Escalation Precision** | 93.75% (`0.9375`) | 93.75% (`0.9375`) | **68.18% (`0.6818`)** |
| **Runner P50 / P95 Latency** | 15.86s / 65.22s | 26.33s / 69.21s | **20.53s / 75.87s** |

## Consequences

### Positive
- **Retrieval Recall@5** progressed from **47.14% $\rightarrow$ 52.14% $\rightarrow$ 62.86%** (+15.72 percentage points / +33.35% relative gain over the vector baseline).
- **Verbatim Citation Correctness** reached **100.00% (`1.0000`)** and **Unsupported Claims** dropped from **128 $\rightarrow$ 120 $\rightarrow$ 0** across all 100 tasks.
- **Safety Escalation Recall** remained at **100.00%** across all three stages (`30/30` negative test cases refused), while P50 runner latency improved from `26.33s` in 2-Way RRF to `20.53s` in 3-Way Statutory Graph-RRF.

### Negative / Trade-offs
- Enforcing strict runtime citation verification (`validate_answer_citations`) conservatively escalates positive queries when retrieved passages lack exact statutory coverage, lowering Escalation Precision from `93.75%` (`30/32`) to `68.18%` (`30/44`) in exchange for zero unsupported claims.
- Multi-CTE retrieval and runner retry backoffs (`BACKOFF_SECONDS = 15.0` on intentionally refused tasks) yield a P95 runner latency of `75.87s`.
