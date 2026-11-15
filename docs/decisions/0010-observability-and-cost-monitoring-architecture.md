# 0010. Observability, Traceability, and Cost Monitoring Architecture

**Date:** 11 October 2026 
**Status:** Accepted  

## Context
In Week 3, the RegIntel platform established multi-step workflow graphs using LangGraph, persisting state transitions, human review tasks, and regulatory decisions to PostgreSQL. However, internal operations lacked runtime visibility into execution latency across nodes, token utilization, model invocation pricing, and retrieval span performance.

Debugging agent regressions, identifying high-latency tool execution, and budgeting operational API spend requires an observability architecture. This telemetry layer must integrate cleanly with LangGraph workflows without polluting core business logic, and it must degrade gracefully if the observability collector is misconfigured or unavailable.

## Decision Drivers
- **Zero Business Logic Pollution:** Tracing must attach via non-invasive callbacks rather than manual logging calls embedded inside graph nodes.
- **Fail-Safe Operation:** Missing credentials, network timeouts, or third-party observability downtime must never cause production workflows to abort.
- **Granular Lineage:** Every trace must capture run metadata, user identity, document scope, prompt versions, and model parameters.
- **Standardized Configuration:** Tracing configuration must emit native LangChain `RunnableConfig` objects compatible with LangGraph's `.invoke()` and `.ainvoke()` execution loops.

## Considered Alternatives
1. **Raw PostgreSQL Audit Logs:** We already persist run states to `WorkflowRun`. However, relational snapshots do not provide distributed spans, parent-child execution waterfalls, token accounting, or external tool latency profiling.
2. **OpenTelemetry with Custom Exporters:** Standard, but requires maintaining an OpenTelemetry Collector daemon, manual baggage propagation, and custom cost mapping per LLM token response.
3. **Langfuse Integration via Native Callbacks:** Purpose-built for LLM and agent frameworks. Connects directly to LangChain and LangGraph via `CallbackHandler`, calculates token pricing out of the box, and tracks session/user hierarchies natively.

## Decision
Adopted **Langfuse via LangChain Callbacks with Graceful Degradation** as the observability foundation, encapsulated behind a unified tracer factory in `src/observability/tracer.py`.

### 1. Unified Configuration Factory (`src/observability/tracer.py`)
Implemented `get_tracing_config(...)` to construct a fully populated `RunnableConfig`:
- **Dynamic Credential Check:** Evaluates `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` via `is_tracing_configured()`.
- **Safe Initialization:** Wraps `CallbackHandler` instantiation in a broad `try/except` block, returning `None` and emitting a warning if the client library fails or dependencies disconnect.
- **Metadata Standardization:** Injects runtime tags, environment profiles, prompt versions, user identifiers, and correlation keys into the root trace metadata.

```python
# Returns RunnableConfig with active callback if configured, empty list if absent
trace_config = get_tracing_config(
    trace_name="regulatory_qa",
    user_id="system:workflow_service",
    session_id=str(document_id),
    tags=["fca_handbook", "automated_qa"],
    metadata={
        "model": "gemini-3.7-flash",
        "temperature": 0.0,
        "workflow_run_id": str(trace_id),
        "document_id": str(document_id),
    },
)
```

### 2. Service-Level Orchestration (`src/services/workflow_service.py`)
Integrated tracing into `WorkflowExecutionService`:
- Correlation IDs (`trace_id` / `workflow_run_id`) are generated upfront as UUIDs.
- The `RunnableConfig` is passed into `regintel_app.invoke(initial_state, config=trace_config)`.
- Internal nodes (document extraction, vector retrieval, entity structuring, quality gating) emit child spans automatically under the root trace.
- The PostgreSQL `WorkflowRun` record records the matching `trace_id` as its primary key, allowing direct cross-referencing between the database record and the Langfuse trace.

### 3. Graceful Fallback Semantics
If Langfuse credentials are not provided or the backend is offline:
- `get_langfuse_callback()` returns `None`.
- `config["callbacks"]` evaluates to `[]`.
- Graph execution proceeds normally without throwing exceptions or degrading request latency.

## Consequences

### Positive
- **Automated Cost Tracking:** Langfuse ingests input and completion token usage directly from model responses and computes dollar spend per run.
- **End-to-End Traces:** Node-level latency, vector query performance, and prompt inputs/outputs are visible in a single timeline view.
- **High Fault Tolerance:** Zero crash risk during external observability outages.
- **Relational Correlation:** Database `WorkflowRun.id` matches the Langfuse `workflow_run_id`, linking audit records to external traces.

### Negative / Trade-offs
- Adds an external dependency (`langfuse`) to the service footprint.
- Self-hosted setups require deploying and maintaining a Langfuse container alongside PostgreSQL and Redis.

## Validation
Implementation verified across unit test suites (`tests/unit/observability/test_tracer.py`):
1. Confirmed unconfigured environments cleanly return `{"callbacks": []}` without errors.
2. Confirmed valid credentials initialize the callback handler.
3. Confirmed connection and instantiation exceptions degrade to `None` without raising runtime exceptions.
4. Confirmed `WorkflowExecutionService` propagates the trace context to LangGraph executions.