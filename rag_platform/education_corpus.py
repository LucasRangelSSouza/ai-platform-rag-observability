"""Education-demo corpus from a pinned `brazil-education-data-lake` Kaggle release.

The adapter reads a release directory that was downloaded and unpacked separately. It never
downloads anything. Every check below runs before a single record becomes a document.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .ingestion import DatasetReference, Document


@dataclass(frozen=True)
class PinnedRelease:
    slug: str
    version: int
    manifest_sha256: str
    schema_version: str = "1.1"
    landing_uri: str | None = None

    @property
    def source_uri(self) -> str:
        return self.landing_uri or f"https://www.kaggle.com/datasets/{self.slug}/versions/{self.version}"

    def reference(self) -> DatasetReference:
        return DatasetReference(self.slug, self.version, self.manifest_sha256)


UNSET_PIN = "0" * 64
EDUCATION_RELEASE_V1 = PinnedRelease(
    "lucasrangelss/brazil-education-data-lake", 1, "44f259602a688432dddbae6b0306a6957514a634d57d94a0abd3cff30f4b3506", "1.1",
)
# Checked-in synthetic package under data/education_fixture; fictional municipalities only.
SYNTHETIC_FIXTURE_RELEASE = PinnedRelease(
    "synthetic/brazil-education-data-lake-fixture", 0, "d62d141dd4a4ec832a260cca469387b99fb1a9d9e19740d4ffe2acf3d12b57b6", "1.1",
    landing_uri="fixture://data/education_fixture",
)
APPROVED_RELEASES: tuple[PinnedRelease, ...] = (EDUCATION_RELEASE_V1, SYNTHETIC_FIXTURE_RELEASE)
RELEASES = {"v1": EDUCATION_RELEASE_V1, "synthetic-fixture": SYNTHETIC_FIXTURE_RELEASE}

MANIFEST_NAME = "release_manifest.json"
SEMANTIC_PATH = "semantic/records.parquet"
AUDIT_PATH = "privacy-audit.json"
SEMANTIC_COLUMNS = (
    "id", "updated_at", "year", "municipality_code", "municipality_name", "state_code", "population",
    "total_revenue_realized", "total_expenditure_paid", "mde_minimum_share_pct",
    "fundeb_remuneration_share_pct", "fundeb_unspent_share_pct",
    "education_share_of_total_expenditure_pct", "investment_per_basic_education_student",
    "identifier_classification", "natural_key",
)
PERSON_LEVEL_FIELDS = frozenset({
    "cpf", "rg", "nis", "pis", "name", "full_name", "first_name", "last_name", "person_name",
    "student_name", "teacher_name", "supplier_name", "social_name", "email", "phone", "telephone",
    "mobile", "address", "street", "zip_code", "cep", "birth_date", "date_of_birth", "gender",
    "race", "ethnicity", "student_id", "teacher_id", "supplier_document",
})
ALLOWED_IDENTIFIER_CLASSES = frozenset({"not_present", "organization"})
MDE_MINIMUM_PCT = 25.0
FUNDEB_REMUNERATION_MINIMUM_PCT = 70.0
FUNDEB_RULE_START_YEAR = 2021


class ReleaseRejected(ValueError):
    """Raised when a release fails a pin, integrity, privacy, or schema check."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def local_name(manifest_path: str) -> str:
    """Kaggle flattens the package, so `semantic/records.parquet` arrives as `semantic_records.parquet`."""
    return manifest_path.replace("/", "_")


