# Public release gates

**Current policy:** The repository must not receive private FIRBO source snapshots until approval of a clean import. This document is guidance, not proof of scan completion.

1. Confirm source ownership and third-party license attribution for every imported path.
2. Make a clean filesystem snapshot, **not** a Git history mirror of the private repository.
3. Exclude user memory, conversations, agent credentials, browser sessions, SSH material, database exports, customer data, production configuration and logs.
4. Replace production domains, infrastructure identifiers, tokens and private endpoint values with safe examples.
5. Run a secret scan against source and all commits, dependency license audit, and code review. Treat scan results as necessary, not sufficient, for safe publication.
6. Run CI with imports enabled only after the vetted snapshot is added in a PR. Independently test startup, authorization and tenant boundaries.
7. Review the entire PR diff and confirm upstream notices before any public merge or release tag.

## Architecture invariants

- FIRBO owns CEO, orchestration, scopes, memory, approvals, task/audit records and result verification.
- OmniRoute is a model/provider routing service, not a second CEO or user-memory authority.
- OpenJarvis is a runtime dependency, not a second business authority.
- The private production repository and infrastructure remain untouched.

## Known gap

The initial monorepo currently uses pinned submodules in `packages/` and a minimal API bridge; it is not a vetted import of the private FIRBO app. The original issue proposed root-level FIRBO source and an OmniRoute subtree under `services/omniroute/`. Any layout change requires a dedicated migration PR with relative-path checks.
