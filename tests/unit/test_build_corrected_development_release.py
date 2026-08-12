"""TDD checks for the corrected-development target-free builder shell."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
builder = importlib.import_module("build_corrected_development_release")


def test_builder_defaults_to_new_d_root_and_never_a_legacy_or_holdout_artifact() -> None:
    """Default output locations are isolated from sealed results and the OOS root."""
    args = builder.parse_args([])

    assert args.output_root.as_posix().startswith("D:/MDS650/")
    assert args.output_root.name == "corrected_development_v1"
    assert args.artifact_root.name == "corrected_development_v1"
    assert "holdout" not in args.output_root.as_posix().casefold()
    assert "legacy" not in args.artifact_root.as_posix().casefold()


def test_builder_rejects_unsafe_predictor_path_before_any_preflight(tmp_path: Path) -> None:
    """A personal or holdout-like input path cannot reach a target-free reader."""
    unsafe = tmp_path / "holdout_predictors.parquet"

    with pytest.raises(ValueError, match="CORRECTED_DEVELOPMENT_UNSAFE_PATH:predictor_panel"):
        builder.main(["--predictor-panel", str(unsafe), "--check-only"])


def test_builder_rejects_a_predictor_source_outside_the_frozen_80_sessions(
    tmp_path: Path,
) -> None:
    """A target-free source from another window cannot be relabelled as Phase 12 input."""
    source = tmp_path / "target_blind_predictors.parquet"
    pl.DataFrame({"session_date": ["2025-07-07"]}).write_parquet(source)

    with pytest.raises(
        ValueError,
        match="CORRECTED_DEVELOPMENT_PREDICTOR_SESSION_COVERAGE_MISMATCH",
    ):
        builder._validated_predictor_session_coverage(
            source,
            development_sessions=("2026-03-24",),
            holdout_sessions=("2026-07-20",),
        )
