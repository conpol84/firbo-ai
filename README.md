# FIRBO AI

Open-source AI operating system for people and teams.

FIRBO combines a conversational CEO/orchestrator, specialist agents, tools, memory,
computer/app connectors, and the OmniRoute AI gateway in one developer-facing project.

> **Status:** alpha / active development. This repository is the clean open-source line.
> Production infrastructure, private user data, secrets, and customer configuration are
> intentionally excluded.

## Repository layout

- `apps/firbo/` — FIRBO product/application layer
- `packages/omniroute/` — pinned OmniRoute gateway source
- `docs/` — architecture, security, contribution and roadmap docs
- `examples/` — reproducible end-to-end examples

## Product goal

A user gives FIRBO a goal. FIRBO keeps the right context, delegates to the right
specialist or tool, executes within explicit permissions, verifies the result, saves
the evidence, and reports back without requiring step-by-step coaching.

## Architecture

```text
User / Voice / Channels
        |
    FIRBO CEO
        |
  Orchestrator
   /   |    \
Agents Tools  Durable jobs
        |
     OmniRoute
        |
Models / Providers / Local inference
```

FIRBO remains the authority for user/tenant scope, tasks, approvals, memory, results
and audit. OmniRoute is the model/provider gateway underneath the agents.

## Security

Never commit:
- API keys, tokens, cookies, browser sessions or OAuth refresh tokens
- production `.env` files
- database dumps or customer/user records
- private memories or conversations
- VPS/SSH credentials

See `SECURITY.md` before connecting a real account or deploying.

## Licensing

FIRBO includes modifications and integrations built on OpenJarvis (Apache-2.0).
OmniRoute components are distributed under their upstream MIT terms. Required notices
are retained in the corresponding source trees and `THIRD_PARTY_NOTICES.md`.

## Development

The first public milestone is **v0.1.0-alpha**: one reproducible end-to-end journey
from CEO request → execution → independently verified result → final response.

Detailed setup will be added with the source import.
