# Project memory

The local CLI can append metadata-only JSONL traces with a question SHA-256 digest and citation document IDs. The local trace sink does not store raw prompts or answers. External 9Router and Langfuse integrations remain unconfigured boundaries, not completed deployments.

The local RAG proof retrieves from a synthetic corpus, returns citations, abstains on missing evidence, refuses simple injection patterns, and produces a trace artifact. Tests cover these three outcomes. 9Router and Langfuse are optional external integrations; no credentials or vendor setup belongs in the repository.
