# RegIntel System Architecture

## 1. High-Level System Architecture

**RegIntel** is a traceable regulatory intelligence platform designed for UK consumer-lending compliance teams. It ingests allow-listed FCA publications, indexes them in a unified PostgreSQL 16 + `pgvector` database for **3-Way Graph-Augmented Reciprocal Rank Fusion (RRF)** search, and executes both contract-enforced RAG Q&A and a controlled 9-node **LangGraph** workflow to produce source-cited compliance briefings.

```mermaid
flowchart TB
    subgraph Sources["Allowlisted UK FCA Regulatory Sources (src/ingestion/poller.py)"]
        FCA["FCA Policy & Consultation Papers\n(fca.org.uk)"]
        HB["FCA Handbook & API Sourcebooks\n(handbook.fca.org.uk / api-handbook.fca.org.uk)"]
        REG["FCA Financial Services Register\n(register.fca.org.uk)"]
    end

    subgraph Ingestion["Ingestion & Processing Pipeline (apps/api/app/services)"]
        FETCH["Allowlisted Fetcher & SHA-256 Deduplicator\n(ingestion.py, extraction.py)"]
        TABLE["Layout-Aware PDF & HTML Table Stitcher\n(table_extraction.py)"]
        CHUNK["FCA Regex Section-Aware Chunker\n(chunking.py: 1500 chars, 250 overlap)"]
        STAT["Statutory Rule & Cross-Reference Parser\n(statutory_parser.py)"]
        EMBED["Embedding Service\n(embedding.py: VoyageAI voyage-3 1024-dim)"]
    end

    subgraph Storage["Unified Data Layer (PostgreSQL 16 + pgvector — apps/db/models.py)"]
        PG_DOC[("documents & ingestion_runs\n(Metadata, SHA-256, Versioning)")]
        PG_VEC[("document_chunks & chunk_cross_references\n(Vector(1024) <=> + English tsvector + 1-Hop Graph)")]
        PG_AUD[("query_runs, query_citations, workflow_runs,\nreview_tasks, organizations, tenant_api_keys")]
    end

    subgraph RetrievalAndRAG["3-Way Hybrid Graph-RRF & Contract RAG (apps/api & src/retrieval)"]
        HYBRID["3-Way SQL Retriever (retrieve_chunks)\nVector <=> + ts_rank_cd + 1-Hop Statutory Graph (rrf_k=60)"]
        FRESH["Temporal Window Verifier\n(freshness.py: is_chunk_within_window)"]
        CONTRACT["Contract-Bound Generator & Validator\n(llm.py, answer_generation.py, validation.py)"]
    end

    subgraph AgentWorkflow["Controlled 9-Node LangGraph Workflow (src/agents)"]
        DIFF["Hierarchical Section-Tree & Interval Diff\n(diffing.py: calculate_diff, get_relevant_chunks_for_diff)"]
        EXTRACT["Structured Fact Extractor\n(change_extraction.py: extract_changes)"]
        BRIEF["Briefing Synthesizer\n(nodes.py: generate_briefing)"]
        GATE["Quality & Confidence Gate\n(nodes.py: quality_gate -> persist / create_review_task)"]
    end

    subgraph LLM["Resilient LLM Layer (src/agents/llm_client.py)"]
        PRIMARY_LLM["Primary Model: ChatGoogleGenerativeAI\n(gemini-3.7-flash)"]
        FALLBACK["Fallback Model: ChatGoogleGenerativeAI\n(gemini-3.6-flash)"]
    end

    subgraph Delivery["API, Frontend & Observability"]
        API["FastAPI Backend\n(Multi-Tenant SHA-256 Auth, SlowAPI Rate Limiting)"]
        WEB["React + TypeScript Compliance Workbench\n(apps/web/src/App.tsx: 4 Tabs + 1-Click Sandbox)"]
        OBS["Langfuse Tracing\n(src/observability/tracer.py)"]
    end

    Sources --> FETCH --> TABLE --> CHUNK --> STAT --> EMBED --> PG_VEC
    FETCH --> PG_DOC
    API <--> HYBRID
    HYBRID <--> PG_VEC
    HYBRID --> FRESH --> CONTRACT
    API <--> DIFF
    DIFF <--> PG_DOC
    DIFF --> EXTRACT --> BRIEF --> GATE
    CONTRACT <--> LLM
    EXTRACT <--> LLM
    BRIEF <--> LLM
    PRIMARY_LLM -. "Tenacity Exponential Backoff +\nJitter / Model Failover" .-> FALLBACK
    CONTRACT --> PG_AUD
    GATE --> PG_AUD
    WEB <--> API
    LLM -.-> OBS
```

