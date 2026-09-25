import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rag_platform.__main__ import main


REPO = Path(__file__).resolve().parents[1]
FIXTURE = str(REPO / "data" / "corpus_fixture.json")
CASES = str(REPO / "data" / "evaluation_fixture.json")
EDUCATION = str(REPO / "data" / "education_fixture")


def run(*argv):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        main(list(argv))
    return json.loads(output.getvalue())


class CliTests(unittest.TestCase):
    def test_answer_prints_result_and_redacted_trace(self):
        payload = run("answer", "--corpus", FIXTURE, "--question", "How does the retrieval service abstain?")
        self.assertEqual(payload["result"]["status"], "answered")
        self.assertEqual(payload["trace"]["id"], payload["result"]["trace_id"])
        self.assertNotIn("How does the retrieval service abstain?", json.dumps(payload["trace"]))

    def test_answer_writes_output_and_jsonl_trace(self):
        with TemporaryDirectory() as directory:
            output, traces = Path(directory) / "result.json", Path(directory) / "traces.jsonl"
            run("answer", "--corpus", FIXTURE, "--question", "What is the weather?", "--output", str(output), "--trace-output", str(traces))
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["result"]["status"], "abstained")
            self.assertEqual(len(traces.read_text(encoding="utf-8").splitlines()), 1)

    def test_answer_over_the_synthetic_education_release(self):
        payload = run("answer", "--education-dir", EDUCATION, "--release", "synthetic-fixture", "--question", "What was the population of Vale Azul in 2022?")
        citation = payload["result"]["citations"][0]
        self.assertEqual(citation["dataset"]["slug"], "synthetic/brazil-education-data-lake-fixture")
        self.assertIn("9900001-2022", citation["record_ids"])

    def test_education_dir_rejects_a_release_that_does_not_match_the_v1_pin(self):
        with self.assertRaises(SystemExit) as caught:
            run("answer", "--education-dir", EDUCATION, "--release", "v1", "--question", "x")
        self.assertIn("manifest SHA-256 does not match", str(caught.exception))

    def test_evaluate_fixture_reports_retrieval_and_abstention(self):
        payload = run("evaluate", "--corpus", FIXTURE, "--cases", CASES)
        self.assertEqual((payload["retrieval"]["case_count"], payload["retrieval"]["recall_at_k"], payload["retrieval"]["citation_coverage"]), (6, 1.0, 1.0))
        self.assertEqual(payload["abstention"]["correct_abstention_rate"], 1.0)

    def test_evaluate_hybrid_mode_runs(self):
        payload = run("evaluate", "--corpus", FIXTURE, "--cases", CASES, "--retrieval", "hybrid")
        self.assertEqual(payload["retrieval"]["recall_at_k"], 1.0)

    def test_gateway_generator_requires_configuration(self):
        previous = os.environ.pop("RAG_GATEWAY_BASE_URL", None)
        try:
            with self.assertRaises(SystemExit):
                run("answer", "--corpus", FIXTURE, "--question", "gateway", "--generator", "gateway")
        finally:
            if previous is not None:
                os.environ["RAG_GATEWAY_BASE_URL"] = previous


if __name__ == "__main__":
    unittest.main()
