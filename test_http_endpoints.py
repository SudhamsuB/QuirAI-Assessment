"""No external services required: mocked HTTP transport, real FastAPI endpoints."""
import asyncio
import json
import sqlite3
import httpx
import pytest
import security_gateway as security, model_router as router
import stream_guardrail as stream


@pytest.mark.asyncio
async def test_security_authorization_and_forwarding(monkeypatch):
    seen = []

    def handler(req):
        seen.append(req)
        payload = json.loads(req.content)
        assert "authorization" not in req.headers
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload.get("id"), "result": {"ok": True}})

    original_client = httpx.AsyncClient
    def downstream_client(*args, **kwargs):
        return original_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(security.httpx, "AsyncClient", downstream_client)
    # use the original client to avoid the mocked downstream transport at gateway edge
    async with original_client(transport=httpx.ASGITransport(app=security.app), base_url="http://gateway") as client:
        def payload(method, name=None):
            p = {"jsonrpc": "2.0", "id": 10, "method": method}
            if name is not None:
                p["params"] = {"name": name, "arguments": {}}
            return p
        viewer = {"authorization": "Bearer local-viewer-change-me"}
        admin = {"authorization": "Bearer local-admin-change-me"}
        r = await client.post("/mcp", json=payload("tools/call", "admin_reset_key"), headers=viewer)
        assert r.json()["error"]["code"] == -32001
        assert not seen
        r = await client.post("/mcp", json=payload("tools/list"), headers=viewer)
        assert r.json()["result"]["ok"] is True
        assert len(seen) == 1
        r = await client.post("/mcp", json=payload("tools/call", "admin_reset_key"), headers=admin)
        assert r.json()["result"]["ok"] is True
        assert len(seen) == 2
        r = await client.post("/mcp", json=payload("tools/call", "get_customer_record"))
        assert r.json()["error"]["code"] == -32001
        assert len(seen) == 2
        r = await client.post("/mcp", content="[{}]", headers={**viewer, "content-type": "application/json"})
        assert r.json()["error"]["code"] == -32600
        assert len(seen) == 2
        r = await client.post("/mcp", content="{invalid", headers={**viewer, "content-type": "application/json"})
        assert r.json()["error"]["code"] == -32700
        assert len(seen) == 2


@pytest.mark.asyncio
async def test_model_router_failover_and_error_sanitization(monkeypatch, tmp_path):
    path = str(tmp_path / "rate.sqlite3")
    router.setup_db(path)
    original_reserve = router.reserve_tokens
    monkeypatch.setattr(router, "reserve_tokens", lambda tenant, tokens: original_reserve(tenant, tokens, path=path))
    seen = []
    def mock_provider(req):
        seen.append(req.url.path)
        if req.url.path == "/primary":
            return httpx.Response(429, json={"secret": "do-not-expose"})
        if req.url.path == "/backup":
            return httpx.Response(200, json={"provider": "backup", "content": "OK"})
        return httpx.Response(503, json={"stack": "internal secret"})
    original_client = httpx.AsyncClient
    def upstream_client(*args, **kwargs):
        return original_client(transport=httpx.MockTransport(mock_provider), **kwargs)
    monkeypatch.setattr(router.httpx, "AsyncClient", upstream_client)
    monkeypatch.setattr(router, "PRIMARY", "http://upstream/primary")
    monkeypatch.setattr(router, "SECONDARY", "http://upstream/backup")
    async with original_client(transport=httpx.ASGITransport(app=router.app), base_url="http://router") as client:
        r = await client.post("/complete", json={"prompt": "hello", "max_tokens": 50}, headers={"x-tenant-key": "t1"})
        assert r.status_code == 200 and r.json()["provider"] == "backup"
        assert seen == ["/primary", "/backup"]
        r = await client.post("/complete", json={"prompt": "hello", "max_tokens": 50})
        assert r.status_code == 401
        r = await client.post("/complete", json={"prompt": "hello", "max_tokens": 8192}, headers={"x-tenant-key": "t2"})
        assert r.status_code == 200
        r = await client.post("/complete", json={"prompt": "x" * 50001, "max_tokens": 1}, headers={"x-tenant-key": "t2"})
        assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
        assert len(seen) == 4
        monkeypatch.setattr(router, "PRIMARY", "http://upstream/failed")
        r = await client.post("/complete", json={"prompt": "again"}, headers={"x-tenant-key": "t3"})
        assert r.status_code == 502 and "internal secret" not in r.text
        assert "stack" not in r.text


