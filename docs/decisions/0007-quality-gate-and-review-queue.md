# 0007. Implement Quality Gate and Human Review Queue

**Date:** 05 October 2026  
**Status:** Accepted  

## Context
In Issue 6, the system implemented structured briefing generation with evidence citations, explicit inference labeling, and uncertainty flags. However, to meet production compliance standards, unverified claims, weak evidence sets, and schema failures must never be published automatically. We need a deterministic quality gate to evaluate each run against strict objective criteria and route uncertain or invalid briefings to a database-backed human review queue rather than allowing ungrounded regulatory intelligence downstream.

## Decisions

1. **Rule-Based Quality Gate Evaluation:**
   Implemented a deterministic quality gate node (`quality_gate`) that evaluates candidate outputs against five non-negotiable criteria:
   - **Extraction Validation:** Enforced via `ExtractionResult.is_valid`, ensuring raw LLM fact extractions conform strictly to the Pydantic schema without silent error suppression.
   - **Allowed Citations & 100% Coverage:** Verified that all cited chunk IDs map directly to chunks retrieved for the run and that every factual claim retains at least one valid citation.
   - **Evidence Quality Threshold:** Checked that the minimum evidence score meets or exceeds `settings.min_evidence_score` (`min_fact_evidence_score >= 0.70`). Documented this metric as an *internal retrieval-quality signal* pending calibrated evaluation in Week 4.
   - **Critical Uncertainty Absence:** Ensured no critical flags (e.g., `insufficient_evidence`, `unsupported_claim`, `unsupported_date`) are present in `uncertainty_flags`.

2. **Conditional Routing and Review Task Creation:**
   - Configured LangGraph conditional routing (`route_quality_decision`) to branch between `persist_approved_briefing` (on `approved`) and `create_review_task` (on `review_required`).
   - Persisted held briefings to a dedicated `review_tasks` table containing reason codes, candidate briefing payloads (`JSONB`), retrieved evidence snapshots (`JSONB`), document references, and `workflow_run_id` foreign keys.
   - Added review task management endpoints to list pending review tasks (`GET /review-tasks`) and resolve them with reviewer notes (`POST /review-tasks/{task_id}/resolve`).

3. **Type Safety and Model Refinement:**
   - Standardized SQLAlchemy ORM mappings using `Mapped[uuid.UUID]` with `UUID(as_uuid=True)` across `WorkflowRun` and `ReviewTasks` models to maintain static type parity with `mypy`.
   - Typed workflow outcomes explicitly (`WorkflowOutcome.RUNNING`, `WorkflowOutcome.APPROVED`, `WorkflowOutcome.REVIEW_REQUIRED`).
   - Standardized task review states using a typed enum (`ReviewStatus.PENDING`, `ReviewStatus.APPROVED`, `ReviewStatus.REJECTED`).

4. **Integration Testing and Isolation:**
   - Added database teardown fixtures to handle foreign key dependencies between `workflow_runs` and `review_tasks` cleanly during local pytest runs.
   - Unit-tested both branches of the compiled LangGraph execution to ensure approved briefs persist while invalid/uncertain runs reliably yield review tasks.

## Consequences
- No factual claim can be published without verified source chunks and 100% citation coverage.
- The system gracefully handles model extraction failures and missing evidence by queuing review tasks instead of raising unhandled exceptions or returning fabricated summaries.
- All review items retain their full contextual payloads (briefing JSON, evidence citations, and failure reason codes), enabling seamless compliance analyst triage in subsequent workflow steps.