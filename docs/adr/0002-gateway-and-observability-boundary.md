# ADR 0002: Keep the gateway and trace export behind small in-repo clients

## Context

Case 5 names 9Router as the model gateway and Langfuse as the observability layer. Both are external services with their own accounts, credentials, and release cycles. The repository must still run its quick start, tests, and CI with no account, no provider key, and no network.

## Decision

The repository talks to both services over their public HTTP contracts through two small stdlib clients.

`rag_platform/gateway.py` speaks the OpenAI-compatible `POST /chat/completions` contract that 9Router exposes. It owns the routing policy: ordered routes, retry with exponential backoff on HTTP 408, 429, 5xx, timeouts, and connection errors, a skip to the next route on 401, 403, and 404, and an immediate stop on any other 4xx or a malformed body. It reads the route key from an environment variable at call time and attributes tokens and cost per call from a JSON price table. Provider OAuth connections stay inside the gateway deployment; this repository never sees them.

`rag_platform/observability.py` builds a Langfuse-shaped trace (trace, retrieval span, generation nested under the span, scores) and exports it through `POST /api/public/ingestion` with basic auth read from `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` at export time. Every exporter receives a `Trace` object and calls `redact` itself, so no export path skips redaction. The default mode exports nothing.

The default generator is extractive and deterministic. The optional gateway generator may cite only chunk ids that retrieval returned; the service abstains when the model output cites none of them.

A trace export failure is counted and logged by exception type only, and the answer is still returned.

## Consequences

Tests exercise both contracts against fake HTTP servers bound to 127.0.0.1 inside the test process. That proves the client behavior this repository controls. It does not prove compatibility with a specific 9Router or Langfuse release, which needs a run against a pinned instance and a dated evidence record.

The Langfuse field mapping (`usageDetails`, `costDetails`, `promptName`, `promptVersion`) follows the public ingestion API as documented at the time of writing and must be re-checked against the pinned Langfuse version before a live export is claimed.

## Alternatives considered

The official SDKs would track upstream changes automatically, but they add dependencies, background flush threads, and their own retry behavior, which would make the redaction and routing rules harder to test in isolation. Vendoring the forks' source would couple this repository to their build and licensing; the spec asks for pinned images or APIs instead.
