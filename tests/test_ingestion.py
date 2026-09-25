import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag_platform.ingestion import DatasetReference, Document, chunk_document, chunk_documents, load_fixture_documents


def document(text: str, **overrides) -> Document:
    fields = {"id": "doc", "title": "Doc", "text": text, "source_uri": "fixture://doc", "license_note": "test"}
    return Document(**{**fields, **overrides})


class ChunkingTests(unittest.TestCase):
    def test_windows_overlap_and_cover_every_word(self):
        words = [f"w{index}" for index in range(10)]
        chunks = chunk_document(document(" ".join(words)), size=4, overlap=1)
        self.assertEqual([chunk.text.split() for chunk in chunks], [words[0:4], words[3:7], words[6:10]])

    def test_chunk_ids_are_positional_and_keep_document_attribution(self):
        reference = DatasetReference("owner/dataset", 1, "a" * 64)
        source = document("one two three four five six", dataset=reference, record_ids=("r1",))
        chunks = chunk_document(source, size=3, overlap=0)
        self.assertEqual([chunk.id for chunk in chunks], ["doc#c000", "doc#c001"])
        for chunk in chunks:
            self.assertEqual((chunk.document_id, chunk.source_uri, chunk.dataset, chunk.record_ids), ("doc", "fixture://doc", reference, ("r1",)))

    def test_chunking_is_deterministic(self):
        text = " ".join(f"token{index}" for index in range(50))
        self.assertEqual(chunk_document(document(text), 7, 2), chunk_document(document(text), 7, 2))

    def test_short_document_yields_one_chunk(self):
        self.assertEqual(len(chunk_document(document("only three words"), size=10, overlap=2)), 1)

    def test_invalid_window_is_rejected(self):
        with self.assertRaises(ValueError):
            chunk_document(document("a b c"), size=3, overlap=3)
        with self.assertRaises(ValueError):
            chunk_document(document("a b c"), size=0, overlap=0)

    def test_duplicate_document_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            chunk_documents([document("a"), document("b")])

    def test_document_requires_text_source_and_safe_id(self):
        with self.assertRaises(ValueError):
            document("   ")
        with self.assertRaises(ValueError):
            document("text", source_uri="")
        with self.assertRaises(ValueError):
            document("text", id="bad#id")

    def test_citation_carries_dataset_and_record_ids_only_for_dataset_documents(self):
        plain = chunk_document(document("plain text"))[0].citation()
        self.assertNotIn("dataset", plain)
        cited = chunk_document(document("text", dataset=DatasetReference("o/d", 2, "b" * 64), record_ids=("x-1",)))[0].citation()
        self.assertEqual(cited["dataset"], {"slug": "o/d", "version": 2, "manifest_sha256": "b" * 64})
        self.assertEqual(cited["record_ids"], ["x-1"])


class FixtureLoadingTests(unittest.TestCase):
    def test_legacy_id_content_shape_gets_default_attribution(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            path.write_text(json.dumps([{"id": "a", "content": "legacy text"}]), encoding="utf-8")
            loaded = load_fixture_documents(path)
        self.assertEqual(loaded[0].text, "legacy text")
        self.assertEqual(loaded[0].source_uri, "fixture://corpus.json#a")

    def test_checked_in_fixture_is_attributed(self):
        documents = load_fixture_documents(Path(__file__).resolve().parents[1] / "data" / "corpus_fixture.json")
        self.assertTrue(all(doc.source_uri.startswith("fixture://") and doc.license_note for doc in documents))


if __name__ == "__main__":
    unittest.main()
