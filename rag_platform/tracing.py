from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any


def trace(question: str, result: dict[str, Any], gateway: str = "local-stub") -> dict[str, Any]:
    return {"trace_id": hashlib.sha256(question.encode()).hexdigest()[:16], "timestamp": datetime.now(timezone.utc).isoformat(), "gateway": gateway, "outcome": result["status"], "citation_count": len(result["citations"]), "safety_reason": result["safety_reason"]}
