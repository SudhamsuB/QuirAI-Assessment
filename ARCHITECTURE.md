# Architecture and assessment design decisions

```text
MCP client --(JSON-RPC+Bearer)--> MCP security gateway :8001 --(JSON-RPC)--> mock downstream :9000/mcp
MCP client --(stdio)-----------> official MCP SDK customer server (`python -m mcp_server`)
Generation client --(HTTP)-----> streaming PII gateway :8002 --(SSE)--> mock LLM :9000/stream
Completion client --(HTTP)-----> rate/model router :8003 --+--> primary mock :9000/primary429
                                      |                 +--> backup mock :9000/complete
                                      +--> SQLite volume `/data/gateway_rate_limit.sqlite3`
```

## Threat and reliability model

- Authorization is enforced **before** upstream tool execution. The inbound Bearer token is checked against configured demo secrets in constant time; it is not forwarded to the downstream service. There is no trusted `role` header from the client.
- Task 2 is intentionally an **HTTP JSON-RPC forwarding subset**. A production MCP gateway must also correctly handle Streamable HTTP negotiation, GET/SSE, session setup and teardown, resume, cancellation, OAuth resource/audience protections, notifications, and batch-policy decisions. Batches are rejected to avoid missing protected calls.
- MCP tools strictly validate input types, field lengths, numeric bounds, NaN/Infinity and unknown fields. Actual refunds **never occur**. Production refunds require scoped service authorization, confirmation, idempotency, storage, audit and real payment integration.
- Stream redaction reconstructs `delta` strings before inspection. A 320-character look-behind protects bounded-length regex matches spanning provider SSE chunks. Larger or obfuscated identifiers may escape detection. This approach trades some TTFT for no full-response buffering. This is a demonstration guardrail, not a guarantee that all PII is caught.
- Each token reservation runs inside one `BEGIN IMMEDIATE` SQLite transaction. A unique reservation row is inserted only when a tenant is below the budget. Rows older than 60 seconds are removed transactionally. One `requests/sec` count is **not** sufficient for token-based rate limiting.
- The conservative prompt token estimate is UTF-8 bytes (a safe overestimate for common UTF-8 tokenizers) plus maximum output tokens. It is **not** exact model token accounting. Replace with a provider/model-specific tokenizer for real billing and reconcile actual output usage. Reserved tokens are not refunded on request failure, a deliberate fail-closed quota policy.
- Fallback is triggered on **primary HTTP 429**, connection/network failure or timeout; primary 5xx returns an upstream gateway error rather than silently triggering fallover. Backup is attempted once with its own 3-second timeout. Timeouts can consume up to 3 seconds per attempt. A production gateway should also adopt idempotency/deduplication safeguards and circuit breakers.
- All downstream errors presented to clients use sanitized messages. Never expose raw tracebacks, upstream credentials or raw upstream error bodies.

## Standards nuance

The assessment specifically requires invalid tool formats to return JSON-RPC `-32602`; this is how Task 1 is implemented. Newer MCP guidance separates **malformed method/request arguments** (JSON-RPC protocol errors) from **valid tool invocations with invalid business inputs** (`CallToolResult` with `isError: true`). For maximum assessment adherence this project intentionally maps Pydantic argument validation to `-32602`. If the reviewer requests strict conformance to newer tool failure guidance, change that validation catch to return `CallToolResult(..., is_error=True)` while preserving `-32602` for malformed protocol requests.

## Verification matrix

| Test | Required property | Test location |
|---|---|---|
| Valid and invalid tool input | Pydantic schema, extra fields, positive finite amount | `test_mcp_validation.py` |
| Real MCP stdio | initialize/list/call, stdout protocol isolation | `mcp_stdio_check.py` (SDK required) |
| Denied admin tool | JSON-RPC `-32001`, no downstream request | `test_http_endpoints.py` |
| Allowed admin/list requests | Exact forwarding | `test_http_endpoints.py` |
| Split email/SSN/card | Three redactions in streaming output | `test_components.py`, `test_http_endpoints.py` |
| Bounded memory | No full response accumulation | `test_components.py` |
| Sliding window and tenants | Atomic quotas, expiry, isolation | `test_components.py` |
| 429/timeout | One secondary attempt | `test_http_endpoints.py` |
| No raw upstream errors | Sanitized gateway error | `test_http_endpoints.py` |
| Live HTTP demo | Four independently running HTTP services | `demo.py` |

## Production changes before real traffic

Integrate OAuth2 or verified JWT API keys; enforce per-tool scopes as well as role; lock down transport and egress using TLS and private service identities; adopt a production MCP Streamable HTTP gateway; use real provider tokenization; reconcile model usage and quota reservations; add durable audit logs with data minimization; use provider-recommended SSE decoders, DLP scanners, telemetry and load testing. Run no real financial operations using this mock server.