@pytest.mark.asyncio
async def test_model_router_timeout_fallback(monkeypatch, tmp_path):
    router.setup_db(str(tmp_path / "timeout.sqlite"))
    real_reserve = router.reserve_tokens
    monkeypatch.setattr(router, "reserve_tokens", lambda tenant, tokens: real_reserve(tenant, tokens, path=str(tmp_path / "timeout.sqlite")))
    calls = []
    async def fake_attempt(client, url, body, timeout):
        calls.append((url, timeout))
        if url == "primary":
            raise httpx.ReadTimeout("private provider failure")
        return httpx.Response(200, json={"provider": "secondary"})
    monkeypatch.setattr(router, "attempt", fake_attempt)
    monkeypatch.setattr(router, "PRIMARY", "primary")
    monkeypatch.setattr(router, "SECONDARY", "secondary")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=router.app), base_url="http://router") as client:
        r = await client.post("/complete", json={"prompt": "hello"}, headers={"x-tenant-key": "tenant-timeout"})
    assert r.status_code == 200 and r.json()["provider"] == "secondary"
    assert calls == [("primary", 3.0), ("secondary", 3.0)]


@pytest.mark.asyncio
async def test_stream_http_redaction(monkeypatch):
    # A mocked SSE provider that fragments each secret across multiple deltas.
    raw_parts = ["Email alice@exa", "mple.com SSN 123-", "45-6789 card 4111 1111 ", "1111 1111! end"]
    async def events():
        for p in raw_parts:
            yield "data: " + json.dumps({"delta": p}) + "\n\n"
        yield "data: [DONE]\n\n"
    class FakeStreamingResponse:
        status_code = 200
        async def aiter_lines(self):
            async for part in events():
                for line in part.splitlines():
                    yield line
        def raise_for_status(self):
            pass
    class FakeStreamContext:
        async def __aenter__(self): return FakeStreamingResponse()
        async def __aexit__(self, *args): return False
    class FakeProviderClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def stream(self, *args, **kwargs): return FakeStreamContext()
    original_client = httpx.AsyncClient
    monkeypatch.setattr(stream.httpx, "AsyncClient", FakeProviderClient)
    async with original_client(transport=httpx.ASGITransport(app=stream.app), base_url="http://stream") as client:
        response = await client.post("/generate", json={"prompt": "test"})
    assert response.status_code == 200
    text = response.text
    assert text.count("[REDACTED]") == 3
    assert "alice@example.com" not in text
    assert "123-45-6789" not in text
    assert "4111 1111 1111 1111" not in text
    assert "data: [DONE]" in text


@pytest.mark.asyncio
async def test_stream_rejects_malformed_input():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=stream.app), base_url="http://stream") as client:
        for payload in ([], {}, {"prompt": 42}, {"prompt": "   "}):
            response = await client.post("/generate", json=payload)
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "INVALID_REQUEST"
        response = await client.post("/generate", content="invalid", headers={"content-type": "application/json"})
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_router_enforces_wall_clock_timeout():
    async def slow_post(*args, **kwargs):
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"provider": "too-late"})

    class FakeClient:
        post = slow_post

    with pytest.raises(TimeoutError):
        await router.attempt(FakeClient(), "http://example.test/complete", {"prompt": "test"}, 0.005)
