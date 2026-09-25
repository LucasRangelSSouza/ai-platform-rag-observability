"""Source-attributed documents and deterministic chunking."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Iterable


FIXTURE_LICENSE = "Synthetic fixture text written for this repository; Apache-2.0."


@dataclass(frozen=True)
class DatasetReference:
    slug: str
    version: int
    manifest_sha256: str


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    text: str
    source_uri: str
    license_note: str
    dataset: DatasetReference | None = None
    record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or "#" in self.id:
            raise ValueError("document id must be non-empty and must not contain '#'")
        if not self.text.strip():
            raise ValueError(f"document {self.id} has no text")
        if not self.source_uri:
            raise ValueError(f"document {self.id} has no source_uri")


@dataclass(frozen=True)
class Chunk:
    id: str
    document_id: str
    position: int
    text: str
    title: str
    source_uri: str
    license_note: str
    dataset: DatasetReference | None = None
    record_ids: tuple[str, ...] = field(default=())

    def citation(self) -> dict[str, Any]:
        citation: dict[str, Any] = {
            "chunk_id": self.id,
            "document_id": self.document_id,
            "title": self.title,
            "source_uri": self.source_uri,
            "license_note": self.license_note,
        }
        if self.dataset is not None:
            citation["dataset"] = asdict(self.dataset)
            citation["record_ids"] = list(self.record_ids)
        return citation


def chunk_id(document_id: str, position: int) -> str:
    return f"{document_id}#c{position:03d}"


def chunk_document(document: Document, size: int = 120, overlap: int = 20) -> list[Chunk]:
    """Split on whitespace into windows of `size` words that share `overlap` words."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    if not 0 <= overlap < size:
        raise ValueError("chunk overlap must be in [0, size)")
    words = re.findall(r"\S+", document.text)
    step = size - overlap
    starts = range(0, max(len(words) - overlap, 1), step)
    return [
        Chunk(
            id=chunk_id(document.id, position),
            document_id=document.id,
            position=position,
            text=" ".join(words[start:start + size]),
            title=document.title,
            source_uri=document.source_uri,
            license_note=document.license_note,
            dataset=document.dataset,
            record_ids=document.record_ids,
        )
        for position, start in enumerate(starts)
    ]


def chunk_documents(documents: Iterable[Document], size: int = 120, overlap: int = 20) -> list[Chunk]:
    chunks: list[Chunk] = []
    seen: set[str] = set()
    for document in documents:
        if document.id in seen:
            raise ValueError(f"duplicate document id: {document.id}")
        seen.add(document.id)
        chunks.extend(chunk_document(document, size, overlap))
    return chunks


def document_from_fixture(entry: dict[str, Any], source_name: str) -> Document:
    """Accept both the v0.1 `{id, content}` shape and the attributed v0.2 shape."""
    return Document(
        id=entry["id"],
        title=entry.get("title", entry["id"]),
        text=entry.get("text", entry.get("content", "")),
        source_uri=entry.get("source_uri", f"fixture://{source_name}#{entry['id']}"),
        license_note=entry.get("license_note", FIXTURE_LICENSE),
    )


def load_fixture_documents(path: Path) -> list[Document]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    return [document_from_fixture(entry, path.name) for entry in entries]
