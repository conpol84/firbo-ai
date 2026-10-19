# FIRBO AI

Open-source AI operating system for people and teams.

FIRBO combines a conversational CEO/orchestrator, specialist agents, tools, memory,
computer/app connectors, **OpenJarvis**, and **OmniRoute** in one developer-facing project.

> **Status:** alpha / active development. This repository is the clean open-source line.
> Production infrastructure, private user data, secrets, and customer configuration are
> intentionally excluded.

**Production source of truth:** [One FIRBO Master Plan](https://github.com/conpol84/Firbo-production/blob/main/docs/FIRBO_MASTER_PLAN_CURRENT.md) and [live checkpoint #163](https://github.com/conpol84/Firbo-production/issues/163). This repo supplies runtime/tools only; do not create a second CEO, website, tasks or memory.

## Clone everything

```bash
git clone --recurse-submodules https://github.com/conpol84/firbo-ai.git
cd firbo-ai
bash scripts/bootstrap.sh
```

A recursive clone includes the pinned OpenJarvis runtime and OmniRoute gateway under
`packages/`. You do not need to discover or assemble separate repositories manually.

## Repository layout

- `services/orchestrator/` — FIRBO-owned orchestration/API boundary
- `packages/openjarvis/` — pinned OpenJarvis runtime
- `packages/omniroute/` — pinned OmniRoute gateway
- `docs/` — architecture, security, contribution and roadmap docs
- `scripts/` — local bootstrap helpers

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
   \   |    /
 Result verifier
        |
     Final answer
        |
   Notification

Model calls: FIRBO -> OmniRoute -> providers/models
Agent runtime: FIRBO -> OpenJarvis -> tools/skills/channels
```

FIRBO remains the authority for user/tenant scope, goals, tasks, approvals, memory,
results and audit. OmniRoute is the model/provider gateway. OpenJarvis supplies reusable
agent/runtime capabilities. Neither dependency becomes a second FIRBO CEO.

## One-command developer start

Prerequisites: Git, Python 3, uv, Node.js/npm, and curl.

```bash
git clone --recurse-submodules https://github.com/conpol84/firbo-ai.git
cd firbo-ai
cp .env.example .env
make up
```

`make up` initializes the pinned submodules, installs missing local dependencies, and starts OmniRoute, OpenJarvis, and the FIRBO orchestrator on loopback. Then use:

```bash
make doctor
make down
```

Runtime logs and PID files stay under `.firbo/` and are ignored by Git.

## Quick developer bridge

Copy `.env.example` to `.env`, start the pinned OmniRoute gateway using its own README,
then run the minimal FIRBO orchestrator:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r services/orchestrator/requirements.txt
uvicorn services.orchestrator.app:app --host 127.0.0.1 --port 8787
```

Health:

```bash
curl http://127.0.0.1:8787/health
```

The bridge intentionally starts small. The open-source roadmap grows it through
reproducible end-to-end journeys instead of claiming hundreds of unverified capabilities.

## Security

Never commit API keys, tokens, cookies, production `.env` files, database dumps,
private memories/conversations, browser sessions, customer data, or VPS credentials.
See `SECURITY.md`.

## Licensing

FIRBO-specific code is Apache-2.0 unless a file states otherwise.

- OpenJarvis: Apache-2.0
- OmniRoute: MIT

The pinned source trees retain their own license and notice files. See
`THIRD_PARTY_NOTICES.md`.

## Roadmap

See `docs/ROADMAP.md`. The first public milestone is **v0.1.0-alpha**: one reproducible
end-to-end journey from CEO request → execution → independently verified result → final
response.
