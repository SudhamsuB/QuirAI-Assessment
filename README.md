# AI Field Developer / AI Solutions Engineer — Complete Assessment Project

**Four runnable Python services, mock backends, SQLite, automated tests, Docker Compose, and demo scripts.** Supports Python 3.11+.

> This is a **local assessment/demo**, not a production security gateway. No paid LLM credentials, cloud account, or real customer/payment data are required.

**FLAT-FILE EDITION:** All Python source files and tests are at the repository root, so you can select and upload all files in one batch using GitHub’s website. GitHub Actions is omitted because workflows must reside in `.github/workflows/`; run the test commands below instead.

## What is included

| Task | Module | Major requirements |
|---|---|---|
| 1. Custom MCP Server | `mcp_server.py` | Official `mcp` Python SDK v2, Pydantic strict schemas, stdio and stderr-only logs, JSON-RPC `-32602` for invalid args |
| 2. MCP Security Proxy | `security_gateway.py` | Bearer role lookup, `tools/list` transparent forwarding, block `admin_*` for viewers with `-32001` before forwarding |
| 3. Streaming PII Guardrail | `stream_guardrail.py` | HTTP SSE proxy, email/SSN/credit-card redaction across partial deltas, bounded state |
| 4. Rate Limit + Failover | `model_router.py` | SQLite 50,000-token/tenant/minute sliding window, `BEGIN IMMEDIATE` concurrency protection, 429/3-second primary timeout -> backup, sanitized errors |

## Quick start — Docker Compose (simplest full HTTP demo)

Install Docker with Docker Compose. From the extracted project directory:

```bash
docker compose up --build -d
python demo.py
```

Expected output includes `PASS: Viewer denied administrative tool`, `PASS: Stream replaced fragmented email, SSN, and credit card`, `PASS: 429 triggers backup LLM`, and `ALL HTTP DEMOS PASSED`.

Endpoints: mock `http://127.0.0.1:9000`, MCP gateway `:8001/mcp`, stream gateway `:8002/generate`, router `:8003/complete`. The SQLite DB lives in the Docker named volume `rate-data`. These ports bind to loopback only.

Stop the project with `docker compose down`. To **delete SQLite data** too, use `docker compose down -v`.

Task 1 uses stdio rather than HTTP, so verify it separately with the SDK-based test below.

## Python setup — Windows / macOS / Linux

```bash
python -m venv .venv
```

macOS/Linux: `source .venv/bin/activate`  
Windows PowerShell: `.venv\Scripts\Activate.ps1` (or CMD: `.venv\Scripts\activate.bat`)

Then:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
```

### Task 1: official MCP stdio server

In the repository root:

```bash
python mcp_stdio_check.py
# Or start the server directly (designed for an MCP client; no human-readable stdout):
python -m mcp_server
```

An MCP-compatible client may use command `python`, args `["-m", "mcp_server"]`, with the repository as working directory. All application logs go to **stderr**, not stdout. `get_customer_record` takes `{"customer_id":"CUST-00001"}`. `trigger_refund` takes `{"customer_id":"CUST-00001","amount":10.5,"reason":"Duplicate payment"}`. A valid customer is `CUST-` followed by precisely five digits. Unknown customer record returns `status: not_found`; refunds are simulated.

The strict Pydantic tool schemas reject unknown keys, incorrect ID formats, non-positive/nonfinite amounts, and reasons under ten characters. Invalid tool parameters are mapped to JSON-RPC `-32602` as explicitly requested. **The MCP protocol's newer distinction between protocol errors and tool execution errors is documented in `ARCHITECTURE.md`.**

### Tasks 2–4 without Docker

Launch the following commands in **four different terminal windows** from the project root:

```bash
uvicorn mock_provider:app --port 9000
```

```bash
# macOS/Linux; on PowerShell use $env:MCP_DOWNSTREAM='http://127.0.0.1:9000/mcp'
MCP_DOWNSTREAM=http://127.0.0.1:9000/mcp uvicorn security_gateway:app --port 8001
```

```bash
STREAM_PROVIDER_URL=http://127.0.0.1:9000/stream uvicorn stream_guardrail:app --port 8002
```

```bash
PRIMARY_LLM_URL=http://127.0.0.1:9000/primary429 SECONDARY_LLM_URL=http://127.0.0.1:9000/complete RATE_DB_PATH=./gateway_rate_limit.sqlite3 uvicorn model_router:app --port 8003
```

On Windows PowerShell, assign all variables with `$env:NAME='value'` before `uvicorn`. Then run `python demo.py` in a fifth window.

## Individual curl examples

**Task 2:** viewer denied admin call (no downstream invocation):

```bash
curl -i http://127.0.0.1:8001/mcp -H 'Authorization: Bearer local-viewer-change-me' -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"admin_reset_key","arguments":{}}}'
```

Change token to `local-admin-change-me` to authorize. For a viewer `tools/list`, send `{"jsonrpc":"2.0","id":2,"method":"tools/list"}`. To check that a forbidden call was never forwarded: `curl http://127.0.0.1:9000/mock/requests`.

