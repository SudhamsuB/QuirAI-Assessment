"""Task 2: authenticated JSON-RPC 2.0 MCP HTTP gateway.

This is a JSON request/response reverse proxy for the assessment, not a full
MCP Streamable HTTP session transport implementation.
"""
import hmac
import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="MCP Security Gateway", version="1.0")
DOWNSTREAM = os.getenv("MCP_DOWNSTREAM", "http://127.0.0.1:9001/mcp")
DEMO_ADMIN = os.getenv("DEMO_ADMIN_TOKEN", "local-admin-change-me")
DEMO_VIEWER = os.getenv("DEMO_VIEWER_TOKEN", "local-viewer-change-me")


def get_role(header: str | None) -> str | None:
    """Constant-time lookup of DEMO secrets. Never trust a client-supplied role."""
    if not header or not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):]
    if not token:
        return None
    if hmac.compare_digest(token, DEMO_ADMIN):
        return "admin"
    if hmac.compare_digest(token, DEMO_VIEWER):
        return "viewer"
    return None


def rpc_error(request_id, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


@app.get("/health")
def health():
    return {"status": "ok", "service": "mcp-security-gateway"}


@app.post("/mcp")
async def proxy(request: Request):
    # Reject batches explicitly: avoids bypass from inspecting only one element.
    raw = await request.body()
    if len(raw) > 1024 * 1024:
        return rpc_error(None, -32600, "Invalid Request")
    try:
        import json
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return rpc_error(None, -32700, "Parse error")
    if not isinstance(payload, dict):
        return rpc_error(None, -32600, "Invalid Request")
    request_id = payload.get("id")
    valid_id = (request_id is None or (isinstance(request_id, (str, int)) and not isinstance(request_id, bool)))
    if payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str) or not valid_id:
        return rpc_error(None, -32600, "Invalid Request")
    role = get_role(request.headers.get("authorization"))
    if role is None:
        return rpc_error(request_id, -32001, "Unauthorized Tool Call")
    if payload["method"] == "tools/call":
        params = payload.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return rpc_error(request_id, -32602, "Invalid params")
        if params["name"].startswith("admin_") and role != "admin":
            return rpc_error(request_id, -32001, "Unauthorized Tool Call")
    # Do not leak the inbound Authorization header to the downstream.
    headers = {"content-type": "application/json"}
    for key in ("mcp-protocol-version", "mcp-session-id", "accept"):
        if request.headers.get(key):
            headers[key] = request.headers[key]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(DOWNSTREAM, content=raw, headers=headers)
    except httpx.HTTPError:
        return rpc_error(request_id, -32002, "Downstream unavailable")
    passthrough = {key: response.headers[key] for key in ("mcp-session-id", "mcp-protocol-version") if key in response.headers}
    # Notifications have no id and should not generate a JSON-RPC response.
    if "id" not in payload and response.status_code < 400:
        return Response(status_code=202, headers=passthrough)
    return Response(content=response.content, status_code=response.status_code,
                    media_type=response.headers.get("content-type", "application/json"), headers=passthrough)
