"""Langfuse-shaped traces with mandatory redaction before any export.

A trace holds a retrieval span; the generation observation is nested under that span
because it consumes the retrieved context. Exporters accept only `Trace` objects and
apply `redact` themselves, so no export path can skip redaction.
"""

from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable, Protocol
from urllib import error, request
import uuid


CONTENT_FIELDS = ("input", "output")
SECRET_KEY_MARKERS = ("authorization", "api_key", "apikey", "secret", "password", "token")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def question_digest(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()


@dataclass
class Score:
    name: str
    value: float
    observation_id: str | None = None
    comment: str | None = None


@dataclass
class Observation:
    id: str
    type: str
    name: str
    start_time: str
    end_time: str | None = None
    parent_observation_id: str | None = None
    input: Any = None
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    usage: dict[str, int] | None = None
    cost_usd: float | None = None
    prompt_name: str | None = None
    prompt_version: int | None = None
    latency_ms: float | None = None


@dataclass
class Trace:
    id: str
    name: str
    timestamp: str
    question: str
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    observations: list[Observation] = field(default_factory=list)
    scores: list[Score] = field(default_factory=list)

    def observation(self, name: str) -> Observation:
        return next(item for item in self.observations if item.name == name)


def new_id() -> str:
    return uuid.uuid4().hex


def _scrub_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if not any(marker in key.casefold() for marker in SECRET_KEY_MARKERS)}


def redact(trace: Trace, allow_content: bool = False) -> dict[str, Any]:
    """Return an export-safe dictionary.

    The raw question is always replaced by its SHA-256 digest. Passage text, prompts, and
    answer text are dropped unless `allow_content` is explicitly set. Metadata keys that look
    like credentials are always removed.
    """
    observations = []
    for item in trace.observations:
        record = {
            "id": item.id,
            "type": item.type,
            "name": item.name,
            "start_time": item.start_time,
            "end_time": item.end_time,
            "parent_observation_id": item.parent_observation_id,
            "metadata": _scrub_metadata(item.metadata),
            "model": item.model,
            "usage": item.usage,
            "cost_usd": item.cost_usd,
            "prompt_name": item.prompt_name,
            "prompt_version": item.prompt_version,
            "latency_ms": item.latency_ms,
        }
        if allow_content:
            record.update({"input": item.input, "output": item.output})
        observations.append(record)
    exported = {
        "id": trace.id,
        "name": trace.name,
        "timestamp": trace.timestamp,
        "question_sha256": question_digest(trace.question),
        "metadata": _scrub_metadata(trace.metadata),
        "observations": observations,
        "scores": [score.__dict__.copy() for score in trace.scores],
        "content_included": allow_content,
    }
    if allow_content:
        exported["output"] = trace.output
    return exported


class Exporter(Protocol):
    def export(self, trace: Trace) -> None: ...


class NoExporter:
    """Local no-export mode: the last few redacted traces stay in memory; nothing leaves the process."""

    def __init__(self, keep: int = 100) -> None:
        self.exported: deque[dict[str, Any]] = deque(maxlen=keep)

    def export(self, trace: Trace) -> None:
        self.exported.append(redact(trace))


class JsonlExporter:
    def __init__(self, path: Path, allow_content: bool = False) -> None:
        self.path = path
        self.allow_content = allow_content
        self._lock = threading.Lock()

    def export(self, trace: Trace) -> None:
        line = json.dumps(redact(trace, self.allow_content), sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)


class LangfuseExportError(RuntimeError):
    pass


def ingestion_batch(exported: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a redacted trace to Langfuse public ingestion events."""
    trace_body = {
        "id": exported["id"],
        "timestamp": exported["timestamp"],
        "name": exported["name"],
        "metadata": {**exported["metadata"], "question_sha256": exported["question_sha256"]},
    }
    if exported.get("content_included"):
        trace_body["output"] = exported.get("output")
    events = [_event("trace-create", exported["timestamp"], trace_body)]
    for item in exported["observations"]:
        body: dict[str, Any] = {
            "id": item["id"],
            "traceId": exported["id"],
            "parentObservationId": item["parent_observation_id"],
            "name": item["name"],
            "startTime": item["start_time"],
            "endTime": item["end_time"],
            "metadata": {**item["metadata"], "latency_ms": item["latency_ms"]},
        }
        if exported.get("content_included"):
            body.update({"input": item.get("input"), "output": item.get("output")})
        if item["type"] == "GENERATION":
            body.update({"model": item["model"], "promptName": item["prompt_name"], "promptVersion": item["prompt_version"]})
            if item["usage"]:
                body["usageDetails"] = {"input": item["usage"].get("prompt_tokens", 0), "output": item["usage"].get("completion_tokens", 0)}
            if item["cost_usd"] is not None:
                body["costDetails"] = {"total": item["cost_usd"]}
            events.append(_event("generation-create", item["start_time"], body))
        else:
            events.append(_event("span-create", item["start_time"], body))
    for score in exported["scores"]:
        score_body = {"id": new_id(), "traceId": exported["id"], "name": score["name"], "value": score["value"], "dataType": "NUMERIC"}
        if score.get("observation_id"):
            score_body["observationId"] = score["observation_id"]
        events.append(_event("score-create", exported["timestamp"], score_body))
    return events


def _event(kind: str, timestamp: str, body: dict[str, Any]) -> dict[str, Any]:
    return {"id": new_id(), "timestamp": timestamp, "type": kind, "body": body}


class LangfuseExporter:
    """Client for `POST /api/public/ingestion` using basic auth read from the environment."""

    def __init__(
        self,
        host: str,
        public_key_env: str = "LANGFUSE_PUBLIC_KEY",
        secret_key_env: str = "LANGFUSE_SECRET_KEY",
        allow_content: bool = False,
        timeout_seconds: float = 10.0,
        environ: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.public_key_env = public_key_env
        self.secret_key_env = secret_key_env
        self.allow_content = allow_content
        self.timeout_seconds = timeout_seconds
        self._environ = environ or (lambda: dict(os.environ))

    def _authorization(self) -> str:
        env = self._environ()
        public_key, secret_key = env.get(self.public_key_env), env.get(self.secret_key_env)
        if not public_key or not secret_key:
            raise LangfuseExportError(f"{self.public_key_env} and {self.secret_key_env} must be set to export traces")
        return "Basic " + base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

    def export(self, trace: Trace) -> None:
        payload = {"batch": ingestion_batch(redact(trace, self.allow_content)), "metadata": {"sdk": "rag_platform"}}
        http_request = request.Request(
            f"{self.host}/api/public/ingestion",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": self._authorization()},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read() or b"{}")
        except error.HTTPError as exc:
            raise LangfuseExportError(f"Langfuse ingestion returned HTTP {exc.code}") from None
        except (error.URLError, TimeoutError) as exc:
            raise LangfuseExportError("Langfuse ingestion is unreachable") from exc
        if body.get("errors"):
            raise LangfuseExportError(f"Langfuse rejected {len(body['errors'])} ingestion events")
