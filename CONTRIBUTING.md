# Contributing to FIRBO

Thanks for helping build FIRBO.

## Before coding

1. Read `docs/ARCHITECTURE.md` and `docs/ROADMAP.md`.
2. Do not add secrets or production data.
3. Open an issue for large architectural changes.
4. Keep OpenJarvis and OmniRoute as pinned dependencies unless an upgrade is intentional.

## Pull requests

A PR should state the problem, user-visible behavior, tests, permission/security impact, rollback path, and what remains incomplete.

We prefer small end-to-end improvements over large collections of unverified adapters.

## Definition of done

For agentic work, tests alone are not enough. Include a reproducible acceptance case showing request -> action -> verified result -> final response.
