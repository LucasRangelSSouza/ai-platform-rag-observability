"""In-process fake HTTP servers bound to 127.0.0.1 for gateway and Langfuse tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any


@dataclass
class ScriptedReply:
    status: int = 200
    body: Any = None
    delay_seconds: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)
    raw: bytes | None = None


def completion(content: str, prompt_tokens: int = 100, completion_tokens: int = 20) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens},
    }


class FakeServer:
    """Replies are consumed per path in order; the last reply repeats once the script runs out."""

    def __init__(self, scripts: dict[str, list[ScriptedReply]]) -> None:
        self.scripts = {path: list(replies) for path, replies in scripts.items()}
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def requests_to(self, path: str) -> list[dict[str, Any]]:
        return [item for item in self.requests if item["path"] == path]

    def _next(self, path: str) -> ScriptedReply:
        with self._lock:
            replies = self.scripts.get(path)
            if not replies:
                return ScriptedReply(404, {"error": "no script"})
            return replies.pop(0) if len(replies) > 1 else replies[0]

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                with fake._lock:
                    fake.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body or b"null")})
                reply = fake._next(self.path)
                if reply.delay_seconds:
                    time.sleep(reply.delay_seconds)
                payload = reply.raw if reply.raw is not None else json.dumps(reply.body).encode()
                try:
                    self.send_response(reply.status)
                    for key, value in reply.headers.items():
                        self.send_header(key, value)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, format: str, *args: Any) -> None:
                pass

        return Handler

    def __enter__(self) -> "FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
