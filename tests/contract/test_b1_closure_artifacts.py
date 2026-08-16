"""Contract checks for the controlled B1 closure artifacts."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import polars as pl
import pytest
from tests.evidence import require_evidence_root

pytestmark = pytest.mark.evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _evidence_root() -> Path:
    """Return the mounted evidence package for the historical B1 closure."""
    return require_evidence_root(
        "artifacts/b1_full_origin/b1_origin_matrix.parquet",
        "artifacts/b1_full_origin/b1_coverage_summary.json",
        "artifacts/b1_full_origin/evidence_index.csv",
        "artifacts/b1_full_origin/test_report.txt",
        "artifacts/api_audit/common_history_all_assets_v3.json",
    )


def _out() -> Path:
    return _evidence_root() / "artifacts" / "b1_full_origin"


def _massive_cache_index() -> Path:
    """Return the on-disk massive contract-day cache index for the closure run.

    The closure reused the pilot massive contract-day cache; the byte-original
    index lives on the bulk-data drive, not inside the mounted evidence root.
    """
    _evidence_root()  # Explicit evidence opt-in gates this historical check.
    data_root = Path(os.environ.get("MDS650_DATA_ROOT", "D:/MDS650"))
    path = data_root / "cache" / "massive" / "pilot_v2" / "cache_index.json"
    if not path.is_file():
        pytest.fail("MDS650_MASSIVE_CACHE_INDEX_MISSING")
    return path


def test_b1_matrix_keeps_all_pilot_origins() -> None:
    frame = pl.read_parquet(_out() / "b1_origin_matrix.parquet")
    assert frame.height == 2840
    assert frame.get_column("origin_id").n_unique() == 2840
    assert frame.get_column("b1q_complete").mean() >= 0.70
    assert frame.get_column("b1c_complete").mean() <= frame.get_column("b1b_complete").mean()


def test_b1q_and_b1t_are_explicitly_distinct() -> None:
    out = _out()
    frame = pl.read_parquet(out / "b1_origin_matrix.parquet")
    assert {"b1q_atm_iv", "b1t_atm_iv", "b1q_complete", "b1t_complete"} <= set(frame.columns)
    summary = json.loads((out / "b1_coverage_summary.json").read_text(encoding="utf-8"))
    assert summary["b1t_route"]["independent_of_b2"] is False


def test_common_history_has_all_assets_and_dates() -> None:
    payload = json.loads(
        (_evidence_root() / "artifacts/api_audit/common_history_all_assets_v3.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(payload["records"]) == 48
    assert all(row["common_pass"] for row in payload["records"])
    assert payload["monthly_points_do_not_prove_daily_continuity"] is True


def test_literature_matrix_has_ten_rows_and_stable_identifiers() -> None:
    with (REPOSITORY_ROOT / "docs/literature_matrix.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    assert len({row["study_id"] for row in rows}) == 10
    assert all(
        row["doi_or_stable_url"].startswith(("https://doi.org/", "https://")) for row in rows
    )
    assert all(2023 <= int(row["year"]) <= 2026 for row in rows)


def test_sanitized_evidence_has_no_secret_or_personal_path() -> None:
    out = _out()
    for path in (out / "evidence_index.csv", out / "test_report.txt"):
        text = path.read_text(encoding="utf-8").lower()
        assert "api_key=" not in text
        assert "c:\\users\\mguer" not in text


def test_cache_index_has_unique_idempotency_keys() -> None:
    payload = json.loads(_massive_cache_index().read_text(encoding="utf-8"))
    entries = payload["entries"]
    keys = [
        (entry["asset"], entry["day"], entry["contract"], entry["source_request_hash"])
        for entry in entries
    ]
    assert len(keys) == len(set(keys))
    assert all(len(entry["source_request_hash"]) == 64 for entry in entries)
