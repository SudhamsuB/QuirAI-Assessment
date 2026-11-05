"""Smoke checks against running Docker Compose services; stdlib only.

Run after `docker compose up --build -d`:
    python scripts/demo.py
"""
import json
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def call(url, payload=None, token=None, method='POST'):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if url.endswith('/complete'):
        headers['X-Tenant-Key'] = 'demo-tenant'
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(req, timeout=15) as response:
            raw = response.read().decode()
            return response.status, raw
    except HTTPError as error:
        return error.code, error.read().decode()


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def main():
    print('Checking mock server and gateways on localhost ...')
    status, body = call('http://127.0.0.1:9000/mock/requests', method='GET')
    check(status == 200, 'Mock provider reachable')
    call('http://127.0.0.1:9000/mock/requests', method='DELETE')
    admin = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'admin_reset_key', 'arguments': {}}}
    status, body = call('http://127.0.0.1:8001/mcp', admin, 'local-viewer-change-me')
    check(json.loads(body)['error']['code'] == -32001, 'Viewer denied administrative tool')
    _, seen = call('http://127.0.0.1:9000/mock/requests', method='GET')
    check(json.loads(seen)['count'] == 0, 'Denied tool never reached downstream')
    _, body = call('http://127.0.0.1:8001/mcp', admin, 'local-admin-change-me')
    check('result' in json.loads(body), 'Admin tool forwarded')
    tools = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}
    _, body = call('http://127.0.0.1:8001/mcp', tools, 'local-viewer-change-me')
    check(len(json.loads(body)['result']['tools']) > 0, 'tools/list forwarded')
    _, text = call('http://127.0.0.1:8002/generate', {'prompt': 'hello'})
    check(text.count('[REDACTED]') == 3 and 'alice@example.com' not in text and '123-45-6789' not in text,
          'Stream replaced fragmented email, SSN, and credit card')
    status, body = call('http://127.0.0.1:8003/complete', {'prompt': 'hello', 'max_tokens': 10})
    check(status == 200 and json.loads(body)['provider'] == 'mock-backup', '429 triggers backup LLM')
    print('\nALL HTTP DEMOS PASSED. Task 1 is a separate stdio MCP process.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('DEMO FAILED:', exc, file=sys.stderr)
        sys.exit(1)
