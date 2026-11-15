# 0013. Multi-Stage Container Hardening and Production Topology

**Date:** 19 October 2026 
**Status:** Accepted 

## Context
RegIntel requires isolated, reproducible runtime environments that eliminate reliance on host-level system dependencies. Development setups rely on running as root, live-mounting local directories, and retaining build-time compiler packages in the filesystem.

The initial acceptance criteria for Issue 5.1 specified `python:3.11-slim`. However, the core application codebase leverages modern type annotations—specifically PEP 695 generic type parameter syntax on functions (such as `def call_structured_completion[T: BaseModel](...)` in `apps/api/app/services/llm.py`). Running this syntax under Python 3.11 produces a `SyntaxError` at parse time.

## Decision
1. **Runtime Target Upgrade to Python 3.12:**
   - Upgraded base images from `python:3.11-slim` to `python:3.12-slim` across both build and runtime stages to natively support PEP 695 type parameter syntax without compromising static typing guarantees.
2. **Multi-Stage Build Architecture (`Dockerfile`):**
   - **Stage 1 (Builder):** Uses `python:3.12-slim` and `build-essential` to compile C-extensions and install all dependencies into an isolated virtual environment at `/opt/venv`.
   - **Stage 2 (Runner):** Uses a clean `python:3.12-slim` image, copying only `/opt/venv` and required runtime source directories (`apps`, `src`, `config`, `alembic`). Build toolchains and pip caches are discarded.
3. **Principle of Least Privilege:**
   - Created a dedicated unprivileged Linux user and system group `appuser:appgroup` (`UID:GID 1000:1000`).
   - Dropped root privileges via `USER appuser` prior to invoking Uvicorn.
4. **Native Container Health Probes:**
   - Configured Docker `HEALTHCHECK` in `Dockerfile` querying `http://localhost:8000/health` via `curl` with a 30s interval, 5s timeout, and 15s start period.
5. **Build Context Optimization:**
   - Authored `.dockerignore` to exclude `.git`, local virtual environments (`.venv`), cache directories (`__pycache__`, `.pytest_cache`, `.ruff_cache`), local secrets (`.env`), tests, and local datasets.
6. **Production Topology (`docker-compose.prod.yml`):**
   - Defined isolated services: `api`, `postgres` (`pgvector/pgvector:pg16`), and `langfuse`.
   - Applied startup ordering constraints using `condition: service_healthy` to guarantee PostgreSQL readiness before the API initializes.

## Consequences
- Preserves modern PEP 695 syntax in application services without requiring backward-compatible `TypeVar` workarounds.
- Eliminates attack surface related to root container privileges and unnecessary compilation utilities.
- Guarantees dev/prod parity across the local container stack and cloud runtime targets.