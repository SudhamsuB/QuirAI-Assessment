import asyncio
import sqlite3
import pytest
from pydantic import ValidationError
from model_router import reserve_tokens, setup_db, estimate_tokens
from stream_guardrail import redact_fragments
from security_gateway import get_role

@pytest.mark.asyncio
async def test_pii_across_chunks():
    async def fragments():
        for x in ["contact alice@exam", "ple.org, SSN 123-", "45-6789, card 4111 1111 1111 ", "1111. okay"]:
            yield x
    result = ''.join([x async for x in redact_fragments(fragments())])
    assert 'alice@exam' not in result
    assert '123-45-6789' not in result
    assert '4111 1111 1111 1111' not in result
    assert result.count('[REDACTED]') == 3

@pytest.mark.asyncio
async def test_stream_is_bounded():
    async def fragments():
        for _ in range(500):
            yield 'ordinary response. '
    emitted = [x async for x in redact_fragments(fragments())]
    assert ''.join(emitted) == 'ordinary response. ' * 500
    assert len(emitted) > 50

def test_rate_limit_and_expiry(tmp_path):
    path = str(tmp_path / 'limits.db')
    setup_db(path)
    assert reserve_tokens('tenant1', 49_999, path=path, now=1000)
    assert not reserve_tokens('tenant1', 2, path=path, now=1001)
    assert reserve_tokens('tenant2', 50_000, path=path, now=1001)
    assert reserve_tokens('tenant1', 50_000, path=path, now=1060)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM reservations WHERE tenant=?', ('tenant1',)).fetchone()[0] == 1

def test_rate_token_estimation():
    assert estimate_tokens({'prompt': 'hello', 'max_tokens': 10}) == 15
    with pytest.raises(ValueError):
        estimate_tokens({'prompt': 'x', 'max_tokens': True})

def test_roles():
    assert get_role('Bearer local-admin-change-me') == 'admin'
    assert get_role('Bearer local-viewer-change-me') == 'viewer'
    assert get_role('Bearer attacker') is None
    assert get_role(None) is None


def test_simultaneous_reservations_are_atomic(tmp_path):
    """A SQLite BEGIN IMMEDIATE transaction prevents quota oversubscription."""
    from concurrent.futures import ThreadPoolExecutor
    path = str(tmp_path / 'concurrent.sqlite3')
    setup_db(path)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: reserve_tokens('same-tenant', 10_000, path=path, now=100), range(10)))
    assert sum(results) == 5
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT SUM(tokens) FROM reservations').fetchone()[0] == 50_000