---

## 2. End-to-End Component Flow

### 2.1 Document Ingestion, Table Reconstruction & Statutory Graph Indexing
1. **Allowlisted Fetching (`src/ingestion/poller.py` & `apps/api/app/services/ingestion.py`):** Manual ingestion (`POST /v1/documents/ingest`) and feed polling (`POST /v1/documents/poll-fca`) validate target URLs against `ALLOWED_FCA_HOSTS` (`fca.org.uk`, `handbook.fca.org.uk`, `api-handbook.fca.org.uk`, `register.fca.org.uk`) and execute inside an isolated background SQLAlchemy session (`_run_background_ingestion`).
2. **Idempotency & Version Tracking:** A SHA-256 `content_hash` is computed over normalized document text. Unchanged documents short-circuit idempotently; updated content for an existing `canonical_url` increments `version_number`.
3. **Layout-Aware Table Extraction (`apps/api/app/services/table_extraction.py`):** Extracts HTML `<table>` tags and PDF tables (`page.find_tables()`), stitching column headers across multi-page continuations and formatting self-contained `[REGULATORY TABLE]` Markdown blocks plus structured `DocumentChunk.table_metadata` JSONB.
4. **Chunking, Statutory Graph Edges & Embeddings (`chunking.py`, `statutory_parser.py`, `embedding.py`):** Documents are split into structure-aware chunks (`1500` chars, `250` overlap) using FCA Handbook regex lookaheads (`CONC`, `DISP`, `PRIN`, `MCOB`, `SYSC`), tagged with `primary_rule_code`, linked via 1-hop edges in `chunk_cross_references` (`amends`, `supersedes`, `exempts`, `references`), and embedded via **VoyageAI (`voyage-3`, `Vector(1024)`)**.

### 2.2 3-Way Graph-Augmented RRF Retrieval & Temporal Freshness Enrichment
When a user submits a compliance question via `retrieve_chunks` (`apps/api/app/services/retrieval.py`):
1. **Vector Search CTE (`vector_search`):** Ranks the top `:candidate_limit` (25) chunks using `pgvector` cosine distance (`dc.embedding <=> cast(:embedding as vector)`).
2. **Lexical Search CTE (`text_search`):** Ranks the top `:candidate_limit` (25) chunks using PostgreSQL full-text search (`ts_rank_cd(to_tsvector('english', dc.text), plainto_tsquery('english', :query_text))`).
3. **Statutory Graph CTE (`graph_search`):** Matches chunks whose `primary_rule_code` appears in the query or that are linked via 1-hop `chunk_cross_references` edges from the top vector/lexical seed chunks.
4. **3-Way Reciprocal Rank Fusion (`fused`):** Merges all three ranked lists inside a single SQL query:
   $$RRF\_Score = \frac{1}{60 + rank_{vec}} + \frac{1}{60 + rank_{lex}} + \frac{1.15}{60 + rank_{graph}}$$
5. **Deterministic Temporal Window Check (`is_chunk_within_window` in `src/retrieval/freshness.py`):** Extracts relative time constraints (`last/past/previous N days/weeks/months`) and tags each chunk and `Citation` with `is_within_window: bool`.

### 2.3 Contract-Enforced Generation & Controlled 9-Node LangGraph Workflow
1. **Evidence-Cited Q&A (`generate_answer` & `generate_answer_with_contract`):** Invokes `ResilientLLMClient` with strict Pydantic structured outputs (`AnswerResponse`), validates every citation via `validate_answer_citations` (`apps/api/app/services/validation.py`), and populates `retrieved_chunk_ids`, `retrieved_chunk_excerpts`, `primary_rule_code`, `referenced_rules`, and `table_metadata`.
2. **9-Node LangGraph Regulatory Briefing Pipeline (`src/agents/graph.py` & `src/agents/nodes.py`):**
   - `load_document` $\rightarrow$ `get_prior_version` $\rightarrow$ `create_diff` (hierarchical section-tree diffing + interval-overlap chunk matching in `diffing.py`) $\rightarrow$ `retrieve_evidence` $\rightarrow$ `extract_facts` $\rightarrow$ `generate_briefing` $\rightarrow$ `quality_gate` $\rightarrow$ conditional routing to `persist_approved_briefing` or `create_review_task`.

