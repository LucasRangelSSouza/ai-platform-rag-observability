# Claim-to-evidence map

| Claim | Evidence | Status |
| --- | --- | --- |
| Answered fixture responses carry citations. | `tests/test_service.py::AnswerTests::test_answer_has_citations`. | Supported |
| Missing evidence abstains. | `tests/test_service.py::UnsupportedQueryTests`; CI run 35991123370 (v0.1.0). | Supported |
| Tested prompt injection patterns refuse, including width and zero-width variants. | `tests/test_service.py::PromptInjectionTests`. | Supported |
| A retrieved passage with injection phrasing is withheld from generation. | `test_poisoned_passage_is_quarantined_before_generation`. | Supported |
| A gateway answer that cites no retrieved chunk abstains. | `tests/test_observability.py::GatewayGeneratorTests`. | Supported (fake gateway only) |
| The gateway client retries 429/5xx/timeouts, falls back on auth errors, and stops on other 4xx. | `tests/test_gateway.py`. | Supported (fake gateway only) |
| Exported traces never contain the question text. | `tests/test_observability.py::RedactionTests`, `ExporterTests`. | Supported |
| The education adapter rejects unapproved versions, hash mismatches, unknown columns, and person-level fields. | `tests/test_education_corpus.py`. | Supported |
| Education v1 retrieval results on a 40-municipality sample: recall@3 0.988, citation coverage 0.938. | `docs/evidence/v0.2.0-local-run-2026-09-25.md`. | Supported for that sample and date |
| The service works with a live 9Router or Langfuse instance. | No live run recorded. | Not claimed |
| The project provides production safety coverage. | No production corpus or red-team benchmark exists. | Not claimed |
