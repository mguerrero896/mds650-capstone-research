"""Acceptance checks for the bounded Pilot V2 evidence package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl
import pytest
from tests.evidence import require_evidence_root

pytestmark = pytest.mark.evidence


def _evidence_root() -> Path:
    """Return the mounted evidence package for the historical Pilot V2 run."""
    return require_evidence_root(
        "artifacts/pilot_v2/b2_feature_coverage_v2.json",
        "artifacts/pilot_v2/b2_features_v2.parquet",
        "artifacts/pilot_v2/massive_controlled_origin_probe.json",
        "artifacts/pilot_v2/b1_origin_coverage_v2.json",
        "artifacts/pilot_v2/fmp_timestamp_validation_v2.json",
        "artifacts/pilot_v2/pilot_manifest_v2.json",
        "artifacts/api_audit/common_history_probe_v2.json",
    )


def _pilot() -> Path:
    return _evidence_root() / "artifacts" / "pilot_v2"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_panel_retains_all_valid_origins_and_no_artificial_balance() -> None:
    coverage = _read_json(_pilot() / "b2_feature_coverage_v2.json")
    assert coverage["origins"] == 2840
    assert coverage["origins_with_option_activity"] + coverage[
        "origins_without_option_activity"
    ] == 2840
    assert coverage["artificial_balancing"] is False
    assert coverage["unusual_event_status"] == "NOT_CALIBRATED"


def test_option_activity_is_not_unusual_event() -> None:
    frame = pl.read_parquet(_pilot() / "b2_features_v2.parquet")
    assert frame.select(pl.col("option_activity_present").is_not_null().all()).item()
    assert frame.select(pl.col("unusual_event_status").n_unique()).item() == 1
    assert frame["unusual_event_status"][0] == "NOT_CALIBRATED"


def test_b2_continuous_fields_and_provider_cumulative_exclusion() -> None:
    frame = pl.read_parquet(_pilot() / "b2_features_v2.parquet")
    expected = {
        "option_trade_count_5m",
        "unique_contract_count_5m",
        "total_premium_5m",
        "call_put_premium_imbalance",
        "ask_side_premium_share",
        "bid_side_premium_share",
        "midpoint_premium_share",
        "implied_volatility_median",
        "missing_iv_share",
    }
    assert expected <= set(frame.columns)
    assert not {"volume", "ask_vol", "bid_vol", "mid_vol", "no_side_vol"} & set(
        frame.columns
    )


def test_massive_controlled_probe_uses_nanoseconds_and_prior_sip_quote() -> None:
    probe = _read_json(_pilot() / "massive_controlled_origin_probe.json")
    assert len(probe["results"]) == 3
    for row in probe["results"]:
        assert int(row["request_params_sanitized"]["timestamp.lte"]) > 10**18
        assert row["sip_le_origin"] is True
        assert row["rows"] == 1


def test_b1_levels_are_separate_and_iv_failures_are_preserved() -> None:
    data = _read_json(_pilot() / "b1_origin_coverage_v2.json")
    assert data["iv_attempts"] == 515
    assert data["iv_successes"] == 506
    assert len(data["iv_failures"]) == 9
    assert data["b1a_origins"] >= data["b1b_origins"] >= data["b1c_origins"]


def test_fmp_symbol_contract_and_etf_applicability() -> None:
    data = _read_json(_pilot() / "fmp_timestamp_validation_v2.json")
    rows = {row["requested_symbol"]: row for row in data["rows"]}
    assert set(rows) == {"SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"}
    assert rows["SPY"]["applicability"] == "not_applicable"
    assert rows["QQQ"]["applicability"] == "not_applicable"
    assert all(symbol in rows[symbol]["returned_symbols"] for symbol in rows)


def test_common_history_v2_uses_as_of_contracts_and_exact_sessions() -> None:
    data = _read_json(
        _evidence_root() / "artifacts" / "api_audit" / "common_history_probe_v2.json"
    )
    assert data["status"] == "COMMON_HISTORY_V2_PROBED"
    assert len(data["common_months"]) == 6
    assert all(item["common_component_pass"] for item in data["months"])
    assert data["full_history_downloaded"] is False


def test_manifest_has_no_secret_values_or_personal_paths() -> None:
    manifest_path = _pilot() / "pilot_manifest_v2.json"
    manifest = manifest_path.read_text(encoding="utf-8")
    data = _read_json(manifest_path)
    lowered = manifest.lower()
    assert "api_key" not in lowered
    assert "smtp" not in lowered
    assert "c:\\users\\" not in lowered
    assert data["secret_values_emitted"] is False
    assert data["personal_paths_emitted"] is False


def test_source_hashes_are_deterministic() -> None:
    pilot = _pilot()
    manifest = _read_json(pilot / "pilot_manifest_v2.json")
    for digest in manifest["source_reuse"]["zip_sha256"].values():
        assert len(digest) == 64
        assert all(char in "0123456789abcdef" for char in digest)
    # The generated Parquet is stable enough to identify the exact package.
    digest = hashlib.sha256((pilot / "b2_features_v2.parquet").read_bytes()).hexdigest()
    assert len(digest) == 64
