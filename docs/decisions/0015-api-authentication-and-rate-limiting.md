# 0015. API Authentication and Rate Limiting

**Date:** 24 October 2026 
**Status:** Accepted 

## Context
As RegIntel transitions to a containerized production deployment, exposing API endpoints without access controls introduces two primary operational risks:

1. **Inference Budget Exhaustion (Denial of Wallet):** Unauthenticated callers or automated scrapers could trigger high-volume document ingestion, vector embedding generation, and Gemini LLM invocations.
2. **Compute and Database Starvation:** Burst traffic from a single client could saturate PostgreSQL connection pools and Uvicorn workers, degrading availability for legitimate analysts.

Simultaneously, container health checks and cloud load balancers must be able to poll the `/health` endpoint continuously without transmitting secret credentials.

## Decisions
1. **Header-Based API Key Authentication (`X-API-Key`):**
   * Implemented `verify_api_key` in `src/api/security.py` and attached it globally to the FastAPI application via `dependencies=[Depends(verify_api_key)]`.
   * Used `APIKeyHeader(name="X-API-Key", auto_error=False)` with `Security()` so missing and invalid keys both consistently return `HTTP 401 Unauthorized` with standard error JSON (`{"detail": "..."}`) while preserving OpenAPI `/docs` authorization support.
   * Validated incoming keys against approved runtime keys (`settings.api_key`) using `secrets.compare_digest` on UTF-8 encoded bytes to prevent timing side-channel attacks and handle non-ASCII characters safely.
   * Exempted `/health` (normalized via `request.url.path.rstrip("/")`) via `PUBLIC_PATHS` so load balancer health probes bypass authentication and return `200 OK`.

2. **Token Bucket Rate Limiting (`slowapi`):**
   * Configured `Limiter` in `src/api/security.py` with `default_limits=["60/minute"]`, backed by `storage_uri="memory://"` and wired globally into FastAPI via `app.state.limiter` and `SlowAPIMiddleware`.
   * Scoped rate-limit buckets per client via `get_rate_limit_key`, using `key:<X-API-Key>` for authenticated requests and falling back to `ip:<remote_address>` via `get_remote_address(request)` for unauthenticated requests.
   * Registered a synchronous `rate_limit_exceeded_handler` for `RateLimitExceeded` that returns `HTTP 429 Too Many Requests`, a structured `{"detail": "..."}` JSON payload, and a `"Retry-After": "60"` header when a client exceeds 60 requests per minute.

## Consequences
* **Positive:** All application routes are automatically protected against unauthenticated access and high-frequency traffic bursts without duplicating decorators across individual router files.
* **Positive:** Any single API key or IP address is strictly capped at 60 requests per minute, protecting upstream Gemini inference budgets and PostgreSQL resources.
* **Positive:** Integration tests in `tests/integration/test_security.py` deterministically verify `401` rejections, `/health` exemption, authorized route access, and `429` throttling with `Retry-After: 60` on request `#61`.
* **Trade-offs:** In-memory rate-limit storage (`memory://`) scopes counters to a single container process; scaling horizontally across multiple replicas in the future will require switching `storage_uri` to a shared Redis instance.
