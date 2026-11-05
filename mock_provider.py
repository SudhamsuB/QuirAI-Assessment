"""Deterministic mock upstreams for all three HTTP-facing components."""
import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse, Response

app = FastAPI(title="Assessment mock providers")
received_mcp = []


@app.get("/health")
def health():
    return {"status": "ok", "service": "mock-provider"}


@app.post("/stream")
async def stream(request: Request):
    async def events():
        for value in ["Hi alice@exa", "mple.com! Your SSN is 123-", "45-6789. Card: 4111 1111 1111 1111", " done."]:
            await asyncio.sleep(0.02)
            yield "data: " + json.dumps({"delta": value}) + "\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/complete")
async def complete(request: Request):
    body = await request.json()
    return {"provider": "mock-backup", "completion": "Successful completion", "received_prompt": body.get("prompt")}


@app.post("/primary429")
async def primary429():
    return JSONResponse(status_code=429, content={"error": "quota"})


@app.post("/primary500")
async def primary500():
    return JSONResponse(status_code=500, content={"internal": "upstream-secret-stack-trace"})


@app.post("/slow")
async def slow():
    await asyncio.sleep(5)
    return {"provider": "too-slow"}


@app.post("/mcp")
async def mcp(request: Request):
    payload = await request.json()
    received_mcp.append(payload)
    if "id" not in payload:
        return Response(status_code=202)
    if payload.get("method") == "tools/list":
        return {"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": [
            {"name": "get_customer_record", "inputSchema": {"type": "object"}},
            {"name": "admin_reset_key", "inputSchema": {"type": "object"}}
        ]}}
    if payload.get("method") == "tools/call":
        return {"jsonrpc": "2.0", "id": payload["id"], "result": {"content": [
            {"type": "text", "text": "Simulated downstream tool: " + payload["params"]["name"]}
        ]}}
    return {"jsonrpc": "2.0", "id": payload["id"], "result": {}}


@app.get("/mock/requests")
def requests_seen():
    return {"received": received_mcp, "count": len(received_mcp)}


@app.delete("/mock/requests")
def clear_requests():
    received_mcp.clear()
    return {"count": 0}
