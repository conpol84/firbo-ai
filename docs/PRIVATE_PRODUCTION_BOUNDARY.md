# Private production boundary

This public/open-source line is intentionally separated from the owner's private
production FIRBO repository and infrastructure.

## Never copy from production into this repository

- secrets or environment files
- customer/user rows, conversations or memories
- OAuth/browser sessions
- provider account exports
- VPS keys or host-specific credentials
- database backups
- private incident evidence containing personal data

## What may move from private production to open source

Only reviewed, generalized source changes that:

1. contain no private data or credentials,
2. are independently understandable,
3. preserve upstream licensing/attribution,
4. include tests or a reproducible acceptance case, and
5. do not depend on hidden production-only state.

Production may consume releases from this repository later, but the open-source project
must remain runnable without access to the owner's private systems.
