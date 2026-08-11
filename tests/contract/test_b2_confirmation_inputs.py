"""Contract tests for the target-free confirmation input builder."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_b2_confirmation_inputs.py"
PROBE = ROOT / "artifacts" / "api_audit" / "new_blocks_availability_probe_v2.json"


def _module():
    spec = importlib.util.spec_from_file_location("b2_confirmation_inputs", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("SCRIPT_IMPORT_SPEC_MISSING")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_origin_allowlist_is_60_sessions_and_25920_rows() -> None:
    module = _module()
    dates = module._dates()
    assert len(dates) == 60
    assert dates == tuple(sorted(set(dates)))
    frame = module._origins_frame()
    assert frame.height == 25_920
    assert frame["origin_id"].n_unique() == frame.height


def test_probe_and_script_are_explicitly_target_blind_before_target_stage() -> None:
    payload = json.loads(PROBE.read_text(encoding="utf-8"))
    assert payload["pit_claim"] is False
    assert payload["full_tape_downloaded"] is False
    source = SCRIPT.read_text(encoding="utf-8")
    assert "target-free" in source
    assert "target_outcome_read\": False" in source


def test_b1_input_preserves_early_origin_missingness() -> None:
    module = _module()
    eligible, excluded, reasons = module._prepare_b1_origins()
    assert eligible.height == 23_760
    assert excluded.height == 2_160
    assert reasons == {"B0V2_UNDERLYING_HISTORY_MISSING": 2_160}
    manifest = json.loads(
        (ROOT / "artifacts" / "b2_confirmation" / "b1_input_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["total_origin_count"] == 25_920
    assert manifest["eligible_origin_count"] == 23_760
    assert manifest["excluded_origin_count"] == 2_160
    assert manifest["target_outcome_read"] is False


def test_panel_contract_maps_session_minute_for_frozen_models() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'pl.col("session_minute").alias("b0_session_minute")' in source


def test_trade_partition_date_is_attached_from_immutable_path(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "events.parquet"
    timestamp = datetime(2024, 8, 2, 14, 35, tzinfo=UTC)
    pl.DataFrame(
        {
            "underlying_symbol": ["AAPL"],
            "executed_at": [timestamp],
            "created_at": [timestamp],
            "option_chain_id": ["AAPL240809C00100000"],
            "premium": [100.0],
            "option_type": ["call"],
            "tags": [""],
            "strike": [100.0],
            "expiry": [date(2024, 8, 9)],
        }
    ).write_parquet(path)
    trades = module._load_b2_trade_partitions([path], date(2024, 8, 2))
    assert trades.get_column("session_date").to_list() == ["2024-08-02"]
