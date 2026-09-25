"""Synthetic education release packages for tests and the offline demo.

Municipality codes start with 99 and the state code is ZZ, neither of which exists in the
IBGE register, so synthetic rows cannot be mistaken for real municipalities.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from .education_corpus import MANIFEST_NAME, SEMANTIC_COLUMNS, PinnedRelease, local_name, sha256_file


SYNTHETIC_MUNICIPALITIES = (
    ("9900001", "Vale Azul", 18250),
    ("9900002", "Serra Clara", 64410),
    ("9900003", "Porto Sereno", 7120),
)


def synthetic_records(years: Sequence[int] = (2020, 2021, 2022)) -> list[dict[str, Any]]:
    records = []
    for index, (code, name, population) in enumerate(SYNTHETIC_MUNICIPALITIES):
        for offset, year in enumerate(years):
            records.append({
                "id": f"{code}-{year}",
                "updated_at": f"{year + 1}-03-31T00:00:00Z",
                "year": year,
                "municipality_code": code,
                "municipality_name": name,
                "state_code": "ZZ",
                "population": population + 100 * offset,
                "total_revenue_realized": 50_000_000.0 * (index + 1) + 1_250_000.0 * offset,
                "total_expenditure_paid": 47_500_000.0 * (index + 1) + 1_100_000.0 * offset,
                "mde_minimum_share_pct": round(23.5 + 1.25 * index + 0.5 * offset, 2),
                "fundeb_remuneration_share_pct": round(66.0 + 3.0 * index + 1.5 * offset, 2),
                "fundeb_unspent_share_pct": round(4.0 - 1.0 * index - 0.25 * offset, 2),
                "education_share_of_total_expenditure_pct": round(27.0 + 2.0 * index + 0.4 * offset, 2),
                "investment_per_basic_education_student": round(7_800.0 + 450.0 * index + 210.0 * offset, 2),
                "identifier_classification": "not_present",
                "natural_key": f"{code}|{year}",
            })
    return records


def _write_parquet(path: Path, records: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as parquet

    table = pa.table({column: [record.get(column) for record in records] for column in columns})
    parquet.write_table(table, path)


def write_release(
    directory: Path,
    records: Sequence[dict[str, Any]],
    slug: str,
    version: int,
    columns: Sequence[str] = SEMANTIC_COLUMNS,
    privacy_gate: str = "passed",
    schema_version: str = "1.1",
) -> PinnedRelease:
    """Write a Kaggle-flattened package and return the pin that matches it."""
    directory.mkdir(parents=True, exist_ok=True)
    layers = {"raw/records.parquet": records, "trusted/records.parquet": records, "semantic/records.parquet": records}
    for path, rows in layers.items():
        _write_parquet(directory / local_name(path), rows, columns)
    audit = {"privacy_gate": privacy_gate, "record_counts": {"raw": len(records), "trusted": len(records), "semantic": len(records)}, "violations": []}
    (directory / "privacy-audit.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    files = []
    for path in sorted([*layers, "privacy-audit.json"]):
        local = directory / local_name(path)
        files.append({"path": path, "sha256": sha256_file(local), "bytes": local.stat().st_size})
    manifest = {
        "schema_version": schema_version,
        "source_id": "fnde-siope",
        "source_url": "https://www.fnde.gov.br/siope/",
        "retrieved_at": "2026-01-01T00:00:00Z",
        "files": files,
        "privacy_gate": privacy_gate,
        "row_counts": {"raw": len(records), "trusted": len(records), "semantic": len(records)},
        "distribution_version": str(version),
        "license": "Synthetic records generated for tests; Apache-2.0.",
    }
    (directory / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return PinnedRelease(slug, version, sha256_file(directory / MANIFEST_NAME), schema_version)
