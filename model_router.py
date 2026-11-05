"""Task 4: atomic SQLite-backed token budget + resilient primary/backup router."""
import asyncio
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

@asynccontextmanager
async def lifespan(_app):
    await asyncio.to_thread(setup_db)
    yield


app = FastAPI(title="LLM Model Router", version="1.0", lifespan=lifespan)
DB_PATH = os.getenv("RATE_DB_PATH", "gateway_rate_limit.sqlite3")
PRIMARY = os.getenv("PRIMARY_LLM_URL", "http://127.0.0.1:9003/complete")
SECONDARY = os.getenv("SECONDARY_LLM_URL", "http://127.0.0.1:9004/complete")
CAP = 50_000
WINDOW = 60


def setup_db(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=10) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, tenant TEXT NOT NULL, ts REAL NOT NULL, tokens INTEGER NOT NULL CHECK(tokens > 0))")
        db.execute("CREATE INDEX IF NOT EXISTS ix_reservations_tenant_ts ON reservations(tenant, ts)")


def reserve_tokens(tenant: str, tokens: int, *, path=DB_PATH, now=None) -> bool:
    """Atomically reserve worst-case tokens; concurrently safe across SQLite connections."""
    if not tenant or isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
        raise ValueError("Invalid reservation")
    if tokens > CAP:
        return False
    now = time.time() if now is None else now
    with sqlite3.connect(path, timeout=10, isolation_level=None) as db:
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("DELETE FROM reservations WHERE ts <= ?", (now - WINDOW,))
            used = db.execute("SELECT COALESCE(SUM(tokens),0) FROM reservations WHERE tenant=? AND ts>?", (tenant, now - WINDOW)).fetchone()[0]
            if used + tokens > CAP:
                db.execute("COMMIT")
                return False
            db.execute("INSERT INTO reservations VALUES (?,?,?,?)", (str(uuid.uuid4()), tenant, now, tokens))
            db.execute("COMMIT")
            return True
        except Exception:
            db.execute("ROLLBACK")
            raise


def estimate_tokens(payload: dict) -> int:
    """Safe upper bound for UTF-8 BPE prompt tokens, plus max generated tokens.

    NOTE: conservative budget, not exact provider billing tokens. For a deployed
    router replace with each target model's actual tokenizer, and reconcile usage.
    """
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be a nonempty string")
    max_tokens = payload.get("max_tokens", 256)
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
        raise ValueError("max_tokens must be 1..8192")
    return len(prompt.encode("utf-8")) + max_tokens


def gateway_error(status: int, code: str, message: str):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


async def attempt(client: httpx.AsyncClient, url: str, body: dict, timeout: float):
    # A per-attempt timeout (not a total timeout) covers connect/write/read.
    # Enforce an actual wall-clock deadline across the entire HTTP call.
    # httpx's timeout alone is per-operation and may exceed the requested total.
    async with asyncio.timeout(timeout):
        return await client.post(url, json=body, timeout=httpx.Timeout(timeout))


@app.get("/health")
def health():
    return {"status": "ok", "service": "llm-model-router"}


@app.post("/complete")
async def complete(request: Request):
    tenant = request.headers.get("x-tenant-key")
    # Demonstration only: replace with verified API key -> tenant mapping.
    if not tenant or len(tenant) > 128:
        return gateway_error(401, "UNAUTHENTICATED", "Tenant credentials required")
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError()
        tokens = estimate_tokens(body)
    except (ValueError, TypeError, UnicodeDecodeError):
        return gateway_error(400, "INVALID_REQUEST", "Invalid completion request")
    try:
        allowed = await asyncio.to_thread(reserve_tokens, tenant, tokens)
    except (sqlite3.Error, OSError):
        return gateway_error(503, "RATE_LIMIT_UNAVAILABLE", "Gateway temporarily unavailable")
    if not allowed:
        return gateway_error(429, "RATE_LIMITED", "Tenant token budget exceeded")
    async with httpx.AsyncClient() as client:
        try:
            primary = await attempt(client, PRIMARY, body, 3.0)
            if primary.status_code != 429:
                if primary.is_success:
                    try:
                        return JSONResponse(primary.json())
                    except ValueError:
                        return gateway_error(502, "BAD_UPSTREAM", "Invalid model response")
                return gateway_error(502, "UPSTREAM_FAILURE", "Primary model unavailable")
        except (TimeoutError, httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
            pass
        try:
            backup = await attempt(client, SECONDARY, body, 3.0)
            if backup.is_success:
                try:
                    return JSONResponse(backup.json())
                except ValueError:
                    return gateway_error(502, "BAD_UPSTREAM", "Invalid model response")
            return gateway_error(502, "UPSTREAM_FAILURE", "Model providers unavailable")
        except (TimeoutError, httpx.HTTPError):
            return gateway_error(502, "UPSTREAM_FAILURE", "Model providers unavailable")
