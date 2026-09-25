# Observable RAG without unsupported answers

**Versioned reference:** [v0.2.0](https://github.com/LucasRangelSSouza/ai-platform-rag-observability/tree/v0.2.0).

A retrieval system needs a visible response boundary before it needs a more elaborate prompt. This reference starts with three outcomes. It answers only when a retrieved passage covers at least 60% of the question's content terms, abstains otherwise, and refuses requests that contain tested prompt-injection patterns.

The retrieval result is part of the response contract. An answered result carries the identifiers and scores of the passages that supplied evidence. The fixture makes this behavior deterministic, which matters for regression tests: a new ranking or model adapter should not silently remove citations from an answer path.

Abstention is equally important. The initial implementation treated a common English word as enough retrieval evidence and answered an unrelated weather question. The failing test exposed that flaw. The corrected tokenizer removes common stopwords before it calculates overlap, and the same test now verifies an abstention instead of an unsupported answer. The repository retains that sequence in its public commit and CI history.

The trace records a random trace ID, a SHA-256 digest of the question, the outcome, the safety reason, a retrieval span, and a generation observation nested under it. Passage and answer text stay out of every export unless an operator sets an explicit flag. Since v0.2.0 the repository includes a Langfuse ingestion client and an OpenAI-compatible gateway client for 9Router, both tested only against fake local servers; a live run against either service has not been recorded.

This small system does not establish retrieval quality for a production corpus. It demonstrates a testable contract: supported answers are cited, unsupported questions abstain, and known hostile phrasing refuses instead of becoming an instruction.
