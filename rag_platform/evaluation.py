"""Offline retrieval evaluation for the deterministic fixture corpus."""

from __future__ import annotations

from typing import Any

from .service import retrieve


def evaluate(corpus: list[dict[str, str]], cases: list[dict[str, Any]], limit: int = 2) -> dict[str, Any]:
    """Measure whether expected evidence is retrieved and cited in fixture cases."""
    results = []
    for case in cases:
        retrieved = retrieve(case["question"], corpus, limit)
        retrieved_ids = [item["id"] for item in retrieved]
        expected_ids = set(case["expected_document_ids"])
        overlap = expected_ids.intersection(retrieved_ids)
        results.append({
            "case_id": case["id"],
            "retrieved_document_ids": retrieved_ids,
            "expected_document_ids": sorted(expected_ids),
            "recall_at_k": len(overlap) / len(expected_ids) if expected_ids else 1.0,
            "citation_coverage": bool(overlap),
        })
    total = len(results)
    return {
        "case_count": total,
        "recall_at_k": sum(item["recall_at_k"] for item in results) / total if total else 0.0,
        "citation_coverage": sum(item["citation_coverage"] for item in results) / total if total else 0.0,
        "cases": results,
    }