**Task 3:** streaming SSE, three sensitive strings split over upstream events:

```bash
curl -N http://127.0.0.1:8002/generate -H 'Content-Type: application/json' -d '{"prompt":"hello"}'
```

Expected result includes **three** `[REDACTED]` strings and `data: [DONE]`.

**Task 4:** primary 429 -> backup success and SQLite quota reservation:

```bash
curl -i http://127.0.0.1:8003/complete -H 'X-Tenant-Key: demo-tenant' -H 'Content-Type: application/json' -d '{"prompt":"Hello","max_tokens":200}'
```

For timeout demonstration replace `PRIMARY_LLM_URL` with `http://mock:9000/slow` (Docker) or `http://127.0.0.1:9000/slow` (local), restart the router, and retry. The primary call has a **3-second wall-clock deadline** (not merely a per-read timeout). To exceed quota, use sufficiently large prompts / `max_tokens` within the 60-second window.

## Tests, structure and explanation

```bash
python -m pytest -v
```

`test_components.py` verifies partial SSE redaction, bounded streaming, limit expiry, tenant separation and authorization roles. `test_http_endpoints.py` performs ASGI integration tests with mocked provider responses; no network needed. `test_mcp_validation.py` verifies the official MCP-connected model validation and is skipped only when `mcp` is missing. `mcp_stdio_check.py` uses the official MCP SDK v2 client/server over stdio and **requires the MCP SDK**. `demo.py` exercises all three running HTTP gateways.

The project includes `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`, and `ARCHITECTURE.md` with diagrams, security assumptions, tradeoffs, a test matrix, and discussion points.

## Honest limitations

- The module uses the SDK's **v2 low-level constructor API**. The official `mcp` package could not be downloaded in the author's build environment; Task 1 end-to-end SDK checks must run after installing dependencies. The other HTTP module tests were run locally.
- Bearer-to-role demo secrets and `X-Tenant-Key` are local stubs, **not real authenticated identity**.
- Task 2 is HTTP/JSON-RPC forwarding, not a full MCP Streamable HTTP session gateway.
- PII detection is a regular-expression proof of concept with a fixed look-behind window, not complete DLP coverage. A bounded hold increases Time To First Token and long/unusual PII can evade regex detection.
- The reservation budget uses an intentionally conservative UTF-8 bytes-per-prompt estimate, not an exact tokenizer; SQLite is suitable for modest deployments, not a horizontally scaled global quota system.
- Mock downstreams do not contact real LLMs or payment processors; no refunds occur.

For model transport documentation see [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) and [MCP Tool Specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

## GitHub assessment submission

This project is ready to upload as source files to a public GitHub repository. Follow **[SUBMISSION_CHECKLIST.md](SUBMISSION_CHECKLIST.md)** for a detailed upload walkthrough, final verification checklist and a short submission email. **[SECURITY.md](SECURITY.md)** explains demo credentials and production security limitations.

**Validation note (2026-11-05):** The HTTP gateway test suite passed locally (12 passed). This environment does not have the official MCP SDK or Docker installed, so the updated SDK v2 stdio test and Docker demo must be run on a machine or CI runner with those dependencies. Run the MCP stdio checker on your machine after installing dependencies.
