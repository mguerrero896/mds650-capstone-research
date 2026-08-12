"""TDD checks for the coverage-first corrected-development builder."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import polars as pl
import pytest

from mds650.corrected_development_sources import build_exact_development_origins

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
builder = importlib.import_module("build_corrected_development_predictors")


def _hashes() -> dict[str, str]:
    """Return deterministic placeholder identities for target-free test inputs."""
    return {
        "b1q_source": "a" * 64,
        "b2_full_tape_manifest": "b" * 64,
        "fmp_source": "c" * 64,
        "study_manifest": "d" * 64,
    }


def test_coverage_first_builder_stops_on_same_day_b1q_rate(tmp_path: Path) -> None:
    """The builder emits only a source block before any target-free panel exists."""
    origins = build_exact_development_origins(("2026-03-24",), assets=("AAPL",))
    fmp_path = tmp_path / "fmp_asset_dates.parquet"
    b1q_path = tmp_path / "b1q_source.parquet"
    pl.DataFrame({"asset": ["AAPL"], "session_date": ["2026-03-24"]}).write_parquet(fmp_path)
    pl.DataFrame(
        [
            {
                "origin_id": row["origin_id"],
                "asset": row["asset"],
                "session_date": row["session_date"],
                "forecast_origin_utc": row["forecast_origin_utc"],
                "rate": 0.04,
                "rate_source_date": "2026-03-24",
                "dividend_yield": 0.0,
                "dividend_assumption": "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO",
                "b1a_complete": True,
                "b1b_complete": False,
                "b1c_complete": False,
                "b1q_atm_iv": 0.2,
                "b1q_skew": None,
                "b1q_term_structure": None,
                "b1q_max_sip_timestamp_ns": int(
                    row["forecast_origin_utc"].timestamp() * 1_000_000_000
                ),
                "b1q_quote_not_after_origin": True,
                "b1q_pit_evidence_valid": True,
            }
            for row in origins.iter_rows(named=True)
        ]
    ).write_parquet(b1q_path)
    b2_asset_dates = pl.DataFrame({"asset": ["AAPL"], "session_date": ["2026-03-24"]})

    ledger = builder.build_target_free_source_coverage(
        session_dates=("2026-03-24",),
        assets=("AAPL",),
        fmp_paths=(fmp_path,),
        b1q_path=b1q_path,
        b2_asset_dates=b2_asset_dates,
        retained_sessions=(),
        source_hashes=_hashes(),
        schema_path=(
            ROOT
            / "specs"
            / "001-pit-options-rv30"
            / "contracts"
            / "corrected-development-source-coverage-v1.schema.json"
        ),
    )

    assert ledger["status"] == "BLOCKED_SOURCE_COVERAGE"
    assert ledger["components"]["B1Q"]["unresolved_origin_count"] == 71
    assert ledger["target_binding_permitted"] is False
    assert ledger["no_target_or_metric_payload_read"] is True


def test_source_coverage_artifact_writer_is_idempotent_and_refuses_conflict(
    tmp_path: Path,
) -> None:
    """A source-block artifact is immutable after its first deterministic write."""
    output = tmp_path / "source_coverage.json"
    ledger = {"ledger_sha256": "a" * 64, "status": "BLOCKED_SOURCE_COVERAGE"}

    builder.write_source_coverage_artifact(ledger, output)
    first_bytes = output.read_bytes()
    builder.write_source_coverage_artifact(ledger, output)

    assert output.read_bytes() == first_bytes
    with pytest.raises(
        FileExistsError,
        match="CORRECTED_DEVELOPMENT_SOURCE_COVERAGE_OUTPUT_CONFLICT",
    ):
        builder.write_source_coverage_artifact(
            {"ledger_sha256": "b" * 64, "status": "BLOCKED_SOURCE_COVERAGE"},
            output,
        )


def test_full_tape_manifest_expands_a_verified_raw_session_per_asset(tmp_path: Path) -> None:
    """A verified Full Tape ZIP supports B2 source coverage without reading trade rows."""
    data_root = tmp_path / "data"
    relative_raw = Path("raw/full_tape/2026-03-24/full_tape_2026-03-24.zip")
    raw_path = data_root / relative_raw
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"x")
    batch_manifest = tmp_path / "batch_manifest.json"
    reused_manifest = tmp_path / "reused_manifest.json"
    batch_manifest.write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "session_date": "2026-03-24",
                        "status": "PASS",
                        "raw_path": relative_raw.as_posix(),
                        "bytes": 1,
                        "sha256": "a" * 64,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    reused_manifest.write_text(json.dumps({"entries": []}), encoding="utf-8")

    asset_dates = builder._full_tape_asset_dates(
        session_dates=("2026-03-24",),
        assets=("AAPL",),
        data_root=data_root,
        batch_manifest_path=batch_manifest,
        reused_manifest_path=reused_manifest,
    )

    assert asset_dates.to_dicts() == [{"asset": "AAPL", "session_date": "2026-03-24"}]


def test_default_paths_bind_only_to_local_source_evidence() -> None:
    """The command defaults to D: sources and a repository-local safe artifact."""
    args = builder.parse_args([])

    assert args.data_root == Path("D:/MDS650")
    assert args.b1q_path.as_posix().startswith("D:/MDS650/")
    assert len(args.fmp_paths) == 3
    assert all(path.as_posix().startswith("D:/MDS650/") for path in args.fmp_paths)
    assert args.output_path.parent == ROOT / "artifacts" / "corrected_development_v1"
    assert "holdout" not in args.output_path.as_posix().casefold()
