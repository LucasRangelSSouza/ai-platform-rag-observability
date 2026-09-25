import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from rag_platform.education_corpus import (
    APPROVED_RELEASES,
    EDUCATION_RELEASE_V1,
    SEMANTIC_COLUMNS,
    SYNTHETIC_FIXTURE_RELEASE,
    PinnedRelease,
    ReleaseRejected,
    load_education_corpus,
    sha256_file,
    year_sentences,
)
from rag_platform.evaluation import education_cases, evaluate_abstention, evaluate_retrieval
from rag_platform.service import build_service
from rag_platform.synthetic_release import synthetic_records, write_release


SLUG = "test/brazil-education-data-lake"
REPO = Path(__file__).resolve().parents[1]


class SyntheticRelease:
    """A temporary Kaggle-flattened package plus the pin and approval list that match it."""

    def __init__(self, records=None, **options):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name)
        self.records = records if records is not None else synthetic_records()
        self.pin = write_release(self.path, self.records, SLUG, 3, **options)

    def load(self, pin: PinnedRelease | None = None, approved=None):
        pin = pin or self.pin
        return load_education_corpus(self.path, pin, approved if approved is not None else (self.pin,))

    def rewrite_manifest(self, change) -> None:
        manifest_path = self.path / "release_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        change(manifest)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.pin = replace(self.pin, manifest_sha256=sha256_file(manifest_path))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.directory.cleanup()


class PinTests(unittest.TestCase):
    def test_v1_pin_is_the_published_release(self):
        self.assertEqual((EDUCATION_RELEASE_V1.slug, EDUCATION_RELEASE_V1.version, EDUCATION_RELEASE_V1.schema_version), ("lucasrangelss/brazil-education-data-lake", 1, "1.1"))
        self.assertEqual(EDUCATION_RELEASE_V1.manifest_sha256, "44f259602a688432dddbae6b0306a6957514a634d57d94a0abd3cff30f4b3506")
        self.assertIn(EDUCATION_RELEASE_V1, APPROVED_RELEASES)

    def test_approved_release_builds_a_cited_corpus(self):
        with SyntheticRelease() as release:
            documents = release.load()
        self.assertEqual([doc.id for doc in documents], ["municipality-9900001", "municipality-9900002", "municipality-9900003", "dataset-card"])
        for document in documents:
            self.assertEqual((document.dataset.slug, document.dataset.version), (SLUG, 3))
        self.assertEqual(documents[0].record_ids, ("9900001-2020", "9900001-2021", "9900001-2022"))

    def test_unapproved_version_is_rejected(self):
        with SyntheticRelease() as release:
            with self.assertRaisesRegex(ReleaseRejected, "not an approved version"):
                release.load(replace(release.pin, version=4), approved=(release.pin,))

    def test_default_approval_list_rejects_an_unlisted_release(self):
        with SyntheticRelease() as release:
            with self.assertRaisesRegex(ReleaseRejected, "not an approved version"):
                load_education_corpus(release.path, release.pin)

    def test_unset_pin_is_rejected(self):
        with SyntheticRelease() as release:
            unset = replace(release.pin, manifest_sha256="0" * 64)
            with self.assertRaisesRegex(ReleaseRejected, "no recorded manifest hash"):
                release.load(unset, approved=(unset,))

    def test_manifest_hash_mismatch_is_rejected(self):
        with SyntheticRelease() as release:
            stale_pin = release.pin
            release.rewrite_manifest(lambda manifest: manifest.update({"retrieved_at": "2026-02-02T00:00:00Z"}))
            with self.assertRaisesRegex(ReleaseRejected, "manifest SHA-256"):
                release.load(stale_pin, approved=(stale_pin,))


class IntegrityTests(unittest.TestCase):
    def test_tampered_data_file_is_rejected(self):
        with SyntheticRelease() as release:
            with (release.path / "semantic_records.parquet").open("ab") as handle:
                handle.write(b"tamper")
            with self.assertRaisesRegex(ReleaseRejected, "semantic_records.parquet does not match"):
                release.load()

    def test_missing_listed_file_is_rejected(self):
        with SyntheticRelease() as release:
            (release.path / "trusted_records.parquet").unlink()
            with self.assertRaisesRegex(ReleaseRejected, "trusted_records.parquet is missing"):
                release.load()

    def test_failed_privacy_gate_is_rejected(self):
        with SyntheticRelease(privacy_gate="failed") as release:
            with self.assertRaisesRegex(ReleaseRejected, "privacy_gate"):
                release.load()

    def test_wrong_schema_version_is_rejected(self):
        with SyntheticRelease(schema_version="1.0") as release:
            pin = replace(release.pin, schema_version="1.1")
            with self.assertRaisesRegex(ReleaseRejected, "schema_version"):
                release.load(pin, approved=(pin,))

    def test_manifest_without_semantic_layer_is_rejected(self):
        with SyntheticRelease() as release:
            release.rewrite_manifest(lambda manifest: manifest.update({"files": [item for item in manifest["files"] if item["path"] != "semantic/records.parquet"]}))
            with self.assertRaisesRegex(ReleaseRejected, "does not list semantic/records.parquet"):
                release.load()


