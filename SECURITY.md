# Security policy

FIRBO can connect AI models to files, computers, business apps and private memory. Treat every integration as privileged.

## Never commit

- API keys, tokens, cookies, sessions, OAuth refresh tokens
- production .env files
- database dumps or customer/user records
- private memories or conversations
- SSH/VPS credentials
- provider account exports

## Defaults

- least privilege
- tenant/user scoping at every data boundary
- human approval for external/destructive actions
- bounded retries and budgets
- idempotency for side effects
- explicit cancellation
- independent result verification
- auditable request/task identifiers

Report vulnerabilities privately to the repository owner rather than opening a public issue containing exploit details or credentials.
