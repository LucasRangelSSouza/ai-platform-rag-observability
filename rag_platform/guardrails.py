"""Pattern-based input and context screening.

These checks recognise known phrasing only. They reduce accidental instruction-following
in a demonstration; they are not a complete prompt-injection defence.
"""

from __future__ import annotations

import re
import unicodedata


INJECTION_PATTERNS = (
    r"\bignore (all |any |the )?(previous|prior|above|earlier)\b",
    r"\bdisregard (all |any |the )?(previous|prior|above|earlier|your)\b",
    r"\bforget (all |any |the )?(previous|prior|your) (instructions|rules)\b",
    r"\bsystem prompt\b",
    r"\b(reveal|print|show|repeat) (your |the )?(hidden |system )?(instructions|prompt|rules)\b",
    r"\bdeveloper mode\b",
    r"\bjailbreak\b",
    r"\byou are now\b",
    r"\bnew instructions\s*:",
    r"\boverride (your |the )?(safety|rules|instructions)\b",
)
_COMPILED = tuple(re.compile(pattern) for pattern in INJECTION_PATTERNS)
MAX_QUESTION_CHARS = 1000


def normalize(text: str) -> str:
    """Fold width, case, zero-width characters, and spacing before matching."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = re.sub(r"[​-‏⁠﻿]", "", folded)
    return re.sub(r"\s+", " ", folded).strip()


def injection_reason(text: str) -> str | None:
    normalized = normalize(text)
    if any(pattern.search(normalized) for pattern in _COMPILED):
        return "prompt_injection_pattern"
    return None


def question_reason(question: str) -> str | None:
    if len(question) > MAX_QUESTION_CHARS:
        return "question_too_long"
    return injection_reason(question)