---

## 3. Database Schema (PostgreSQL 16 + `pgvector` — `apps/db/models.py`)

```mermaid
erDiagram
    ORGANIZATIONS ||--o{ TENANT_API_KEYS : owns
    ORGANIZATIONS ||--o{ QUERY_RUNS : executes
    ORGANIZATIONS ||--o{ WORKFLOW_RUNS : executes
    ORGANIZATIONS ||--o{ REVIEW_TASKS : reviews
    DOCUMENTS ||--o{ DOCUMENT_CHUNKS : contains
    DOCUMENTS ||--o{ INGESTION_RUNS : tracks
    DOCUMENTS ||--o{ WORKFLOW_RUNS : analyzes
    DOCUMENT_CHUNKS ||--o{ CHUNK_CROSS_REFERENCES : links
    WORKFLOW_RUNS ||--o{ REVIEW_TASKS : escalates_to
    QUERY_RUNS ||--o{ QUERY_CITATIONS : cites
    DOCUMENT_CHUNKS ||--o{ QUERY_CITATIONS : supports

    ORGANIZATIONS {
        uuid id PK
        varchar name
        varchar fca_frn
        jsonb watched_sourcebooks
        enum plan_tier "sandbox | solo | firm | consultancy"
        varchar subscription_status
        integer monthly_briefing_quota
        integer monthly_briefings_used
        timestamptz created_at
    }

    TENANT_API_KEYS {
        uuid id PK
        uuid organization_id FK
        varchar key_prefix "ri_live_... / ri_test_..."
        varchar key_hash UK "SHA-256 hex digest"
        varchar label
        boolean is_active
        timestamptz last_used_at
        timestamptz created_at
    }

    DOCUMENTS {
        uuid id PK
        varchar canonical_url
        varchar title
        varchar source_name "Default: FCA"
        varchar source_type "text/html | application/pdf | text/plain"
        timestamptz published_at
        varchar content_hash UK "SHA-256"
        integer version_number
        timestamptz created_at
    }

    DOCUMENT_CHUNKS {
        uuid id PK
        uuid document_id FK
        integer chunk_index
        varchar section_heading
        integer page_number
        integer char_start
        integer char_end
        text text
        vector_1024 embedding "VoyageAI 1024-dim pgvector"
        varchar primary_rule_code "e.g. CONC 3.3.1AR"
        jsonb table_metadata "Reconstructed table headers & rows"
        timestamptz created_at
    }

    CHUNK_CROSS_REFERENCES {
        uuid id PK
        uuid source_chunk_id FK
        varchar source_rule_code
        varchar target_rule_code
        uuid target_chunk_id FK
        varchar relation_type "amends | supersedes | exempts | references"
        timestamptz created_at
    }

    INGESTION_RUNS {
        uuid ingestion_id PK
        text document_url
        enum status "queued | processing | completed | failed"
        uuid document_id FK
        varchar error_code
        varchar error_message
        varchar embedding_model
        integer embedding_dimensions
        timestamptz created_at
        timestamptz started_at
        timestamptz completed_at
    }

    QUERY_RUNS {
        uuid id PK
        uuid organization_id FK
        text question
        varchar status "answered | insufficient_evidence"
        text answer
    }

    QUERY_CITATIONS {
        uuid id PK
        uuid query_run_id FK
        uuid chunk_id FK
        text excerpt
        integer citation_order
    }

    WORKFLOW_RUNS {
        uuid id PK
        uuid organization_id FK
        uuid document_id FK
        uuid trace_id
        enum workflow_type
        text retrieval_config_version
        text prompt_version
        jsonb state_json
        jsonb output_json
        enum outcome "approved | review_required | failed | crashed | running"
        text error_message
    }

    REVIEW_TASKS {
        uuid id PK
        uuid organization_id FK
        uuid workflow_run_id FK
        uuid document_id FK
        jsonb reason_codes
        jsonb candidate_briefing
        jsonb evidence_payload
        text reviewer_notes
        varchar resolution
        enum status "pending | approved | rejected"
        timestamptz created_at
        timestamptz resolved_at
    }
```