def verify_release(directory: Path, pin: PinnedRelease, approved: Iterable[PinnedRelease] = APPROVED_RELEASES) -> dict[str, Any]:
    if pin not in tuple(approved):
        raise ReleaseRejected(f"release {pin.slug} v{pin.version} is not an approved version")
    if pin.manifest_sha256 == UNSET_PIN:
        raise ReleaseRejected(f"release {pin.slug} v{pin.version} has no recorded manifest hash yet")
    manifest_file = directory / MANIFEST_NAME
    if not manifest_file.is_file():
        raise ReleaseRejected(f"{MANIFEST_NAME} is missing")
    if sha256_file(manifest_file) != pin.manifest_sha256:
        raise ReleaseRejected("manifest SHA-256 does not match the pinned release")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != pin.schema_version:
        raise ReleaseRejected(f"manifest schema_version must be {pin.schema_version}")
    if manifest.get("privacy_gate") != "passed":
        raise ReleaseRejected("manifest privacy_gate is not passed")
    listed = {entry.get("path") for entry in manifest.get("files", [])}
    for required in (SEMANTIC_PATH, AUDIT_PATH):
        if required not in listed:
            raise ReleaseRejected(f"manifest does not list {required}")
    for entry in manifest["files"]:
        _verify_file(directory, entry)
    audit = json.loads((directory / local_name(AUDIT_PATH)).read_text(encoding="utf-8"))
    if audit.get("privacy_gate") != "passed" or audit.get("violations"):
        raise ReleaseRejected("privacy audit did not pass")
    return manifest


def _verify_file(directory: Path, entry: dict[str, Any]) -> None:
    path = directory / local_name(str(entry["path"]))
    if not path.is_file():
        raise ReleaseRejected(f"release file {path.name} is missing")
    if sha256_file(path) != entry.get("sha256"):
        raise ReleaseRejected(f"release file {path.name} does not match its manifest SHA-256")
    if "bytes" in entry and path.stat().st_size != int(entry["bytes"]):
        raise ReleaseRejected(f"release file {path.name} does not match its manifest size")


def check_columns(columns: Iterable[str]) -> None:
    present = list(columns)
    person_level = sorted(PERSON_LEVEL_FIELDS.intersection(column.casefold() for column in present))
    if person_level:
        raise ReleaseRejected(f"person-level field blocks ingestion: {person_level[0]}")
    unknown = sorted(set(present) - set(SEMANTIC_COLUMNS))
    if unknown:
        raise ReleaseRejected(f"unknown column blocks ingestion: {unknown[0]}")
    missing = [column for column in SEMANTIC_COLUMNS if column not in present]
    if missing:
        raise ReleaseRejected(f"required column is missing: {missing[0]}")


