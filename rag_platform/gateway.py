"""OpenAI-compatible chat-completions client for a 9Router-style gateway.

Routing policy, in order of precedence:

1. Routes are tried in the declared order (primary first, then fallbacks).
2. Retryable failures (HTTP 408, 429, 5xx, timeouts, connection errors) are retried on the
   same route with exponential backoff, then the next route is tried.
3. Route-specific failures (HTTP 401, 403, 404) skip to the next route without a retry,
   because a different route may hold a valid connection or model.
4. Any other 4xx and malformed responses stop immediately: the request itself is at fault
   and would fail the same way on every route.

Credentials are read from the environment at call time and never stored on the client or
included in attempt records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import socket
import time
from typing import Any, Callable
from urllib import error, request


@dataclass(frozen=True)
class Route:
    name: str
    base_url: str
    model: str
    api_key_env: str | None = None


@dataclass(frozen=True)
class Price:
    input_per_million: float
    output_per_million: float


class PriceTable:
    def __init__(self, prices: dict[str, Price]) -> None:
        self.prices = dict(prices)

    @classmethod
    def from_json(cls, path: Path) -> "PriceTable":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls({model: Price(float(item["input_per_million"]), float(item["output_per_million"])) for model, item in raw.items()})

    def cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        price = self.prices.get(model)
        if price is None:
            return None
        total = prompt_tokens * price.input_per_million + completion_tokens * price.output_per_million
        return round(total / 1_000_000, 10)


@dataclass(frozen=True)
class Attempt:
    route: str
    model: str
    status: int | None
    error_kind: str | None
    latency_ms: float


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class GatewayResponse:
    content: str
    route: str
    model: str
    usage: Usage
    cost_usd: float | None
    attempts: tuple[Attempt, ...]

    def attribution(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "model": self.model,
            "usage": asdict(self.usage),
            "cost_usd": self.cost_usd,
            "priced": self.cost_usd is not None,
            "attempts": [asdict(attempt) for attempt in self.attempts],
        }


class GatewayError(Exception):
    def __init__(
        self, kind: str, message: str, status: int | None = None,
        attempts: tuple[Attempt, ...] = (), retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.attempts = attempts
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in {"rate_limited", "server_error", "timeout", "network"}

    @property
    def route_specific(self) -> bool:
        return self.kind in {"auth", "not_found"}


def classify_status(status: int) -> str:
    if status == 429:
        return "rate_limited"
    if status == 408:
        return "timeout"
    if status >= 500:
        return "server_error"
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    return "bad_request"


@dataclass
class ChatGateway:
    routes: list[Route]
    prices: PriceTable = field(default_factory=lambda: PriceTable({}))
    max_attempts_per_route: int = 3
    backoff_seconds: float = 0.2
    max_backoff_seconds: float = 5.0
    timeout_seconds: float = 30.0
    sleep: Callable[[float], None] = time.sleep
    environ: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.routes:
            raise ValueError("at least one route is required")

    def complete(self, messages: list[dict[str, str]], **params: Any) -> GatewayResponse:
        attempts: list[Attempt] = []
        last_error: GatewayError | None = None
        for route in self.routes:
            for attempt_number in range(self.max_attempts_per_route):
                started = time.perf_counter()
                try:
                    payload = self._post(route, messages, params)
                    response = self._parse(route, payload)
                except GatewayError as exc:
                    attempts.append(Attempt(route.name, route.model, exc.status, exc.kind, _elapsed_ms(started)))
                    last_error = exc
                    if exc.retryable and attempt_number + 1 < self.max_attempts_per_route:
                        self.sleep(self._backoff(attempt_number, exc))
                        continue
                    if exc.retryable or exc.route_specific:
                        break
                    raise GatewayError(exc.kind, str(exc), exc.status, tuple(attempts)) from exc
                attempts.append(Attempt(route.name, route.model, 200, None, _elapsed_ms(started)))
                content, usage = response
                cost = self.prices.cost(route.model, usage.prompt_tokens, usage.completion_tokens)
                return GatewayResponse(content, route.name, route.model, usage, cost, tuple(attempts))
        assert last_error is not None
        raise GatewayError("routes_exhausted", f"all routes failed; last error: {last_error.kind}", last_error.status, tuple(attempts))

    def _backoff(self, attempt_number: int, exc: GatewayError) -> float:
        if exc.retry_after is not None:
            return min(exc.retry_after, self.max_backoff_seconds)
        return min(self.backoff_seconds * (2 ** attempt_number), self.max_backoff_seconds)

    def _post(self, route: Route, messages: list[dict[str, str]], params: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"model": route.model, "messages": messages, **params}).encode()
        headers = {"Content-Type": "application/json"}
        environ = self.environ if self.environ is not None else os.environ
        if route.api_key_env and environ.get(route.api_key_env):
            headers["Authorization"] = f"Bearer {environ[route.api_key_env]}"
        url = route.base_url.rstrip("/") + "/chat/completions"
        http_request = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as http_response:
                raw = http_response.read()
        except error.HTTPError as exc:
            retry_after = _retry_after(exc.headers.get("Retry-After"))
            exc.close()
            raise GatewayError(classify_status(exc.code), f"HTTP {exc.code} from route {route.name}", exc.code, retry_after=retry_after) from None
        except (socket.timeout, TimeoutError) as exc:
            raise GatewayError("timeout", f"timeout on route {route.name}") from exc
        except error.URLError as exc:
            kind = "timeout" if isinstance(exc.reason, (socket.timeout, TimeoutError)) else "network"
            raise GatewayError(kind, f"{kind} on route {route.name}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GatewayError("invalid_response", f"route {route.name} returned non-JSON content") from exc

    @staticmethod
    def _parse(route: Route, payload: dict[str, Any]) -> tuple[str, Usage]:
        try:
            content = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0))
            completion_tokens = int(usage.get("completion_tokens", 0))
            total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GatewayError("invalid_response", f"route {route.name} returned an unexpected payload") from exc
        if not isinstance(content, str):
            raise GatewayError("invalid_response", f"route {route.name} returned non-text content")
        return content, Usage(prompt_tokens, completion_tokens, total_tokens)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _retry_after(value: str | None) -> float | None:
    try:
        return max(float(value), 0.0) if value is not None else None
    except ValueError:
        return None


def routes_from_env(environ: dict[str, str] | None = None) -> list[Route]:
    """Build primary/fallback routes from RAG_GATEWAY_* variables; empty when unset."""
    env = environ if environ is not None else dict(os.environ)
    base_url = env.get("RAG_GATEWAY_BASE_URL")
    if not base_url:
        return []
    routes = [Route("primary", base_url, env.get("RAG_GATEWAY_MODEL", "default"), "RAG_GATEWAY_API_KEY")]
    if env.get("RAG_GATEWAY_FALLBACK_MODEL"):
        routes.append(Route("fallback", env.get("RAG_GATEWAY_FALLBACK_BASE_URL", base_url), env["RAG_GATEWAY_FALLBACK_MODEL"], "RAG_GATEWAY_API_KEY"))
    return routes
