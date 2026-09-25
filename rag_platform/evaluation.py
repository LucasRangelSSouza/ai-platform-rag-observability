"""Offline retrieval, citation, and abstention evaluation."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .ingestion import document_from_fixture
from .service import RagService, build_service


OUT_OF_SCOPE_QUESTIONS = (
    "What is the capital of France?",
    "Who won the 2022 World Cup?",
    "Write a poem about the ocean.",
    "How do I reset my email password?",
    "What is the weather forecast for tomorrow?",
    # Known hard case: every term except the invented place name matches the corpus.
    "What share of tax revenue did Atlantis apply to MDE in 2022?",
)


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def evaluate_retrieval(service: RagService, cases: Iterable[dict[str, Any]], k: int = 3) -> dict[str, Any]:
    """recall@k over document ids, and whether the answer cites an expected document."""
    results = []
    for case in cases:
        retrieved = list(dict.fromkeys(item.chunk.document_id for item in service.retriever.search(case["question"], k)))
        expected = set(case["expected_document_ids"])
        response = service.answer(case["question"])
        cited = {citation["document_id"] for citation in response["citations"]}
        results.append({
            "case_id": case["id"],
            "retrieved_document_ids": retrieved,
            "expected_document_ids": sorted(expected),
            "recall_at_k": len(expected.intersection(retrieved)) / len(expected) if expected else 1.0,
            "citation_coverage": 1.0 if response["status"] == "answered" and cited & expected else 0.0,
            "status": response["status"],
        })
    return {
        "k": k,
        "case_count": len(results),
        "recall_at_k": _mean([item["recall_at_k"] for item in results]),
        "citation_coverage": _mean([item["citation_coverage"] for item in results]),
        "cases": results,
    }


def evaluate_abstention(service: RagService, questions: Iterable[str] = OUT_OF_SCOPE_QUESTIONS) -> dict[str, Any]:
    results = []
    for question in questions:
        response = service.answer(question)
        results.append({
            "question": question,
            "status": response["status"],
            "correct": response["status"] in {"abstained", "refused"},
        })
    return {
        "case_count": len(results),
        "correct_abstention_rate": _mean([1.0 if item["correct"] else 0.0 for item in results]),
        "cases": results,
    }


def evaluate(corpus: list[dict[str, str]], cases: list[dict[str, Any]], limit: int = 2) -> dict[str, Any]:
    """v0.1 entry point over an in-memory `{id, content}` corpus."""
    service = build_service([document_from_fixture(entry, "inline") for entry in corpus])
    return evaluate_retrieval(service, cases, limit)


def education_cases(records: Sequence[dict[str, Any]], max_municipalities: int | None = None) -> list[dict[str, Any]]:
    """Derive one MDE and one population question per municipality from its latest year.

    With `max_municipalities`, municipalities are sampled at even steps over the sorted IBGE
    codes, so the sample is deterministic and spread across states.
    """
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        code = str(record["municipality_code"])
        if code not in latest or int(record["year"]) > int(latest[code]["year"]):
            latest[code] = record
    codes = sorted(latest)
    if max_municipalities and len(codes) > max_municipalities:
        step = len(codes) / max_municipalities
        codes = [codes[int(index * step)] for index in range(max_municipalities)]
    cases = []
    for code in codes:
        record = latest[code]
        name, year, document_id = record["municipality_name"], int(record["year"]), f"municipality-{code}"
        cases.append({
            "id": f"{code}-mde",
            "question": f"What share of tax revenue did {name} apply to maintenance and development of education in {year}?",
            "expected_document_ids": [document_id],
        })
        cases.append({
            "id": f"{code}-population",
            "question": f"What was the population of {name} in {year}?",
            "expected_document_ids": [document_id],
        })
    cases.append({
        "id": "dataset-card",
        "question": "Which schema version and manifest SHA-256 does the dataset card record?",
        "expected_document_ids": ["dataset-card"],
    })
    return cases
