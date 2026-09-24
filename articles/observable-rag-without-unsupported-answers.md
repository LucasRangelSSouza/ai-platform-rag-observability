# Observable RAG without unsupported answers

**Versioned reference:** [v0.1.0](https://github.com/LucasRangelSSouza/ai-platform-rag-observability/tree/v0.1.0)

A retrieval system needs a visible response boundary before it needs a more elaborate prompt. This reference starts with three outcomes. It answers only when an approved corpus passage supplies lexical evidence, abstains when no passage matches, and refuses requests that contain tested prompt-injection patterns.

The retrieval result is part of the response contract. An answered result carries the identifiers and scores of the passages that supplied evidence. The fixture makes this behavior deterministic, which matters for regression tests: a new ranking or model adapter should not silently remove citations from an answer path.

Abstention is equally important. The initial implementation treated a common English word as enough retrieval evidence and answered an unrelated weather question. The failing test exposed that flaw. The corrected tokenizer removes common stopwords before it calculates overlap, and the same test now verifies an abstention instead of an unsupported answer. The repository retains that sequence in its public commit and CI history.

The trace artifact records a stable question-derived trace ID, outcome, citation count, gateway label, and safety reason. It does not carry hidden prompts, raw credentials, or provider configuration. A deployment can forward a redacted version of that artifact to Langfuse and route approved model calls through 9Router, but those integrations remain external and optional.

This small system does not establish retrieval quality for a production corpus. It demonstrates a testable contract: supported answers are cited, unsupported questions abstain, and known hostile phrasing refuses instead of becoming an instruction.