class FieldBoundaryTests(unittest.TestCase):
    def test_person_level_field_blocks_ingestion(self):
        for field in ("cpf", "email", "phone", "address", "name", "student_name"):
            with self.subTest(field=field):
                records = [{**record, field: "value"} for record in synthetic_records()]
                with SyntheticRelease(records, columns=(*SEMANTIC_COLUMNS, field)) as release:
                    with self.assertRaisesRegex(ReleaseRejected, f"person-level field blocks ingestion: {field}"):
                        release.load()

    def test_unknown_column_blocks_ingestion(self):
        records = [{**record, "free_text_justification": "x"} for record in synthetic_records()]
        with SyntheticRelease(records, columns=(*SEMANTIC_COLUMNS, "free_text_justification")) as release:
            with self.assertRaisesRegex(ReleaseRejected, "unknown column"):
                release.load()

    def test_missing_column_blocks_ingestion(self):
        columns = tuple(column for column in SEMANTIC_COLUMNS if column != "natural_key")
        with SyntheticRelease(columns=columns) as release:
            with self.assertRaisesRegex(ReleaseRejected, "required column is missing: natural_key"):
                release.load()

    def test_natural_person_identifier_class_blocks_ingestion(self):
        records = synthetic_records()
        records[0]["identifier_classification"] = "natural_person"
        with SyntheticRelease(records) as release:
            with self.assertRaisesRegex(ReleaseRejected, "identifier_classification"):
                release.load()

    def test_record_without_id_cannot_be_cited(self):
        records = synthetic_records()
        records[0]["id"] = ""
        with SyntheticRelease(records) as release:
            with self.assertRaisesRegex(ReleaseRejected, "no id"):
                release.load()


class DocumentTextTests(unittest.TestCase):
    def test_sentences_state_values_and_statutory_minimums(self):
        text = " ".join(year_sentences(synthetic_records()[2]))
        self.assertIn("In 2022, Vale Azul applied 24.50% of tax revenue", text)
        self.assertIn("below the constitutional minimum of 25%", text)
        self.assertIn("below the 70% minimum that applies from 2021", text)
        self.assertIn("municipality-wide total expenditure paid of BRL 49,700,000.00", text)

    def test_pre_2021_fundeb_value_is_not_judged_against_the_2021_rule(self):
        text = " ".join(year_sentences(synthetic_records()[0]))
        self.assertIn("declared before the 70% minimum took effect in 2021", text)

    def test_implausible_declared_values_are_rendered_as_declared(self):
        record = {**synthetic_records()[1], "mde_minimum_share_pct": -4.01, "education_share_of_total_expenditure_pct": 12345.6}
        text = " ".join(year_sentences(record))
        self.assertIn("applied -4.01% of tax revenue", text)
        self.assertIn("devoted 12345.60% of total expenditure", text)

    def test_missing_values_are_omitted_not_invented(self):
        record = {**synthetic_records()[1], **{key: None for key in SEMANTIC_COLUMNS[6:14]}}
        self.assertEqual(year_sentences(record), ["In 2021, Vale Azul has no reported indicator values in this release."])

    def test_documents_carry_the_as_declared_caveat_and_dataset_card(self):
        with SyntheticRelease() as release:
            documents = release.load()
        self.assertIn("as declared to SIOPE, not audited", documents[0].text)
        card = documents[-1]
        self.assertIn(release.pin.manifest_sha256, card.text)
        self.assertIn("9 municipality-year records for 3 municipalities covering 2020 to 2022", card.text)


class EducationEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.release = SyntheticRelease()
        self.service = build_service(self.release.load())

    def tearDown(self):
        self.release.directory.cleanup()

    def test_answers_cite_dataset_version_and_record_ids(self):
        result = self.service.answer("What was the population of Serra Clara in 2021?")
        self.assertEqual(result["status"], "answered")
        citation = result["citations"][0]
        self.assertEqual((citation["dataset"]["slug"], citation["dataset"]["version"]), (SLUG, 3))
        self.assertIn("9900002-2021", citation["record_ids"])
        self.assertIn("64,510", result["answer"])

    def test_derived_cases_reach_full_recall_and_citation_coverage(self):
        cases = education_cases(self.release.records)
        self.assertEqual(len(cases), 7)
        metrics = evaluate_retrieval(self.service, cases, k=3)
        self.assertEqual((metrics["recall_at_k"], metrics["citation_coverage"]), (1.0, 1.0))

    def test_abstention_set_exposes_the_unknown_entity_failure(self):
        metrics = evaluate_abstention(self.service)
        self.assertEqual(metrics["correct_abstention_rate"], round(5 / 6, 6))
        failed = [case["question"] for case in metrics["cases"] if not case["correct"]]
        self.assertEqual(failed, ["What share of tax revenue did Atlantis apply to MDE in 2022?"])

    def test_case_sampling_is_deterministic_and_bounded(self):
        cases = education_cases(self.release.records, max_municipalities=2)
        self.assertEqual([case["id"] for case in cases], ["9900001-mde", "9900001-population", "9900002-mde", "9900002-population", "dataset-card"])


class CheckedInFixtureTests(unittest.TestCase):
    def test_checked_in_synthetic_release_matches_its_pin(self):
        documents = load_education_corpus(REPO / "data" / "education_fixture", SYNTHETIC_FIXTURE_RELEASE)
        self.assertEqual(len(documents), 4)


if __name__ == "__main__":
    unittest.main()
