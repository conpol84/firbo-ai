# FIRBO architecture

FIRBO is one project with two pinned engines:

- **OpenJarvis** — agent/runtime primitives, local-first tools, skills and channels.
- **OmniRoute** — OpenAI-compatible model gateway, provider routing, fallback, quotas, MCP/A2A and model telemetry.

FIRBO owns the product contract: user/tenant identity, goals, memory policy, task state, approvals, budgets, tool permissions, result verification, receipts and notifications.

## Control flow

```text
voice / web / Telegram / apps
            |
        FIRBO CEO
            |
      goal orchestrator
       /      |       \
 specialist  tools   durable jobs
       \      |       /
        result verifier
            |
        final answer
            |
        notification

Model calls: FIRBO -> OmniRoute -> provider/model
Agent/runtime capabilities: FIRBO -> OpenJarvis -> skills/tools/channels
```

OpenJarvis and OmniRoute are dependencies, not competing CEOs. FIRBO remains the authority for goal completion and user permissions.

## Golden rule

A tool receipt is not automatically a successful user outcome. Every action must be checked against the original goal before FIRBO says "done".
