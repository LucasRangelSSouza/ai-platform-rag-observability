import unittest

from rag_platform.ingestion import Document, chunk_documents
from rag_platform.retrieval import Bm25Index, HashingEmbedder, HybridRetriever, build_retriever, cosine, terms


def chunks(entries: dict[str, str]):
    return chunk_documents([Document(key, key, text, f"fixture://{key}", "test") for key, text in entries.items()])


CORPUS = chunks({
    "gateway": "The gateway routes model requests to a primary route and a fallback route.",
    "tracing": "Traces record latency, token usage, and evaluation scores for each request.",
    "safety": "The service abstains when retrieval finds no supporting evidence.",
})


class TermTests(unittest.TestCase):
    def test_stopwords_and_short_tokens_are_removed(self):
        self.assertEqual(terms("How does the AI gateway work?"), ["gateway", "work"])

    def test_plural_fold_matches_singular(self):
        self.assertEqual(terms("routes requests"), terms("route request"))


class Bm25Tests(unittest.TestCase):
    def test_ranks_the_matching_chunk_first(self):
        results = Bm25Index(CORPUS).search("Which route handles fallback requests?", 3)
        self.assertEqual(results[0].chunk.document_id, "gateway")

    def test_no_shared_terms_returns_nothing(self):
        self.assertEqual(Bm25Index(CORPUS).search("What is the weather?", 3), [])

    def test_coverage_is_share_of_query_terms_matched(self):
        result = Bm25Index(CORPUS).search("gateway weather", 3)[0]
        self.assertEqual(result.matched_terms, ("gateway",))
        self.assertEqual(result.coverage, 0.5)

    def test_rarer_terms_weigh_more(self):
        index = Bm25Index(chunks({"a": "common rare", "b": "common filler", "c": "common other"}))
        self.assertEqual(index.search("common rare", 3)[0].chunk.document_id, "a")

    def test_limit_is_respected(self):
        self.assertEqual(len(Bm25Index(CORPUS).search("route latency evidence", 2)), 2)


class EmbeddingTests(unittest.TestCase):
    def test_hashing_embedder_is_deterministic_and_normalized(self):
        embedder = HashingEmbedder(64)
        vector = embedder.embed("gateway fallback route")
        self.assertEqual(vector, HashingEmbedder(64).embed("gateway fallback route"))
        self.assertAlmostEqual(cosine(vector, vector), 1.0)

    def test_empty_text_embeds_to_zero_vector(self):
        self.assertEqual(HashingEmbedder(8).embed("the and"), [0.0] * 8)

    def test_hybrid_never_admits_a_chunk_without_shared_terms(self):
        self.assertEqual(HybridRetriever(CORPUS, HashingEmbedder()).search("What is the weather?", 3), [])

    def test_hybrid_ranks_the_matching_chunk_first(self):
        results = build_retriever(CORPUS, "hybrid").search("fallback route for model requests", 3)
        self.assertEqual(results[0].chunk.document_id, "gateway")

    def test_custom_embedder_satisfies_the_protocol(self):
        class ConstantEmbedder:
            name = "constant"

            def embed(self, text):
                return [1.0, 0.0]

        results = build_retriever(CORPUS, "hybrid", ConstantEmbedder()).search("token latency", 3)
        self.assertEqual(results[0].chunk.document_id, "tracing")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            build_retriever(CORPUS, "dense-only")


if __name__ == "__main__":
    unittest.main()
