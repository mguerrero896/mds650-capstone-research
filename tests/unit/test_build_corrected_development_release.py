"""TDD checks for the corrected-development target-free builder shell."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

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
