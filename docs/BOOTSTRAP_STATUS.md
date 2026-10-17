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