def read_semantic_records(directory: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as parquet

    table = parquet.read_table(directory / local_name(SEMANTIC_PATH))
    check_columns(table.column_names)
    records = table.to_pylist()
    for record in records:
        if record["identifier_classification"] not in ALLOWED_IDENTIFIER_CLASSES:
            raise ReleaseRejected(f"record {record['id']} has a disallowed identifier_classification")
        if not record.get("id"):
            raise ReleaseRejected("a semantic record has no id and cannot be cited")
    return records


def _money(value: Any) -> str | None:
    return None if value is None else f"BRL {float(value):,.2f}"


def _pct(value: Any) -> str | None:
    return None if value is None else f"{float(value):.2f}%"


def _comparison(value: Any, minimum: float) -> str:
    return "at or above" if float(value) >= minimum else "below"


def year_sentences(record: dict[str, Any]) -> list[str]:
    name, year = record["municipality_name"], int(record["year"])
    prefix = f"In {year}, {name}"
    sentences = []
    if record["population"] is not None:
        sentences.append(f"{prefix} had a population of {int(record['population']):,}.")
    revenue, expenditure = _money(record["total_revenue_realized"]), _money(record["total_expenditure_paid"])
    if revenue or expenditure:
        sentences.append(
            f"{prefix} reported municipality-wide total revenue realized of {revenue or 'not reported'} and "
            f"municipality-wide total expenditure paid of {expenditure or 'not reported'}, covering all functions, not only education."
        )
    mde = record["mde_minimum_share_pct"]
    if mde is not None:
        sentences.append(
            f"{prefix} applied {_pct(mde)} of tax revenue, including transfers, to maintenance and development of education (MDE), "
            f"{_comparison(mde, MDE_MINIMUM_PCT)} the constitutional minimum of 25%."
        )
    fundeb = record["fundeb_remuneration_share_pct"]
    if fundeb is not None:
        rule = (
            f"{_comparison(fundeb, FUNDEB_REMUNERATION_MINIMUM_PCT)} the 70% minimum that applies from 2021"
            if year >= FUNDEB_RULE_START_YEAR
            else "declared before the 70% minimum took effect in 2021"
        )
        sentences.append(f"{prefix} spent {_pct(fundeb)} of FUNDEB funds on education professional remuneration, {rule}.")
    if record["fundeb_unspent_share_pct"] is not None:
        sentences.append(f"{prefix} left {_pct(record['fundeb_unspent_share_pct'])} of FUNDEB funds unspent.")
    if record["education_share_of_total_expenditure_pct"] is not None:
        sentences.append(f"{prefix} devoted {_pct(record['education_share_of_total_expenditure_pct'])} of total expenditure to education.")
    if record["investment_per_basic_education_student"] is not None:
        sentences.append(f"{prefix} invested {_money(record['investment_per_basic_education_student'])} per basic education student.")
    if not sentences:
        sentences.append(f"{prefix} has no reported indicator values in this release.")
    return sentences


def municipality_documents(records: list[dict[str, Any]], pin: PinnedRelease, license_note: str) -> list[Document]:
    by_municipality: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_municipality[str(record["municipality_code"])].append(record)
    documents = []
    for code in sorted(by_municipality):
        rows = sorted(by_municipality[code], key=lambda row: int(row["year"]))
        first = rows[0]
        heading = (
            f"{first['municipality_name']} ({first['state_code']}), IBGE municipality code {code}, education finance "
            f"indicators. Values are as declared to SIOPE, not audited."
        )
        body = " ".join(sentence for row in rows for sentence in year_sentences(row))
        documents.append(Document(
            id=f"municipality-{code}",
            title=f"{first['municipality_name']} ({first['state_code']}) education finance",
            text=f"{heading} {body}",
            source_uri=pin.source_uri,
            license_note=license_note,
            dataset=pin.reference(),
            record_ids=tuple(str(row["id"]) for row in rows),
        ))
    return documents


def license_note(manifest: dict[str, Any]) -> str:
    declared = manifest.get("license")
    return str(declared) if declared else "Derived from public FNDE SIOPE and IBGE data; credit FNDE and IBGE; see the dataset card for terms."


def dataset_card_document(records: list[dict[str, Any]], manifest: dict[str, Any], pin: PinnedRelease) -> Document:
    years = sorted({int(record["year"]) for record in records})
    municipalities = {str(record["municipality_code"]) for record in records}
    year_span = f"{years[0]} to {years[-1]}" if years else "no years"
    text = (
        f"The dataset {pin.slug} version {pin.version} holds municipal education finance indicators declared by "
        f"source {manifest.get('source_id', 'unknown')} ({manifest.get('source_url', 'no source URL')}), with manifest "
        f"SHA-256 {pin.manifest_sha256} and schema version {pin.schema_version}. "
        f"Its semantic layer holds {len(records)} municipality-year records for {len(municipalities)} municipalities "
        f"covering {year_span}. The release passed its privacy gate and the adapter found no person-level fields. "
        f"Columns are {', '.join(SEMANTIC_COLUMNS)}. "
        f"Values are as declared to SIOPE, not audited, and individual declarations may be implausible. "
        f"Total revenue realized and total expenditure paid are municipality-wide totals, not education spending. "
        f"The MDE indicator is compared with the constitutional minimum of 25% of tax revenue. "
        f"The FUNDEB remuneration indicator is compared with the 70% minimum that applies from 2021."
    )
    return Document(
        id="dataset-card",
        title=f"{pin.slug} v{pin.version} dataset card",
        text=text,
        source_uri=pin.source_uri,
        license_note=license_note(manifest),
        dataset=pin.reference(),
        record_ids=(),
    )


def load_education_corpus(
    directory: Path,
    pin: PinnedRelease = EDUCATION_RELEASE_V1,
    approved: Iterable[PinnedRelease] = APPROVED_RELEASES,
) -> list[Document]:
    manifest = verify_release(directory, pin, approved)
    records = read_semantic_records(directory)
    documents = municipality_documents(records, pin, license_note(manifest)) + [dataset_card_document(records, manifest, pin)]
    for document in documents:
        if document.dataset is None or document.dataset.slug != pin.slug:
            raise ReleaseRejected(f"document {document.id} has no dataset citation")
        if document.id != "dataset-card" and not document.record_ids:
            raise ReleaseRejected(f"document {document.id} has no record citation")
    return documents
