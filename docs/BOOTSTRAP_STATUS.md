# Bootstrap status

## Completed

- Repository initialized on `main`.
- Apache-2.0 root license present.
- OpenJarvis and OmniRoute pinned as separate runtime dependencies.
- Minimal FIRBO orchestrator and smoke tests present.
- GitHub Actions CI enabled.
- Secret-scanning workflow enabled on pushes and pull requests.
- `.gitignore`, `.env.example`, `SECURITY.md`, `CONTRIBUTING.md`, and `CODE_OF_CONDUCT.md` present.
- Public-release gates documented.
- Private production Git history has not been copied.

## Source import boundary

The production application snapshot is not part of this public bootstrap. It must be reviewed in an isolated staging workflow before publication, including content review, licensing review, configuration sanitization, and automated scanning.

## Source baselines

- FIRBO baseline: `conpol84/javris-clone@89469864dc3975eadcbc433a72fcf0a9ef7173fa`
- OmniRoute baseline: `06742ac2c291ee9d680c7a50a03f7741a41063ec`

The production repository remains unchanged.

## FIRBO auxiliary intelligence worker

The paired Mac may act as an optional **Auxiliary Intelligence Worker**, never as a second CEO or replacement runtime.

Allowed roles:
- local lightweight inference / fallback models;
- memory/context compression and retrieval pre-processing;
- speech/VAD/audio pre-processing and local cache;
- device-local desktop/app actions;
- background embeddings, summarisation, indexing and low-cost reasoning;
- optional prefetching/warming to reduce perceived latency.

The canonical decision loop remains FIRBO/OpenJarvis with shared task, memory and audit state. Strong cloud models remain available for hard reasoning. The Mac must not create a second task system, second memory store, or divergent conversation history.

Target UX: short natural spoken turns, immediate acknowledgment, low latency, interruption/barge-in, persistent conversational context, and tool execution without repetitive permission prompts for low-risk reads.

