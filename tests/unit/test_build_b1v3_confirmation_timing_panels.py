"""CLI contract for source-bound B1v3 timing common panels."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_b1v3_confirmation_timing_panels import _arguments  # noqa: E402


def test_timing_panel_cli_freezes_all_five_inputs_on_d_drive() -> None:
    args = _arguments([])

    assert args.fmp_b0 == Path(
        "D:/MDS650/b1v3_confirmation/predictors/timing/fmp_delay_2/b0.parquet"
    )
    assert args.massive_60_b1.name == "b1v3_features.parquet"
    assert args.massive_300_b1.name == "b1v3_features.parquet"
    assert args.uw_120_b2.name == "b2_latency_5m_120s_target_blind.parquet"
    assert args.uw_300_b2.name == "b2_latency_5m_300s_target_blind.parquet"
    assert args.manifest_schema.name == "b1v3-confirmation-timing-panels-v1.schema.json"
