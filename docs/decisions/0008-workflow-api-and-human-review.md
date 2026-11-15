# 0008. Expose, Test, and Document the Intelligence Workflow

**Date:** 08 October 2026 
**Status:** Accepted  

## Context
Across Issues 1 through 7, we built the LangGraph pipeline, deterministic diffing, structured fact extraction, evidence-backed briefing generation, and the rule-based quality gate. However, the workflow remained an internal Python module without external entry points. Issue 8 exposes the full regulatory intelligence agent via public FastAPI endpoints, provides endpoints to triage and resolve held review tasks, integrates end-to-end API tests, and documents the system operational runbook for compliance analysts and auditors.

## Decisions

1. **Workflow Trigger & Inspection API:**
   - **`POST /workflows/documents/{document_id}/run`**: Dispatches the compiled LangGraph pipeline for a target document, returning immediately with the `workflow_run_id`, document metadata, and execution status (`approved`, `review_required`, or `failed`).
   - **`GET /workflows/{workflow_run_id}`**: Retrieves the comprehensive audit trail for a run, combining scalar fields (`status`, `trace_id`, execution timestamps) with structured deliverables extracted from `output_json` (and `state_json` fallback), including `quality_decision`, `briefing`, and `evidence`.

2. **Database-Backed Human Review Triage:**
   - **`GET /review-tasks`**: Lists pending review tasks filtered by status (`pending`, `approved`, `rejected`), returning candidate briefings, failure reason codes, and original source evidence snapshots.
   - **`POST /review-tasks/{task_id}/resolve`**: Allows compliance reviewers to transition tasks to `approved` or `rejected`. Mandates typed `reviewer_notes` and records timezone-aware UTC resolution timestamps (`resolved_at`) to preserve compliance auditability.

3. **OpenAPI & Error Contract Verification:**
   - Documented explicit OpenAPI response codes (`200 OK`, `400 Bad Request`, `404 Not Found`, `422 Unprocessable Entity`) across all workflow and review routes.
   - Leveraged Pydantic request models (`ResolveReviewTaskRequest`) and typed Enums (`ReviewStatus`) to guarantee payload validation at the HTTP boundary.

4. **Integration Testing Strategy:**
   - Created hermetic integration tests in `tests/integration/test_workflow_api.py` using FastAPI `TestClient` and pre-seeded database fixtures (`sample_document`, `workflow_run`, `review_task`).
   - Verified that end-to-end execution correctly branches into the review queue on weak evidence and that reviewers can resolve tasks without side effects.

## Consequences
- The RegIntel agent workflow is now fully accessible over HTTP, allowing external services, frontends, or scheduled ingestion workers to trigger and inspect compliance runs.
- Compliance analysts have an operational mechanism to inspect uncertain briefings and resolve review tasks without direct database intervention.
- Week 3 is formally completed with full unit test, integration test, and static typing (`mypy`) coverage, establishing the foundation for Week 4's 100-task evaluation benchmark.