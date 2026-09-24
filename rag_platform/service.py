from __future__ import annotations

import re
from typing import Any


INJECTION_PATTERNS = ("ignore previous", "system prompt", "reveal instructions")
STOPWORDS = {"about", "does", "from", "have", "how", "into", "that", "the", "this", "what", "when", "with"}


def tokens(text: str) -> set[str]:
    return {part for part in re.findall(r"[a-z0-9]{3,}", text.casefold()) if part not in STOPWORDS}


def retrieve(question: str, corpus: list[dict[str, str]], limit: int = 2) -> list[dict[str, Any]]:
    query_terms = tokens(question)
    scored = []
    for document in corpus:
        overlap = query_terms & tokens(document["content"])
        if overlap:
            scored.append({"id": document["id"], "content": document["content"], "score": len(overlap), "matched_terms": sorted(overlap)})
    return sorted(scored, key=lambda item: (-item["score"], item["id"]))[:limit]


def answer(question: str, corpus: list[dict[str, str]]) -> dict[str, Any]:
    normalized = question.casefold()
    if any(pattern in normalized for pattern in INJECTION_PATTERNS):
        return {"status": "refused", "answer": "I can answer questions about the approved corpus only.", "citations": [], "safety_reason": "prompt_injection_pattern"}
    passages = retrieve(question, corpus)
    if not passages:
        return {"status": "abstained", "answer": "The approved corpus does not contain enough evidence to answer this question.", "citations": [], "safety_reason": "insufficient_retrieval"}
    evidence = passages[0]
    return {"status": "answered", "answer": evidence["content"], "citations": [{"document_id": item["id"], "score": item["score"]} for item in passages], "safety_reason": None}
