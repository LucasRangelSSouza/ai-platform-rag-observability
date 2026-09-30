"""Language matching for short, deterministic refusal and abstention messages."""

from __future__ import annotations

from langid import classify


MESSAGES = {
    "en": {
        "abstained": "The approved corpus does not contain enough evidence to answer this question.",
        "refused": "I can answer questions about the approved corpus only.",
    },
    "pt": {
        "abstained": "O corpus aprovado não contém evidências suficientes para responder a esta pergunta.",
        "refused": "Posso responder apenas a perguntas sobre o corpus aprovado.",
    },
}


def language_code(text: str) -> str:
    """Return the detected ISO-639 language code for a visitor question."""
    code, _ = classify(text)
    return code


def response_message(status: str, question: str) -> str:
    """Return the approved non-generative response in the visitor's supported language."""
    language = language_code(question)
    messages = MESSAGES.get(language, MESSAGES["en"])
    return messages[status]
