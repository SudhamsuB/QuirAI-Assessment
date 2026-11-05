# Security notes

This project is a **local, educational assessment demo**, not production-grade infrastructure.

- Never replace the demo Bearer tokens with real access credentials in source control. Use environment variables or a secret store in a real deployment.
- The `X-Tenant-Key` identifier is an **unverified demo tenant identifier**, not authentication. A real system must verify API keys or JWT audience, issuer, expiry, and scopes before accounting or routing.
- `admin_*` tool filtering is role-based policy demonstration only. A production policy should use allowlists, deny-by-default rules, and action/resource authorization.
- Credit-card redaction uses regex, not complete card validation or PCI-DSS compliance; identifiers split across boundaries are detected within a bounded look-behind only.
- Demo refunds never transfer money. Any production refund implementation must add authentication, approvals, idempotency, audit, and transaction controls.
- Never publicly expose the mock endpoints; Docker Compose binds host ports only to `127.0.0.1`.
- No real customer details or external LLM API keys are required.

For deployment, use TLS, authenticated service identities, secret management, audit logging, input/output limits, and robust operational controls.
