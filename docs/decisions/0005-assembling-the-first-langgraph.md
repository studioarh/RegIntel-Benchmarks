# 0005. Assemble First LangGraph Processing Workflow

**Date:** 25 September 2026  
**Status:** Accepted  

## Context
Previously, regulatory document processing ran as procedural code without formal checkpointing, explicit intermediate state validation, or inspectable branching. Because regulatory compliance mandates strict auditability and deterministic quality control, we need an orchestration framework that enforces typed state transitions, isolates node logic, and conditionally routes outputs based on evidence validation rather than relying on unstructured LLM prompt loops.

## Decisions

### 1. LangGraph StateGraph Architecture
- Structured the pipeline into an explicit `StateGraph(WorkflowState)` with sequential nodes: `load_document` -> `locate_prior_version` -> `create_diff` -> `retrieve_evidence` -> `extract_facts` -> `generate_briefing` -> `quality_gate`.
- Implemented conditional routing after `quality_gate`:
  - `status == "approved"` routes to `persist_approved_briefing`.
  - `status == "review_required"` routes to `create_review_task`.
- Downstream nodes (`generate_briefing`, `persist_approved_briefing`, and `create_review_task`) are stubbed with compliant data models for Issue 5 and will be completed in Issues 6 and 7.

### 2. State & Signature Refactoring
- **State Serialization:** Updated node signatures to accept and return plain primitives and Pydantic models (e.g. `diff: DocumentDiff`) rather than raw SQLAlchemy ORM instances to maintain clean JSON serialization and prevent detached-session runtime errors.
- **Canonical URL Uniqueness:** Removed the global `unique=True` constraint on `documents.canonical_url` (retaining `index=True`) to allow version tracking of identical regulatory publications over time. De-duplication remains strictly enforced via `content_hash`.
- **Passage-Level Diffing:** Implemented a custom `split_into_passages` regex utility instead of `.splitlines()` to handle multi-line paragraph semantics and strip synthetic PDF pagination headers before computing diffs with `difflib.SequenceMatcher`.

### 3. Testing Strategy
- Isolated database-querying nodes (`load_document`, `locate_prior_version`) from live PostgreSQL during unit tests by mocking `SessionLocal` via `MagicMock` / `monkeypatch`.
- Enhanced test database fixtures with automatic rollbacks (`yield` pattern) to ensure idempotent test runs.
- Added end-to-end graph compilation and routing integration tests verifying both the `approved` and `review_required` execution paths.

## Consequences
- **Positive:** Pipeline steps are completely decoupled, independently testable, and auditable at each node boundary.
- **Positive:** Malformed extractions or unsupported citations deterministically escalate to human review rather than silently persisting unverified briefings.
- **Trade-off:** Node signatures require strict adherence to `WorkflowState` contracts, requiring Pydantic model serialization across boundaries.
