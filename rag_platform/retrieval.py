"""Lexical, embedding, and hybrid retrieval over source-attributed chunks."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import heapq
import math
import re
from typing import Protocol, Sequence
import unicodedata

from .ingestion import Chunk


STOPWORDS = frozenset({
    "about", "also", "and", "are", "can", "did", "does", "for", "from", "has", "have", "how",
    "into", "its", "much", "not", "tell", "that", "the", "their", "there", "this", "was",
    "were", "what", "when", "where", "which", "who", "why", "will", "with", "you", "your",
})


def normalize_term(term: str) -> str:
    # A light plural fold keeps "routes"/"route" together without a stemmer dependency.
    if len(term) > 4 and term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


def fold_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def terms(text: str) -> list[str]:
    return [normalize_term(part) for part in re.findall(r"[a-z0-9]{3,}", fold_accents(text)) if part not in STOPWORDS]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float
    matched_terms: tuple[str, ...]
    coverage: float


class Retriever(Protocol):
    def search(self, question: str, limit: int) -> list[RetrievedChunk]: ...


class Embedder(Protocol):
    name: str

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic feature-hashing embedder; a stand-in for a local or provider model."""

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions
        self.name = f"hashing-{dimensions}"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for term in terms(text):
            digest = hashlib.sha256(term.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


class Bm25Index:
    """Okapi BM25 with an inverted index, so a query touches only chunks that share a term."""

    def __init__(self, chunks: Sequence[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = list(chunks)
        self.k1 = k1
        self.b = b
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        lengths = []
        for position, chunk in enumerate(self.chunks):
            counts = Counter(terms(chunk.text + " " + chunk.title))
            lengths.append(sum(counts.values()))
            for term, frequency in counts.items():
                self._postings[term].append((position, frequency))
        average = sum(lengths) / len(lengths) if lengths else 0.0
        self._length_ratio = [length / average if average else 0.0 for length in lengths]
        total = len(self.chunks)
        self._idf = {term: math.log(1 + (total - len(posting) + 0.5) / (len(posting) + 0.5)) for term, posting in self._postings.items()}

    def search(self, question: str, limit: int) -> list[RetrievedChunk]:
        query_terms = sorted(set(terms(question)))
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, list[str]] = defaultdict(list)
        for term in query_terms:
            idf = self._idf.get(term)
            if idf is None:
                continue
            for position, frequency in self._postings[term]:
                denominator = frequency + self.k1 * (1 - self.b + self.b * self._length_ratio[position])
                scores[position] += idf * frequency * (self.k1 + 1) / denominator
                matched[position].append(term)
        best = heapq.nsmallest(limit, scores, key=lambda position: (-scores[position], self.chunks[position].id))
        return [
            RetrievedChunk(self.chunks[position], scores[position], tuple(matched[position]), len(matched[position]) / len(query_terms))
            for position in best
        ]


class EmbeddingIndex:
    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder) -> None:
        self.chunks = list(chunks)
        self.embedder = embedder
        self._vectors = [embedder.embed(chunk.text + " " + chunk.title) for chunk in self.chunks]

    def similarities(self, question: str) -> list[float]:
        query = self.embedder.embed(question)
        return [cosine(query, vector) for vector in self._vectors]


class HybridRetriever:
    """Reciprocal-rank fusion of BM25 and embedding ranks.

    Embedding similarity only reorders chunks that share at least one query term with
    the question; it never admits a chunk on its own, so abstention stays lexical.
    """

    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder, rank_constant: int = 60) -> None:
        self.lexical = Bm25Index(chunks)
        self.embedding = EmbeddingIndex(chunks, embedder)
        self.rank_constant = rank_constant

    def search(self, question: str, limit: int) -> list[RetrievedChunk]:
        lexical = self.lexical.search(question, len(self.lexical.chunks))
        similarities = self.embedding.similarities(question)
        positions = {chunk.id: index for index, chunk in enumerate(self.embedding.chunks)}
        by_similarity = sorted(lexical, key=lambda item: (-similarities[positions[item.chunk.id]], item.chunk.id))
        embedding_rank = {item.chunk.id: rank for rank, item in enumerate(by_similarity)}
        fused = [
            RetrievedChunk(
                item.chunk,
                1 / (self.rank_constant + rank + 1) + 1 / (self.rank_constant + embedding_rank[item.chunk.id] + 1),
                item.matched_terms,
                item.coverage,
            )
            for rank, item in enumerate(lexical)
        ]
        return sorted(fused, key=lambda item: (-item.score, item.chunk.id))[:limit]


def build_retriever(chunks: Sequence[Chunk], mode: str = "bm25", embedder: Embedder | None = None) -> Retriever:
    if mode == "bm25":
        return Bm25Index(chunks)
    if mode == "hybrid":
        return HybridRetriever(chunks, embedder or HashingEmbedder())
    raise ValueError(f"unknown retrieval mode: {mode}")
