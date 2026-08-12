"""Contract checks for the bounded authenticated audit artifact."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from mds650.manifests import load_and_validate_audit_manifest

MANIFEST = (
    Path(__file__).parents[2]
    / "artifacts"
    / "api_audit"
    / "authenticated_v1"
    / "provider_audit_manifest.json"
)
CORRECTED_MANIFEST = MANIFEST.parent.parent / "authenticated_v1j" / "provider_audit_manifest.json"
LATEST_MANIFEST = MANIFEST.parent.parent / "authenticated_v1r" / "provider_audit_manifest.json"
V1S_MANIFEST = MANIFEST.parent.parent / "authenticated_v1s" / "provider_audit_manifest.json"
V1V_MANIFEST = MANIFEST.parent.parent / "authenticated_v1v" / "provider_audit_manifest.json"
V1W_MANIFEST = MANIFEST.parent.parent / "authenticated_v1w" / "provider_audit_manifest.json"
V1X_MANIFEST = MANIFEST.parent.parent / "authenticated_v1x" / "provider_audit_manifest.json"
ASSETS = {"SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"}


def _document() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_authenticated_manifest_is_schema_one_point_one_and_sanitized() -> None:
    document = _document()
    assert document["schema_version"] == "1.1"
    assert document["research_only"] is True
    assert document["secrets_present"] is True
    assert document["secret_values_emitted"] is False
    validation = load_and_validate_audit_manifest(MANIFEST)
    assert validation.sanitized is True
    assert validation.authorized_for_backfill is False
    assert "B1_NOT_AUTHORIZED" in validation.blockers


def test_authenticated_manifest_covers_eight_assets_and_separates_pit_state() -> None:
    records = _document()["provider_results"]
    assert isinstance(records, list)
    fmp_assets = {
        record["asset"]
        for record in records
        if record["provider"] == "fmp" and record["component"] == "underlying_1min"
    }
    uw_assets = {
        record["asset"]
        for record in records
        if record["provider"] == "unusual_whales" and record["component"] == "unusual_option_events"
    }
    assert fmp_assets == ASSETS
    assert uw_assets == ASSETS
    event_records = [
        record
        for record in records
        if record["provider"] == "unusual_whales" and record["component"] == "unusual_option_events"
    ]
    assert any(record["event_iv_fields_present"] for record in event_records)
    assert all(
        record["ordinary_option_state_pit_verified"] != "verified" for record in event_records
    )


def test_authenticated_manifest_identity_and_hashes_are_unique() -> None:
    records = _document()["provider_results"]
    assert isinstance(records, list)
    keys = [record["record_key"] for record in records]
    hashes = [item for record in records for item in record["raw_response_hashes"]]
    assert len(keys) == len(set(keys))
    assert len(hashes) == len(set(hashes))
    assert Counter(record["provider"] for record in records) == Counter(
        {"fmp": 27, "unusual_whales": 13, "massive": 3}
    )


def test_authenticated_manifest_has_no_secret_values_or_personal_paths() -> None:
    serialized = MANIFEST.read_text(encoding="utf-8")
    assert "UNUSUALWHALES_API_KEY" not in serialized
    assert "MASSIVE_API_KEY" not in serialized
    assert "FMP_API_KEY" not in serialized
    assert "C:\\Users\\mguer" not in serialized
    assert "AppData" not in serialized
    assert "restricted://MDS650/raw" in serialized


def test_corrected_massive_probe_records_current_contract_format() -> None:
    document = json.loads(CORRECTED_MANIFEST.read_text(encoding="utf-8"))
    records = document["provider_results"]
    massive = [record for record in records if record["provider"] == "massive"]
    assert len(massive) == 3
    assert {record["http_status"] for record in massive} == {200}
    assert {record["contract_id"] for record in massive} == {"O:SPXW260724P07400000"}
    assert document["cross_provider_summary"]["massive_directed_trade_statuses"] == ["200:1"]
    assert document["cross_provider_summary"]["massive_directed_quote_statuses"] == ["200:1"]
    validation = load_and_validate_audit_manifest(CORRECTED_MANIFEST)
    assert "MASSIVE_NOT_AUTHORIZED" not in validation.blockers
    assert validation.authorized_for_backfill is False


def test_v1j_records_ordinary_state_coverage_without_upgrading_pit() -> None:
    document = json.loads(CORRECTED_MANIFEST.read_text(encoding="utf-8"))
    records = document["provider_results"]
    ordinary = [
        record
        for record in records
        if record["provider"] == "unusual_whales" and record["component"] == "ordinary_option_state"
    ]
    term_structure = [
        record
        for record in ordinary
        if record.get("ordinary_option_state_fields_present")
        and "term-structure" in record["request_id"]
    ]
    assert {record["asset"] for record in term_structure} == ASSETS
    assert all(record["ordinary_option_state_pit_verified"] != "verified" for record in ordinary)
    assert any(record.get("rows", 0) == 0 for record in ordinary)


def test_v1j_records_calendar_sessions_without_claiming_timestamp_semantics() -> None:
    """Calendar diagnostics must expose session gaps separately from minute gaps."""
    document = json.loads(CORRECTED_MANIFEST.read_text(encoding="utf-8"))
    summary = document["cross_provider_summary"]
    assert summary["fmp_calendar_cases"] == ["dst", "early-close", "summer", "winter"]
    dst = next(
        record
        for record in document["provider_results"]
        if record.get("request_id") == "fmp-calendar-dst-spy"
    )
    assert dst["missing_session_dates"] == ["2026-03-06"]
    assert dst["missing_minute_candidates"] == ["2026-03-09 15:19:00"]
    assert "start-versus-close semantics remain unresolved" in dst["calendar_label_assumption"]
    summer = next(
        record
        for record in document["provider_results"]
        if record.get("request_id") == "fmp-calendar-summer-spy"
    )
    assert summer["missing_session_dates"] == ["2026-07-13"]
    early_close = next(
        record
        for record in document["provider_results"]
        if record.get("request_id") == "fmp-calendar-early-close-spy"
    )
    assert early_close["regular_session_expected_rows"] == 210
    assert early_close["completeness_ratio"] == 1


def test_v1r_massive_probe_records_pagination_schema_and_empty_window() -> None:
    """Latest directed Massive evidence must expose contract-level fields and paging."""
    document = json.loads(LATEST_MANIFEST.read_text(encoding="utf-8"))
    massive = [record for record in document["provider_results"] if record["provider"] == "massive"]
    assert len(massive) == 5
    trades = next(record for record in massive if record["component"] == "contract_trades")
    assert trades["rows"] > 0
    assert {"conditions", "sip_timestamp", "price", "size"}.issubset(trades["schema_fields"])
    quotes = [record for record in massive if record["component"] == "contract_quotes"]
    assert len(quotes) == 3
    assert quotes[0]["pagination"]["status"] == "pass"
    assert {"bid_price", "ask_price", "bid_size", "ask_size"}.issubset(quotes[0]["schema_fields"])
    assert any(record["rows"] == 0 for record in quotes)
    validation = load_and_validate_audit_manifest(LATEST_MANIFEST)
    assert validation.authorized_for_backfill is False


def test_v1s_refresh_preserves_hard_blockers_and_idempotent_keys() -> None:
    """The newest bounded refresh is valid evidence but cannot authorize backfill."""
    document = json.loads(V1S_MANIFEST.read_text(encoding="utf-8"))
    records = document["provider_results"]
    assert len(records) == 59
    assert len({record["record_key"] for record in records}) == 59
    validation = load_and_validate_audit_manifest(V1S_MANIFEST)
    assert validation.sanitized is True
    assert validation.authorized_for_backfill is False
    assert {
        "B1_NOT_AUTHORIZED",
        "COMMON_HISTORY_NOT_ESTABLISHED",
        "PROVIDER_FAILURES_PRESENT",
    }.issubset(validation.blockers)


def test_v1v_corrected_calls_remove_provider_failure_blocker() -> None:
    """Correct provider parameters leave only the unresolved research gates."""
    validation = load_and_validate_audit_manifest(V1V_MANIFEST)
    assert validation.sanitized is True
    assert validation.authorized_for_backfill is False
    assert validation.blockers == ("B1_NOT_AUTHORIZED", "COMMON_HISTORY_NOT_ESTABLISHED")


def test_v1w_records_fmp_exchange_timezone_without_claiming_bar_semantics() -> None:
    """FMP's local timezone is documented; start-versus-close remains unresolved."""
    document = json.loads(V1W_MANIFEST.read_text(encoding="utf-8"))
    record = next(
        item
        for item in document["provider_results"]
        if item["request_id"] == "fmp-minute-regular-spy"
    )
    timestamp = record["timestamp_fields"][0]
    assert timestamp["timezone"].startswith("America/New_York")
    assert "start-versus-close unresolved" in timestamp["semantics"]


def test_v1x_derives_b1_and_common_history_states() -> None:
    """The refreshed audit must derive states and clear provider/common-history failures."""
    document = json.loads(V1X_MANIFEST.read_text(encoding="utf-8"))
    summary = document["cross_provider_summary"]
    assert summary["b1_point_in_time_status"] == "INFEASIBLE"
    assert summary["b1_fallback_comparison"] == "B2-vs-B0"
    assert summary["common_history_status"] == "PASS"
    validation = load_and_validate_audit_manifest(V1X_MANIFEST)
    assert validation.blockers == ("B1_NOT_AUTHORIZED",)
