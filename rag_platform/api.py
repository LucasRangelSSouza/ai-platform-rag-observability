"""Stdlib JSON API: `POST /v1/answer` and `GET /healthz`."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any

from .guardrails import MAX_QUESTION_CHARS
from .service import RagService


MAX_BODY_BYTES = 16 * 1024


class RequestError(ValueError):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


def parse_answer_request(raw: bytes) -> str:
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RequestError(HTTPStatus.BAD_REQUEST, "body must be valid JSON") from None
    if not isinstance(body, dict):
        raise RequestError(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
    unknown = sorted(set(body) - {"question"})
    if unknown:
        raise RequestError(HTTPStatus.BAD_REQUEST, f"unknown field: {unknown[0]}")
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        raise RequestError(HTTPStatus.BAD_REQUEST, "question must be a non-empty string")
    if len(question) > MAX_QUESTION_CHARS:
        raise RequestError(HTTPStatus.BAD_REQUEST, f"question must be at most {MAX_QUESTION_CHARS} characters")
    return question


def make_handler(service: RagService, health: dict[str, Any], access_log: bool = True) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "rag-platform"
        sys_version = ""

        def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            if self.path == "/healthz":
                self._send(HTTPStatus.OK, {"status": "ok", **health})
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/answer":
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY_BYTES:
                    raise RequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"body must be at most {MAX_BODY_BYTES} bytes")
                question = parse_answer_request(self.rfile.read(length))
            except RequestError as exc:
                self._send(exc.status, {"error": str(exc)})
                return
            except ValueError:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
                return
            self._send(HTTPStatus.OK, service.answer(question))

        def log_message(self, format: str, *args: Any) -> None:
            # The default line holds method, path, and status only; bodies are never logged.
            if access_log:
                super().log_message(format, *args)

    return Handler


def make_server(
    service: RagService, host: str = "127.0.0.1", port: int = 8080,
    health: dict[str, Any] | None = None, access_log: bool = True,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(service, health or {}, access_log))
