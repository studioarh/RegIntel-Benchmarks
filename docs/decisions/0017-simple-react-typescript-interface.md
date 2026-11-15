# 0017. React + TypeScript Interface and CORS Security Boundary

**Date:** 01 November 2026 
**Status:** Accepted 

## Context

Prior to Week 6, interacting with the FCA Regulatory Compliance Copilot required sending raw HTTP requests via `curl`, automated test suites, or the FastAPI Swagger UI (`/docs`). While sufficient for backend development and evaluation benchmarking, a browser-based interface is needed so compliance reviewers and hiring managers can:

1. Configure API authentication (`X-API-Key`) interactively.
2. Submit FCA regulatory publication URLs for ingestion (`POST /v1/documents/ingest`).
3. Ask natural-language regulatory questions (`POST /answer`) and immediately inspect:
   - Whether the system synthesized a grounded answer (`answered`) or safely abstained (`insufficient_evidence`).
   - The categorical confidence rating (`low`, `medium`, `high`) and end-to-end `trace_id`.
   - Verbatim supporting citations (document title, source URL, publication date, and quoted excerpt).

Because the frontend runs on a separate browser origin (`http://localhost:5173` in local Vite development) from the containerized FastAPI backend (`http://localhost:8000`), browser security policies enforce Cross-Origin Resource Sharing (CORS) preflight `OPTIONS` checks whenever custom headers like `X-API-Key` and `Content-Type: application/json` are sent.

---

## Decision

### 1. Minimal Vite + React + Strict TypeScript SPA (`apps/web/`)
We implemented a lightweight Single-Page Application (SPA) in `apps/web/` using **React**, **TypeScript**, and **Vite** without heavy third-party UI component libraries or state-management frameworks:
- **Zero UI bloat:** Plain semantic HTML and scoped CSS (`apps/web/src/App.css`) keep the bundle small, fast to build, and easy to audit.
- **Strict compile-time type checking:** `npm run build` executes `tsc -b && vite build`, enforcing strict TypeScript verification equivalent to `mypy --strict` on the Python backend before emitting static production assets.

### 2. Explicit TypeScript Contract Mirroring (`apps/web/src/types/api.ts`)
We created `apps/web/src/types/api.ts` to mirror the backend Pydantic schemas across all 7 API routes:
- **Ingestion:** `IngestRequest` and `IngestionUrlResponse` (`POST /v1/documents/ingest`, `GET /v1/ingestion-runs/{run_id}`).
- **Grounded Q&A:** `AnswerRequest`, `AnswerResponse`, `AnswerStatus` (`"answered" | "insufficient_evidence"`), `ConfidenceLevel` (`"low" | "medium" | "high"`), and `Citation` (`POST /answer`).
- **Human-in-the-Loop Review Tasks:** `ReviewTaskResponse`, `ReviewStatus`, `ReviewTaskResolveRequest`, and `ReviewTaskResolveResponse` (`GET /review-tasks`, `POST /review-tasks/{task_id}/resolve`).
- **Agentic Workflows:** `WorkflowRunResponse`, `WorkflowRunDetailResponse`, and `WorkflowOutcome` (`POST /workflows/documents/{document_id}/run`, `GET /workflows/{workflow_run_id}`).

### 3. First-Class Refusal Visibility & End-to-End Traceability (`apps/web/src/App.tsx`)
In regulated financial compliance workflows, knowing *why* the system abstained is as important as reading an answer:
- **Client-generated `trace_id`:** Every `POST /answer` request generates a UUID via the browser's native `crypto.randomUUID()` and displays the returned `trace_id` alongside the response so any UI query can be correlated directly with backend structured logs and Langfuse traces.
- **Explicit Refusal Rendering:** When `status === "insufficient_evidence"`, the UI renders a high-visibility amber `INSUFFICIENT EVIDENCE` status badge and displays the backend `reason` field rather than an empty or generic error state.
- **Verbatim Citation Cards:** Supporting citations render document titles, clickable FCA source URLs (`rel="noopener noreferrer"`), publication dates, and verbatim excerpts.

### 4. FastAPI `CORSMiddleware` Configuration (`apps/api/app/main.py`)
We registered FastAPI's `CORSMiddleware` in `apps/api/app/main.py` to explicitly permit browser preflight `OPTIONS` requests from local Vite origins (`http://localhost:5173`, `http://127.0.0.1:5173`) and allow the `X-API-Key` and `Content-Type` headers.

---

## Consequences

### Positive
- **Immediate Portfolio & Compliance Usability:** Reviewers can test authenticated ingestion, grounded synthesis, citation verification, and safe abstention end-to-end in a clean web UI.
- **End-to-End Type Safety:** Backend responses are validated by Pydantic and `mypy --strict`, while frontend consumption is validated at compile time by `tsc -b`.
- **Traceability Preserved:** Propagating `trace_id` from the browser through `POST /answer` links user-visible answers directly to backend observability logs.

### Trade-offs & Mitigations
- **Manual Schema Synchronization:** TypeScript interfaces in `apps/web/src/types/api.ts` are maintained manually alongside backend Pydantic models. If backend response schemas change, `api.ts` must be updated accordingly. (For a compact 7-route API surface, explicit TypeScript interfaces are simpler and more transparent than adding an OpenAPI code-generation pipeline.)
- **Immutable Production Containers Require Rebuild:** Because our hardened production setup (`docker-compose.prod.yml`) bakes application code into the image rather than bind-mounting host source files, middleware or route updates require rebuilding the image (`docker compose -f docker-compose.prod.yml up --build -d`).

---

## Verification

1. **Frontend Type Check & Production Bundle:**
   ```bash
   cd apps/web && npm run build
   ```
2. **Backend Integration & CORS Preflight Verification:**
   ```bash
   ruff check .
   ruff format --check .
   mypy --strict --explicit-package-bases src/ apps/
   pytest tests/integration/test_security.py
   ```
