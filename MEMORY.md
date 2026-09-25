# Project memory

## Current state

- v0.2.0: ingestion/chunking, BM25+hybrid retrieval, guardrails, extractive + gateway generation (citation-contained), an OpenAI-compatible gateway client, Langfuse-shaped traces with mandatory redaction, a pinned education corpus adapter, a JSON API, and a Dockerfile/Compose. 118 unit tests pass.
- Education adapter pinned to `lucasrangelss/brazil-education-data-lake` v1, manifest SHA-256 `44f259602a688432dddbae6b0306a6957514a634d57d94a0abd3cff30f4b3506` (real, published — see [brazil-public-data-map](https://github.com/LucasRangelSSouza/brazil-public-data-map)).
- 2026-09-25 real-data run ([evidence](docs/evidence/v0.2.0-local-run-2026-09-25.md)): fixture recall@3/coverage/abstention all 1.0 (n=6); real education release (40 sampled municipalities) recall@3 0.988, citation coverage 0.938, abstention 1.0 (n=81+6). Docker image built; both Compose profiles (`fixture`, `education`) smoke-tested against the real release, including a citation carrying the dataset slug/version/manifest hash.
- Gateway and Langfuse clients are tested only against fake in-process HTTP servers ([ADR 0002](docs/adr/0002-gateway-and-observability-boundary.md)); no live 9Router/Langfuse instance has been run against.

## Decisions

- Citations can only reference chunk ids retrieval actually returned; a gateway-generated citation to an unretrieved or hallucinated id is dropped, not trusted.
- Traces redact the question (SHA-256 only) and drop passage/answer text by default; `--trace-include-content` opts in explicitly.
- The education corpus adapter verifies the full manifest (not just its hash) before reading any layer, and rejects unknown/person-level columns.

## Next verifiable task

Run the gateway and Langfuse clients against one pinned live instance of each (a dated evidence record, not a permanent dependency) and investigate the education citation-coverage gap (0.988 recall vs 0.938 coverage).

## Registry publish

A signed `v*` tag now runs a `release` CI job that builds and pushes an immutable, provenance-attested image to `ghcr.io/lucasrangelssouza/ai-platform-rag-observability` (both a semver tag and a `sha-<full-commit>` tag). After the first publish, GHCR packages default to private — the package visibility must be flipped to Public once, manually, in the package's own Settings page (Actions cannot do this with the default token). Until that one-time step happens, `distributed-agent-runtime-lab`'s public-demo profile cannot pull it and must keep using its documented fixture stand-in.
