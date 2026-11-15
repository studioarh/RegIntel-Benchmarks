# ADR-0002: Unified PostgreSQL 16 + pgvector Storage & Statutory Graph Schema

## Status
Accepted

## Context
Regulatory intelligence systems require three distinct retrieval modalities over the same corpus:
1. **Dense Semantic Retrieval:** High-dimensional vector similarity over embedded chunks (`1024`-dim VoyageAI embeddings).
2. **Lexical Full-Text Search:** Exact keyword, rule number, and phrase matching (`ts_rank_cd` over `to_tsvector('english', text)`).
3. **Statutory Cross-Reference Traversal:** Following explicit UK regulatory rule links (`AMENDS`, `SUPERSEDES`, `EXEMPTS`, `REFERENCES`) between sourcebooks (`SYSC`, `PRIN`, `DISP`, `ESG`, `CONC`, `MCOB`, `CASS`, `MAR`).

Maintaining separate vector databases (e.g., Pinecone/Qdrant), search clusters (Elasticsearch), and graph stores (Neo4j) introduces distributed transaction drift, eventual-consistency bugs during document re-ingestion, and operational overhead.

## Decision
We standardize on a single **PostgreSQL 16 + `pgvector`** instance as our unified relational, vector, lexical, and statutory graph store:
- **Vector Index:** `HNSW` index (`m = 16, ef_construction = 64`) on `document_chunks.embedding` (`Vector(1024)`) using cosine distance (`<=>`).
- **Lexical Index:** `GIN` index on `to_tsvector('english', text)` for fast `ts_rank_cd` scoring.
- **Statutory Graph Edges:** Relational `chunk_cross_references` table (`source_chunk_id`, `source_rule_code`, `target_rule_code`, `target_chunk_id`, `relation_type`) indexed on `(source_chunk_id, target_rule_code)` and joined directly inside our single-pass 7-CTE Reciprocal Rank Fusion (`rrf_k = 60`, `graph_weight = 1.15`) SQL query.

## Consequences
- **Positive:** ACID consistency across document versions, chunks, embeddings, and statutory graph edges; single-query 3-Way Hybrid RRF execution with zero cross-network serialization overhead.
- **Negative:** Requires PostgreSQL 16 with `pgvector` extension enabled across all local, CI, and cloud environments.
