# 0014. LLM Retry Policy and Multi-Provider Failover

**Date:** 24 October 2026 
**Status:** Accepted 

## Context
RegIntel's ingestion, change-extraction, and briefing workflows depend on upstream LLM calls with strict Pydantic structured outputs. Relying on a single unguarded model invocation exposes live analyst queries and background ingestion jobs to transient upstream faults—specifically HTTP `429` (`ResourceExhausted` / rate limits), `500` (`InternalServerError`), `502` (`BadGateway`), `503` (`ServiceUnavailable`), and `504` (`DeadlineExceeded`).

Furthermore:
1. Default SDK retry loops obscure retry counts and wait timings from application-level observability and unit tests.
2. Deterministic retry intervals risk causing synchronized retry storms ("thundering herd") when multiple concurrent requests encounter rate limits simultaneously.
3. Persistent single-model outages require automatic failover to a secondary model without breaking downstream Pydantic schema contracts or leaking raw vendor SDK exceptions into API and LangGraph layers.

## Decision

### 1. Centralized `ResilientLLMClient` Abstraction
We introduced `ResilientLLMClient` in `src/agents/llm_client.py` to encapsulate both direct structured calls (`invoke_structured`) and LangChain Expression Language (LCEL) pipelines (`invoke_runnable` via `RunnableLambda`). Internal LangChain retries are capped (`max_retries=1`) so retry orchestration is managed explicitly by `tenacity`.

### 2. Exponential Backoff with Additive Random Jitter
Primary model invocations (`gemini-3.7-flash`) in `_call_primary` are wrapped with `@retry`:
* **Exception Filtering:** Retries trigger strictly on transient upstream errors (`RETRYABLE_GOOGLE_ERRORS` and HTTP status codes `429`, `500`, `502`, `503`) via `_is_retryable_google_genai_error`. Permanent client errors (e.g., `400`, `401`, validation errors) fail fast without retrying.
* **Backoff & Jitter:** Configured with `wait_exponential(multiplier=1, min=2, max=10) + wait_random(0, 1)` to enforce a `2.0s` minimum floor, `10.0s` exponential cap, and `0.0s–1.0s` random jitter to desynchronize concurrent retries.
* **Attempt Cap:** Bounded via `stop_after_attempt(3)` and `reraise=True` so terminal failures propagate immediately to the failover handler after the third attempt.

### 3. Secondary Provider Failover and Structured Telemetry
When `_call_primary` exhausts its 3 attempts and raises a `PROVIDER_FAILURE_EXCEPTIONS` error, `_invoke_with_fallback` catches the terminal exception and routes the prompt and target Pydantic schema directly to the secondary fallback client (`gemini-3.6-flash`). Upon recovery, it emits a structured `WARNING` log containing:
* `original_error`: The terminal exception from the primary provider.
* `fallback_provider`: The secondary model identifier (`gemini-3.6-flash`).
* `invocation_latency_ms`: Wall-clock execution time of the fallback call.

### 4. Explicit Domain Error Boundary (`LLMProviderError`)
If both primary and fallback providers fail, `_invoke_with_fallback` raises a custom `LLMProviderError` domain exception preserving both `primary_error` and `fallback_error` instances. This prevents raw Google SDK or LangChain exceptions from leaking across architectural boundaries and enables clean escalation to human review.

## Consequences

### Positive
* **High Availability:** Transient quota spikes (`429`) and brief upstream hiccups (`502`/`503`) self-heal transparently without failing analyst queries or ingestion runs.
* **Schema & Output Parity:** Both primary and fallback paths enforce identical `.with_structured_output(schema)` contracts, guaranteeing type-safe Pydantic responses regardless of which provider serves the request.
* **Deterministic Testability:** Dependency injection of `primary_client` and `fallback_client` in `ResilientLLMClient.__init__` allows `tests/unit/test_llm_resilience.py` to verify retry counts, backoff durations, and failover behavior without live network calls.

### Trade-offs
* **Tail Latency on Outages:** When the primary model experiences a persistent outage, requests incur the cumulative wait duration of two backoff intervals (`~4.0s–6.0s`) across 3 attempts before failing over to `gemini-3.6-flash`.