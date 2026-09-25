"""Rebuild the checked-in synthetic education release and print its manifest SHA-256.

The printed hash must match `SYNTHETIC_FIXTURE_RELEASE.manifest_sha256`. Parquet bytes depend
on the pyarrow version, so rebuilding with another version requires updating that pin.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_platform.education_corpus import SYNTHETIC_FIXTURE_RELEASE  # noqa: E402
from rag_platform.synthetic_release import synthetic_records, write_release  # noqa: E402


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "data" / "education_fixture"
    shutil.rmtree(target, ignore_errors=True)
    pin = write_release(target, synthetic_records(), SYNTHETIC_FIXTURE_RELEASE.slug, SYNTHETIC_FIXTURE_RELEASE.version)
    print(pin.manifest_sha256)


if __name__ == "__main__":
    main()
