from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


def trace(question: str, result: dict[str, Any], gateway: str = "local-stub") -> dict[str, Any]:
    question_digest = hashlib.sha256(question.encode()).hexdigest()
    return {
        "trace_id": question_digest[:16],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gateway": gateway,
        "outcome": result["status"],
        "citation_count": len(result["citations"]),
        "citation_document_ids": [citation["document_id"] for citation in result["citations"]],
        "safety_reason": result["safety_reason"],
        "question_sha256": question_digest,
    }


def append_trace(path: Path, trace_record: dict[str, Any]) -> None:
    """Append a metadata-only trace that is safe to inspect without raw prompts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace_record, sort_keys=True) + "\n")
