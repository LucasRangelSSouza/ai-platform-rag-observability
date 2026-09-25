"""Cited-answer service: guardrails, retrieval, generation, and trace capture."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Any, Callable, Sequence

from .generation import ExtractiveGenerator, Generation, Generator
from .guardrails import injection_reason, question_reason
from .ingestion import Chunk, Document, chunk_documents, document_from_fixture
from .observability import Exporter, NoExporter, Observation, Score, Trace, new_id, utc_now
from .retrieval import Retriever, RetrievedChunk, build_retriever


LOGGER = logging.getLogger(__name__)
REFUSAL_TEXT = "I can answer questions about the approved corpus only."
ABSTENTION_TEXT = "The approved corpus does not contain enough evidence to answer this question."


@dataclass
class RagService:
    retriever: Retriever
    generator: Generator = field(default_factory=ExtractiveGenerator)
    exporter: Exporter = field(default_factory=NoExporter)
    top_k: int = 3
    min_coverage: float = 0.6
    clock: Callable[[], float] = time.perf_counter
    export_failures: int = 0

    def answer(self, question: str) -> dict[str, Any]:
        trace = Trace(id=new_id(), name="rag.answer", timestamp=utc_now(), question=question)
        reason = question_reason(question)
        if reason:
            result = _result("refused", REFUSAL_TEXT, [], reason)
        else:
            result = self._grounded_answer(question, trace)
        trace.output = result["answer"]
        trace.metadata.update({"outcome": result["status"], "safety_reason": result["safety_reason"], "citation_count": len(result["citations"])})
        trace.scores.append(Score("cited", 1.0 if result["citations"] else 0.0))
        self._export(trace)
        return {**result, "trace_id": trace.id}

    def _export(self, trace: Trace) -> None:
        # Observability must not decide whether a user gets an answer; failures are counted
        # and logged by type only, because exception text could echo request content.
        try:
            self.exporter.export(trace)
        except Exception as exc:  # noqa: BLE001
            self.export_failures += 1
            LOGGER.warning("trace export failed: %s", type(exc).__name__)

    def _grounded_answer(self, question: str, trace: Trace) -> dict[str, Any]:
        passages, quarantined = self._retrieve(question, trace)
        if not passages:
            reason = "context_injection_quarantined" if quarantined else "insufficient_retrieval"
            return _result("abstained", ABSTENTION_TEXT, [], reason)
        generation = self._generate(question, passages, trace)
        if generation.failure:
            return _result("abstained", ABSTENTION_TEXT, [], generation.failure)
        if not generation.cited_chunk_ids:
            return _result("abstained", ABSTENTION_TEXT, [], "no_valid_citation")
        by_id = {item.chunk.id: item for item in passages}
        citations = [{**by_id[chunk_id].chunk.citation(), "score": round(by_id[chunk_id].score, 6)} for chunk_id in generation.cited_chunk_ids]
        return _result("answered", generation.text, citations, None)

    def _retrieve(self, question: str, trace: Trace) -> tuple[list[RetrievedChunk], int]:
        # The question never enters an observation; the trace carries only its digest.
        span = Observation(id=new_id(), type="SPAN", name="retrieval", start_time=utc_now())
        started = self.clock()
        candidates = self.retriever.search(question, self.top_k)
        # Passages that carry instruction-like text are withheld from generation so a poisoned
        # document cannot steer the answer; the quarantine count stays visible in the trace.
        clean = [item for item in candidates if injection_reason(item.chunk.text) is None]
        passages = [item for item in clean if item.coverage >= self.min_coverage]
        span.latency_ms = round((self.clock() - started) * 1000, 3)
        span.end_time = utc_now()
        span.output = [item.chunk.text for item in passages]
        span.metadata = {
            "top_k": self.top_k,
            "min_coverage": self.min_coverage,
            "candidate_chunk_ids": [item.chunk.id for item in candidates],
            "accepted_chunk_ids": [item.chunk.id for item in passages],
            "scores": [round(item.score, 6) for item in candidates],
            "quarantined_count": len(candidates) - len(clean),
        }
        trace.observations.append(span)
        top_coverage = max((item.coverage for item in clean), default=0.0)
        trace.scores.append(Score("evidence_coverage", round(top_coverage, 6), observation_id=span.id))
        return passages, len(candidates) - len(clean)

    def _generate(self, question: str, passages: Sequence[RetrievedChunk], trace: Trace) -> Generation:
        retrieval_span = trace.observation("retrieval")
        observation = Observation(
            id=new_id(), type="GENERATION", name="generation", start_time=utc_now(),
            parent_observation_id=retrieval_span.id, input={"chunk_ids": [item.chunk.id for item in passages]},
        )
        started = self.clock()
        generation = self.generator.generate(question, passages)
        observation.latency_ms = round((self.clock() - started) * 1000, 3)
        observation.end_time = utc_now()
        observation.output = generation.text
        observation.model = generation.model or generation.generator
        observation.usage = generation.usage
        observation.cost_usd = generation.cost_usd
        observation.prompt_name = generation.prompt_name
        observation.prompt_version = generation.prompt_version
        observation.metadata = {
            "generator": generation.generator,
            "cited_chunk_ids": list(generation.cited_chunk_ids),
            "failure": generation.failure,
            **({"gateway": generation.attribution} if generation.attribution else {}),
        }
        trace.observations.append(observation)
        return generation


def _result(status: str, text: str, citations: list[dict[str, Any]], reason: str | None) -> dict[str, Any]:
    return {"status": status, "answer": text, "citations": citations, "safety_reason": reason}


def build_service(
    documents: Sequence[Document],
    retrieval_mode: str = "bm25",
    chunk_size: int = 120,
    chunk_overlap: int = 20,
    **options: Any,
) -> RagService:
    chunks: list[Chunk] = chunk_documents(documents, chunk_size, chunk_overlap)
    return RagService(retriever=build_retriever(chunks, retrieval_mode), **options)


def answer(question: str, corpus: list[dict[str, str]]) -> dict[str, Any]:
    """v0.1 convenience entry point over an in-memory `{id, content}` corpus."""
    service = build_service([document_from_fixture(entry, "inline") for entry in corpus])
    return service.answer(question)
