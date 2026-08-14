"""CLI contract for the canonical target-blind common predictor panel."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_b1v3_confirmation_common import _arguments  # noqa: E402


def test_cli_defaults_bind_all_three_predictor_sources() -> None:
    args = _arguments([])

    assert args.origins.name == "forecast_origins_target_blind.parquet"
    assert args.b0.name == "b0_target_blind.parquet"
    assert args.b1_source_manifest.name == "b1q_source_manifest.json"
    assert args.b1.name == "b1v3_features.parquet"
    assert args.b2.name == "b2_primary_target_blind.parquet"
    assert args.output == Path(
        "D:/MDS650/b1v3_confirmation/predictors/common_predictor_panel.parquet"
    )
    assert args.manifest.name == "common_predictor_manifest.json"
    assert args.manifest_schema.name == (
        "b1v3-confirmation-common-predictor-v1.schema.json"
    )
