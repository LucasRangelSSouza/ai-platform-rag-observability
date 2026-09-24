# ADR 0001: Require evidence before answering

## Context

A useful RAG demonstration must show what supports an answer and what happens when retrieval cannot support one.

## Decision

The reference returns cited answers only when the fixture evidence is sufficient; otherwise it abstains. Its local trace stores minimized metadata and excludes raw questions or answers.

## Consequences

The demo is intentionally narrower than a general chatbot. It makes unsupported-answer and data-minimization behavior testable.

## Alternatives considered

Returning fluent answers for every request would make the interface appear more capable while undermining the claimed grounding boundary.
