"""Task 3: bounded-lookbehind redaction across arbitrary response chunks.

Demo provider uses text event-stream with OpenAI-style data payloads.
The client receives a clean stream (text/event-stream with JSON `delta`).
"""
import json
import os
import re
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

app = FastAPI(title="Streaming PII gateway")
UPSTREAM = os.getenv("STREAM_PROVIDER_URL", "http://127.0.0.1:9002/stream")
# Limits are intentional; see README for the long-identifier tradeoff.
EMAIL = r"(?<![\w.+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,20}(?![\w-])"
SSN = r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"
CC = r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"
PII = re.compile(f"(?:{EMAIL})|(?:{SSN})|(?:{CC})")
HOLD = 320

def redact(text: str) -> str:
    return PII.sub("[REDACTED]", text)

async def redact_fragments(fragments):
    """Memory O(HOLD + input-fragment-size), independent of total output."""
    pending = ""
    async for chunk in fragments:
        # Chunk splitting bounds worst-case provider delta sizes.
        for i in range(0, len(chunk), 1024):
            pending += chunk[i:i + 1024]
            if len(pending) <= HOLD:
                continue
            cutoff = len(pending) - HOLD
            # Keep complete matches crossing the safe emission boundary.
            for match in PII.finditer(pending):
                if match.start() < cutoff < match.end():
                    cutoff = match.start()
                    break
            if cutoff > 0:
                yield redact(pending[:cutoff])
                pending = pending[cutoff:]
    if pending:
        yield redact(pending)

def sse_delta(text: str) -> str:
    return "data: " + json.dumps({"delta": text}) + "\n\n"

@app.post("/generate")
async def generate(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("prompt"), str) or not body["prompt"].strip():
            raise ValueError("Invalid request")
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"error": {"code": "INVALID_REQUEST", "message": "A nonempty prompt is required"}})

    async def upstream_fragments():
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=None)) as client:
            async with client.stream("POST", UPSTREAM, json=body, headers={"accept": "text/event-stream"}) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                        delta = event.get("delta")
                        if delta is None:
                            choices = event.get("choices") or []
                            delta = (choices[0].get("delta") or {}).get("content") if choices else None
                        if isinstance(delta, str):
                            yield delta
                    except (ValueError, TypeError, AttributeError, IndexError):
                        # Drop malformed provider event, log server-side in real deployment.
                        continue
    async def output():
        try:
            async for clean in redact_fragments(upstream_fragments()):
                if clean:
                    yield sse_delta(clean)
            yield "data: [DONE]\n\n"
        except (httpx.HTTPError, httpx.TimeoutException):
            yield "event: error\ndata: " + json.dumps({"error": {"code": "UPSTREAM_FAILURE", "message": "Generation unavailable"}}) + "\n\n"
    return StreamingResponse(output(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
