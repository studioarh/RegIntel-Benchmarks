# 0016. Cloud Deployment Topology and Secret Management

**Date:** 26 October 2026 
**Status:** Accepted 

## Context

RegIntel requires a publicly accessible production deployment so external stakeholders and hiring managers can inspect live API endpoints (`/health`, `/docs`, `/v1/documents/ingest`, `/api/v1/query`, `/workflows`) and verify end-to-end regulatory intelligence workflows.

Deploying a production RAG and agentic workflow system introduces three operational requirements:
1. **Vector Database Compatibility:** The managed PostgreSQL database must natively support PostgreSQL 16 and the `pgvector` extension for embedding similarity search alongside transactional workflow state.
2. **Container Reproducibility:** The cloud runtime must execute the exact Docker image validated in development and GitHub Actions CI (`python:3.12-slim` with `psycopg[binary]`).
3. **Zero-Trust Secret Management:** The system relies on multiple sensitive credentials (`API_KEY`, `VOYAGE_API_KEY`) etc, and Google Cloud Vertex AI service account JSON keys. Zero plaintext secrets may exist in Git history or container build layers.

## Decision

We decided to deploy RegIntel using a **Managed Container Web Service** paired with a **Managed PostgreSQL 16 (`pgvector`)** instance within the same private cloud region:

1. **Managed Compute & Private Networking:**
   - The FastAPI + LangGraph application is packaged via a single production `Dockerfile` and deployed to a managed container platform (Render) triggered from the `main` branch after CI quality gates pass.
   - Database traffic between the API container and the PostgreSQL 16 instance is routed over an internal private network using the `postgresql+psycopg://` SQLAlchemy 2.0 driver scheme.
   - The `/health` endpoint is configured as the platform's liveness/readiness probe for zero-downtime rollouts.

2. **Runtime Secret Injection & Mounted Secret Files:**
   - All scalar secrets (`DATABASE_URL`, `API_KEY`, `VOYAGE_API_KEY` etc)  are stored exclusively in the cloud provider's encrypted environment store and injected into the container environment at runtime.
   - Multi-line service account credentials (`gcp-credentials.json` for Vertex AI) are mounted at runtime as a read-only secret file (`/etc/secrets/gcp-credentials.json`) and referenced via `GCP_CREDENTIALS_PATH`, ensuring credentials are never baked into Docker layers or committed to Git.

3. **Schema Migration Discipline:**
   - Database schema changes are managed deterministically via Alembic (`alembic upgrade head`) after enabling `CREATE EXTENSION IF NOT EXISTS vector;` on the managed database instance.

## Consequences

### Positive
- **Complete Secret Isolation:** Git repository history remains 100% free of credentials, `.env` files, and service account keys, allowing the repository to be safely public.
- **Architectural Parity:** Using `pgvector` on managed PostgreSQL 16 mirrors the exact `pgvector/pgvector:pg16` service container tested in GitHub Actions CI (Issue 5.4).
- **Operational Simplicity:** Consolidating relational tables and vector embeddings into a single managed PostgreSQL instance eliminates the latency, cost, and synchronization overhead of maintaining a separate external vector database.

### Negative / Trade-offs
- **Cold Start Latency on Entry-Tier Compute:** If deployed on scale-to-zero or entry-tier container instances, initial requests after inactivity may experience a cold-start delay while Uvicorn initializes.
- **Manual/Controlled Migration Step:** Running `alembic upgrade head` requires explicit verification during schema updates to prevent breaking changes during zero-downtime container swaps.
