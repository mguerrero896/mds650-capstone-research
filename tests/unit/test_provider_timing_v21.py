"""Regression tests for the target-blind provider-timing v2.1 amendment."""

from __future__ import annotations

import csv
import hashlib
import importlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mds650.provider_timing_v21 import (
    B2_FEATURE_COLUMNS,
    OfficialSourceResponse,
    archive_official_source_records,
    audit_b2_canonical_traceability,
    audit_forecast_origin_session_bounds,
    audit_massive_reselection,
    audit_uw_session_asset_incidents,
    build_pit_claim_matrix_v21,
    reselect_last_quote_asof,
    timestamp_array_to_ns,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
audit_script = importlib.import_module("audit_provider_timing_v21")
renderer_script = importlib.import_module("render_provider_timing_v21_docs")


def test_timestamp_array_to_ns_normalizes_microseconds_without_1970_regression() -> None:
    """Arrow microsecond timestamps must be scaled before PIT calculations."""
    values = pa.array(
        [datetime(2025, 10, 20, 13, 30, tzinfo=UTC), None],
        type=pa.timestamp("us", tz="UTC"),
    )

    ns, valid = timestamp_array_to_ns(values)

    assert valid == [True, False]
    assert ns[0] == 1_760_967_000_000_000_000
    assert ns[1] is None


def test_uw_zero_rows_with_delayed_records_are_confounding_not_true_no_activity(
    tmp_path: Path,
) -> None:
    """A delayed source cannot silently turn an all-zero B2 group into no activity."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-10-20" / "asset=AAPL" / "events.parquet",
        executed=["2025-10-20T13:30:00Z", "2025-10-20T13:31:00Z"],
        created=["2025-10-20T19:46:00Z", "2025-10-20T19:47:00Z"],
    )
    incidents = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=("2025-10-20",),
        assets=("AAPL",),
        batch_size=1,
    )
    matrix_root = tmp_path / "b2"
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-10-20.parquet",
        asset="AAPL",
        values=(0.0, 0.0),
    )

    rows, gate = audit_b2_canonical_traceability(
        matrix_root=matrix_root,
        incidents=incidents,
        expected_origins_per_asset_date=2,
    )

    assert rows[0]["coding_status"] == "ZERO_CODING_POTENTIALLY_CONFOUNDED"
    assert rows[0]["source_temporal_state"] == "RECORD_CREATION_DELAY_OBSERVED"
    assert rows[0]["availability_indicator_status"] == "ABSENT"
    assert gate == "FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED"


def test_uw_missing_source_never_passes_zero_activity_availability(tmp_path: Path) -> None:
    """An absent raw partition remains unavailable even when B2 rows are zero."""
    event_root = tmp_path / "events"
    event_root.mkdir()
    incidents = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=("2025-10-20",),
        assets=("AAPL",),
    )
    matrix_root = tmp_path / "b2"
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-10-20.parquet",
        asset="AAPL",
        values=(0.0, 0.0),
    )

    rows, gate = audit_b2_canonical_traceability(
        matrix_root=matrix_root,
        incidents=incidents,
        expected_origins_per_asset_date=2,
    )

    assert rows[0]["source_temporal_state"] == "SOURCE_UNAVAILABLE"
    assert rows[0]["coding_status"] == "ZERO_CODING_SOURCE_UNAVAILABLE"
    assert gate == "FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED"


def test_uw_delay_tail_confounds_individual_zero_rows_inside_mixed_group(tmp_path: Path) -> None:
    """A mixed numeric group still needs a delay flag for its zero-coded origins."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-09-18" / "asset=NVDA" / "events.parquet",
        executed=["2025-09-18T13:30:00Z", "2025-09-18T13:31:00Z"],
        created=["2025-09-18T13:30:01Z", "2025-09-18T14:31:01Z"],
    )
    incidents = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=("2025-09-18",),
        assets=("NVDA",),
    )
    matrix_root = tmp_path / "b2"
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-09-18.parquet",
        asset="NVDA",
        values=(0.0, 1.0),
    )

    rows, gate = audit_b2_canonical_traceability(
        matrix_root=matrix_root,
        incidents=incidents,
        expected_origins_per_asset_date=2,
    )

    assert rows[0]["canonical_value_coding"] == "MIXED_NUMERIC_ZERO_AND_NONZERO"
    assert rows[0]["coding_status"] == "ZERO_CODING_POTENTIALLY_CONFOUNDED"
    assert gate == "FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED"


def test_b2_traceability_separates_zero_missing_and_row_exclusion(tmp_path: Path) -> None:
    """Traceability must expose each representation rather than infer activity."""
    event_root = tmp_path / "events"
    for asset in ("AAPL", "MSFT", "NVDA"):
        _write_events(
            event_root / "date=2025-08-21" / f"asset={asset}" / "events.parquet",
            executed=["2025-08-21T13:30:00Z"],
            created=["2025-08-21T13:30:10Z"],
        )
    incidents = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=("2025-08-21",),
        assets=("AAPL", "MSFT", "NVDA"),
    )
    matrix_root = tmp_path / "b2"
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-08-21.parquet",
        asset="AAPL",
        values=(0.0, 0.0),
    )
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-08-21-msft.parquet",
        asset="MSFT",
        values=(None, 1.0),
    )
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-08-21-nvda.parquet",
        asset="NVDA",
        values=(1.0,),
    )

    rows, _ = audit_b2_canonical_traceability(
        matrix_root=matrix_root,
        incidents=incidents,
        expected_origins_per_asset_date=2,
    )
    by_asset = {str(row["asset"]): row for row in rows}

    assert by_asset["AAPL"]["coding_status"] == "ZERO_CODING_SOURCE_AVAILABLE"
    assert by_asset["MSFT"]["coding_status"] == "MISSING_FEATURE_VALUES"
    assert by_asset["NVDA"]["coding_status"] == "ROW_EXCLUDED_OR_MISSING"
    assert all(row["availability_indicator_status"] == "ABSENT" for row in rows)


def test_b2_traceability_uses_target_free_origin_projection_for_early_close(tmp_path: Path) -> None:
    """Expected B2 rows must come from a schedule-aware origin table, not hard-coded 72."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-11-28" / "asset=AAPL" / "events.parquet",
        executed=["2025-11-28T14:30:00Z"],
        created=["2025-11-28T14:30:01Z"],
    )
    incidents = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=("2025-11-28",),
        assets=("AAPL",),
    )
    origins = tmp_path / "origins.parquet"
    pq.write_table(
        pa.table({"asset": pa.array(["AAPL"]), "session_date": pa.array(["2025-11-28"])}),
        origins,
    )
    matrix_root = tmp_path / "b2"
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-11-28.parquet",
        asset="AAPL",
        values=(1.0,),
    )

    rows, _ = audit_b2_canonical_traceability(
        matrix_root=matrix_root,
        incidents=incidents,
        expected_origins_path=origins,
    )

    assert rows[0]["expected_origin_count"] == 1
    assert rows[0]["row_presence_status"] == "ALL_EXPECTED_ROWS_PRESENT"


def test_claim_matrix_separates_kafka_semantics_from_full_tape_observation() -> None:
    """Kafka field definitions cannot be silently elevated to Full Tape REST semantics."""
    claims = {row["claim_key"]: row for row in build_pit_claim_matrix_v21()}

    assert claims["fmp_intraday_exchange_region_timezone"]["claim_class"] == "PROVIDER_DOCUMENTED"
    assert claims["fmp_exact_iana_timezone"]["claim_class"] == "UNVERIFIED"
    assert claims["uw_kafka_created_at"]["claim_class"] == "PROVIDER_DOCUMENTED_KAFKA"
    assert claims["uw_full_tape_created_at_field"]["claim_class"] == "PAYLOAD_OBSERVED"
    assert claims["uw_full_tape_created_at_semantics"]["claim_class"] == "UNVERIFIED"
    assert "publication" not in claims["uw_kafka_created_at"]["permitted_conclusion"].lower()


def test_official_source_archive_hashes_only_allowlisted_content(tmp_path: Path) -> None:
    """Official document evidence is hash-addressed and retains no raw body."""
    body = b"Official FMP FAQ body"

    def fake_fetch(url: str, headers: dict[str, str]) -> OfficialSourceResponse:
        assert url.startswith("https://")
        assert "User-Agent" in headers
        return OfficialSourceResponse(status_code=200, content_type="text/html", body=body)

    records = archive_official_source_records(output_dir=tmp_path, fetch=fake_fetch)

    fmp = next(record for record in records if record["source_id"] == "fmp_faq_intraday_timezone")
    persisted = json.loads(
        (tmp_path / "fmp_faq_intraday_timezone.json").read_text(encoding="utf-8")
    )
    assert fmp["source_content_sha256"] == hashlib.sha256(body).hexdigest()
    assert "body" not in persisted
    assert body.decode("utf-8") not in json.dumps(persisted)
    assert all(record["source_content_hash_status"] == "HTTP_200_BODY_SHA256" for record in records)


def test_massive_reselection_uses_each_shifted_cutoff_not_selected_quote_filter(
    tmp_path: Path,
) -> None:
    """The origin-minus-delay cut must choose a different raw quote when available."""
    origin_ns = 1_750_000_000_000_000_000
    attempts_path = tmp_path / "attempts.parquet"
    contract = "O:AAPL250117C00100000"
    source_hash = _fixture_source_hash(contract)
    _write_attempts(
        attempts_path,
        origin_ns=origin_ns,
        source_hash=source_hash,
        contract=contract,
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _write_cache(
        cache_root / "AAPL_2025-01-02_O_AAPL250117C00100000_fixture.json",
        source_hash=source_hash,
        quotes=[
            _quote(origin_ns + 20_000_000_000, 10),
            _quote(origin_ns - 10_000_000_000, 11),
            _quote(origin_ns - 70_000_000_000, 12),
            _quote(origin_ns - 310_000_000_000, 13),
        ],
    )

    selected_60 = reselect_last_quote_asof(
        quotes=[
            _quote(origin_ns + 20_000_000_000, 10),
            _quote(origin_ns - 10_000_000_000, 11),
            _quote(origin_ns - 70_000_000_000, 12),
            _quote(origin_ns - 310_000_000_000, 13),
        ],
        cutoff_ns=origin_ns - 60_000_000_000,
    )
    assert selected_60 is not None
    assert selected_60["sip_timestamp"] == origin_ns - 70_000_000_000

    audit = audit_massive_reselection(
        attempts_path=attempts_path,
        cache_root=cache_root,
        cutoffs_seconds=(0, 60, 300),
    )
    by_cut = {int(row["cutoff_delay_seconds"]): row for row in audit["summary_by_cutoff"]}

    assert audit["status"] == "PASS"
    assert by_cut[0]["selected_quote_count"] == 1
    assert by_cut[0]["median_quote_age_seconds"] == pytest.approx(10.0)
    assert by_cut[60]["median_quote_age_seconds"] == pytest.approx(70.0)
    assert by_cut[300]["median_quote_age_seconds"] == pytest.approx(310.0)
    assert by_cut[60]["future_quote_count"] == 0
    assert by_cut[300]["iv_success_count"] == 1


def test_massive_reselection_fails_closed_for_cache_source_hash_mismatch(tmp_path: Path) -> None:
    """A cache envelope with the wrong request hash cannot be joined to an IV attempt."""
    origin_ns = 1_750_000_000_000_000_000
    attempts_path = tmp_path / "attempts.parquet"
    contract = "O:AAPL250117C00100000"
    _write_attempts(
        attempts_path,
        origin_ns=origin_ns,
        source_hash="a" * 64,
        contract=contract,
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _write_cache(
        cache_root / "AAPL_2025-01-02_O_AAPL250117C00100000_fixture.json",
        source_hash=_fixture_source_hash(contract),
        quotes=[_quote(origin_ns - 10_000_000_000, 1)],
    )

    audit = audit_massive_reselection(
        attempts_path=attempts_path,
        cache_root=cache_root,
        cutoffs_seconds=(0,),
    )

    assert audit["cache_identity_failures"]["CACHE_SOURCE_HASH_MISMATCH"] == 1
    assert audit["summary_by_cutoff"][0]["selected_quote_count"] == 0


def test_massive_reselection_fails_closed_for_cache_key_digest_tampering(tmp_path: Path) -> None:
    """The file name and envelope key must remain derivable from the contract-day."""
    origin_ns = 1_750_000_000_000_000_000
    attempts_path = tmp_path / "attempts.parquet"
    contract = "O:AAPL250117C00100000"
    source_hash = _fixture_source_hash(contract)
    _write_attempts(
        attempts_path,
        origin_ns=origin_ns,
        source_hash=source_hash,
        contract=contract,
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cache_path = _write_cache(
        cache_root / "unused.json",
        source_hash=source_hash,
        quotes=[_quote(origin_ns - 10_000_000_000, 1)],
    )
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["cache_key"] = "tampered"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")

    audit = audit_massive_reselection(
        attempts_path=attempts_path,
        cache_root=cache_root,
        cutoffs_seconds=(0,),
    )

    assert audit["cache_identity_failures"]["CACHE_KEY_DIGEST_MISMATCH"] == 1
    assert audit["status"] == "FAIL_CACHE_IDENTITY_OR_MONOTONICITY"
    assert audit["summary_by_cutoff"][0]["selected_quote_count"] == 0


def test_massive_reselection_accepts_early_close_regular_close_request_without_post_close_quote(
    tmp_path: Path,
) -> None:
    """An overextended early-close request is usable only when its quotes stop at close."""
    origin_ns = 1_764_341_000_000_000_000
    contract = "O:AAPL250117C00100000"
    request_params = _fixture_request_params(
        session_date="2025-11-28", use_nominal_regular_close=True
    )
    source_hash = _fixture_source_hash(contract, request_params=request_params)
    attempts_path = tmp_path / "attempts.parquet"
    _write_attempts(
        attempts_path,
        origin_ns=origin_ns,
        source_hash=source_hash,
        contract=contract,
        session_date="2025-11-28",
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _write_cache(
        cache_root / "unused.json",
        source_hash=source_hash,
        quotes=[_quote(origin_ns - 10_000_000_000, 1)],
        session_date="2025-11-28",
        request_params=request_params,
    )

    audit = audit_massive_reselection(
        attempts_path=attempts_path,
        cache_root=cache_root,
        cutoffs_seconds=(0,),
    )

    assert audit["status"] == "PASS"
    assert audit["cache_identity_failures"] == {}
    assert audit["cache_scope_warnings"] == {"OK_EARLY_CLOSE_REQUEST_OVEREXTENDED": 1}
    assert audit["summary_by_cutoff"][0]["selected_quote_count"] == 1


def test_massive_reselection_excludes_post_close_early_close_quotes_before_selection(
    tmp_path: Path,
) -> None:
    """An overextended early-close cache must strip post-close SIP rows explicitly."""
    origin_ns = 1_764_341_000_000_000_000
    close_ns = 1_764_352_800_000_000_000
    contract = "O:AAPL250117C00100000"
    request_params = _fixture_request_params(
        session_date="2025-11-28", use_nominal_regular_close=True
    )
    source_hash = _fixture_source_hash(contract, request_params=request_params)
    attempts_path = tmp_path / "attempts.parquet"
    _write_attempts(
        attempts_path,
        origin_ns=origin_ns,
        source_hash=source_hash,
        contract=contract,
        session_date="2025-11-28",
    )
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _write_cache(
        cache_root / "unused.json",
        source_hash=source_hash,
        quotes=[_quote(origin_ns - 10_000_000_000, 1), _quote(close_ns + 1, 2)],
        session_date="2025-11-28",
        request_params=request_params,
    )

    audit = audit_massive_reselection(
        attempts_path=attempts_path,
        cache_root=cache_root,
        cutoffs_seconds=(0,),
    )

    assert audit["status"] == "PASS"
    assert audit["cache_identity_failures"] == {}
    assert audit["cache_scope_warnings"] == {
        "OK_EARLY_CLOSE_POST_CLOSE_QUOTES_EXCLUDED": 1
    }
    assert audit["summary_by_cutoff"][0]["selected_quote_count"] == 1


def test_massive_reselection_rejects_duplicate_and_never_backfills_invalid_quote() -> None:
    """The selected latest quote is not silently replaced by an earlier clean quote."""
    origin_ns = 1_750_000_000_000_000_000
    with pytest.raises(ValueError, match="TIMING_V21_CACHE_QUOTE_DUPLICATE"):
        reselect_last_quote_asof(
            quotes=[_quote(origin_ns - 10_000_000_000, 1), _quote(origin_ns - 10_000_000_000, 1)],
            cutoff_ns=origin_ns,
        )
    selected = reselect_last_quote_asof(
        quotes=[
            _quote(origin_ns - 20_000_000_000, 1),
            {
                "sip_timestamp": origin_ns - 10_000_000_000,
                "sequence_number": 2,
                "bid_price": 0.0,
                "ask_price": 1.0,
            },
        ],
        cutoff_ns=origin_ns,
    )
    assert selected is not None
    assert selected["sip_timestamp"] == origin_ns - 10_000_000_000


def test_v21_outputs_are_path_and_secret_free(tmp_path: Path) -> None:
    """Sanitized v2.1 summaries cannot leak local roots or credential-like values."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-08-21" / "asset=AAPL" / "events.parquet",
        executed=["2025-08-21T13:30:00Z"],
        created=["2025-08-21T13:30:01Z"],
    )
    incident = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=("2025-08-21",),
        assets=("AAPL",),
    )

    rendered = json.dumps(incident, sort_keys=True)

    assert str(tmp_path) not in rendered
    assert "apiKey" not in rendered
    assert "Authorization" not in rendered


def test_forecast_origin_session_bounds_accepts_early_close_and_fails_closed_outside_session(
    tmp_path: Path,
) -> None:
    """The schedule audit must retain early closes and reject post-close origins."""
    passed_path = tmp_path / "passed_origins.parquet"
    pq.write_table(
        pa.table(
            {
                "asset": pa.array(["AAPL"]),
                "session_date": pa.array(["2025-11-28"]),
                "forecast_origin_ns": pa.array([1_764_351_000_000_000_000], type=pa.int64()),
            }
        ),
        passed_path,
    )
    passed = audit_forecast_origin_session_bounds(origins_path=passed_path)
    assert passed["status"] == "PASS"
    assert passed["early_close_origin_count"] == 1

    failed_path = tmp_path / "failed_origins.parquet"
    pq.write_table(
        pa.table(
            {
                "asset": pa.array(["AAPL"]),
                "session_date": pa.array(["2025-11-28"]),
                "forecast_origin_ns": pa.array([1_764_352_800_000_000_001], type=pa.int64()),
            }
        ),
        failed_path,
    )
    failed = audit_forecast_origin_session_bounds(origins_path=failed_path)
    assert failed["status"] == "FAIL_ORIGIN_OUTSIDE_XNYS_SESSION"
    assert failed["origin_after_close_count"] == 1


def test_forecast_origin_session_bounds_normalizes_utc_arrow_timestamp_field(
    tmp_path: Path,
) -> None:
    """UTC microsecond source timestamps must use the canonical origin column."""
    origins_path = tmp_path / "utc_origins.parquet"
    pq.write_table(
        pa.table(
            {
                "asset": pa.array(["AAPL"]),
                "session_date": pa.array(["2025-08-21"]),
                "forecast_origin_utc": pa.array(
                    [datetime(2025, 8, 21, 13, 35, tzinfo=UTC)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
            }
        ),
        origins_path,
    )

    result = audit_forecast_origin_session_bounds(origins_path=origins_path)

    assert result["status"] == "PASS"
    assert result["origin_timestamp_column"] == "forecast_origin_utc"
    assert result["origin_row_count"] == 1


def test_offline_audit_cli_writes_target_free_compact_sidecars(tmp_path: Path) -> None:
    """The audit CLI must run entirely from acquired fixtures when Massive is skipped."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-08-21" / "asset=AAPL" / "events.parquet",
        executed=["2025-08-21T13:30:00Z"],
        created=["2025-08-21T13:30:01Z"],
    )
    matrix_root = tmp_path / "b2"
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-08-21.parquet",
        asset="AAPL",
        values=(1.0,),
    )
    origins = tmp_path / "origins.parquet"
    pq.write_table(
        pa.table(
            {
                "asset": pa.array(["AAPL"]),
                "session_date": pa.array(["2025-08-21"]),
                "forecast_origin_ns": pa.array([1_755_783_300_000_000_000], type=pa.int64()),
            }
        ),
        origins,
    )
    output = tmp_path / "output"

    result = audit_script.main(
        [
            "--event-root",
            str(event_root),
            "--b2-matrix-root",
            str(matrix_root),
            "--expected-origins-path",
            str(origins),
            "--output-dir",
            str(output),
            "--skip-massive",
        ]
    )

    assert result == 0
    audit = json.loads((output / "pit_timing_audit_v21.json").read_text(encoding="utf-8"))
    assert audit["no_targets_or_predictive_metrics_read"] is True
    assert audit["massive"]["status"] == "SKIPPED_BY_EXPLICIT_CLI_FLAG"
    assert audit["reconciliation_gate"]["safe_to_reconcile_existing_results"] is False
    assert "MASSIVE_CACHE_IDENTITY_GATE_NOT_PASS" in audit["reconciliation_gate"]["reasons"]


def test_offline_audit_cli_can_reuse_compact_massive_result_without_raw_cache(
    tmp_path: Path,
) -> None:
    """Finalization may reuse a strict compact Massive result without reopening cache files."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-08-21" / "asset=AAPL" / "events.parquet",
        executed=["2025-08-21T13:30:00Z"],
        created=["2025-08-21T13:30:01Z"],
    )
    matrix_root = tmp_path / "b2"
    _write_b2_matrix(
        matrix_root / "primary_5m_60s" / "date=2025-08-21.parquet",
        asset="AAPL",
        values=(1.0,),
    )
    origins = tmp_path / "origins.parquet"
    pq.write_table(
        pa.table(
            {
                "asset": pa.array(["AAPL"]),
                "session_date": pa.array(["2025-08-21"]),
                "forecast_origin_ns": pa.array([1_755_783_300_000_000_000], type=pa.int64()),
            }
        ),
        origins,
    )
    massive_result = tmp_path / "massive.json"
    massive_result.write_text(
        json.dumps(
            {
                "cache_identity_failures": {},
                "quote_existence_coverage_monotonic_nonincreasing": True,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = audit_script.main(
        [
            "--event-root",
            str(event_root),
            "--b2-matrix-root",
            str(matrix_root),
            "--expected-origins-path",
            str(origins),
            "--output-dir",
            str(output),
            "--reuse-massive-json",
            str(massive_result),
        ]
    )

    assert result == 0
    audit = json.loads((output / "pit_timing_audit_v21.json").read_text(encoding="utf-8"))
    assert audit["massive"]["status"] == "PASS"


def test_renderer_keeps_b2_contract_open_when_zero_is_confounding(tmp_path: Path) -> None:
    """Rendered human documentation must preserve the fail-closed B2 gate."""
    artifacts = tmp_path / "artifacts"
    sources = artifacts / "official_sources"
    sources.mkdir(parents=True)
    for index in range(4):
        (sources / f"source-{index}.json").write_text(
            json.dumps(
                {
                    "source_id": f"source-{index}",
                    "http_status": 200,
                    "source_content_sha256": "a" * 64,
                    "documented_excerpt": "documented fact",
                    "documented_nonclaim": "documented boundary",
                }
            ),
            encoding="utf-8",
        )
    (artifacts / "pit_timing_audit_v21.json").write_text(
        json.dumps(
            {"b2": {"b2_activity_availability_gate": "FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED"}}
        ),
        encoding="utf-8",
    )
    (artifacts / "massive_reselection_sensitivity_v21.json").write_text(
        json.dumps(
            {
                "quote_existence_coverage_monotonic_nonincreasing": True,
                "summary_by_cutoff": [],
            }
        ),
        encoding="utf-8",
    )
    _write_csv_fixture(
        artifacts / "uw_session_asset_incidents_v21.csv",
        [
            {
                "session_date": "2025-10-20",
                "source_temporal_state": "RECORD_CREATION_DELAY_OBSERVED",
                "lag_seconds_min": "1",
                "lag_seconds_max": "2",
            }
        ],
    )
    _write_csv_fixture(
        artifacts / "b2_canonical_traceability_v21.csv",
        [{"coding_status": "ZERO_CODING_POTENTIALLY_CONFOUNDED"}],
    )

    result = renderer_script.render_documents(
        artifact_dir=artifacts,
        docs_dir=tmp_path / "docs",
        reports_dir=tmp_path / "reports",
    )

    rendered = (tmp_path / "docs" / "provider_timing_pit_contract_v21.md").read_text(
        encoding="utf-8"
    )
    assert result["status"] == "CONDITIONAL_NOT_CLOSED"
    assert "not closed" in rendered
    assert "FAIL_ZERO_ACTIVITY_NOT_DISAMBIGUATED" in rendered
    assert result["safe_to_reconcile_existing_results"] is False
    assert "SAFE_TO_RECONCILE_EXISTING_RESULTS=NO" in rendered


def _write_events(path: Path, *, executed: list[str], created: list[str]) -> None:
    """Write UTC microsecond fixture events."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "executed_at": pa.array(
                    [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in executed],
                    type=pa.timestamp("us", tz="UTC"),
                ),
                "created_at": pa.array(
                    [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in created],
                    type=pa.timestamp("us", tz="UTC"),
                ),
            }
        ),
        path,
    )


def _write_csv_fixture(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a tiny deterministic CSV fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_b2_matrix(path: Path, *, asset: str, values: tuple[float | None, ...]) -> None:
    """Write a minimal canonical-like B2 matrix fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = len(values)
    match = re.search(r"date=(\d{4}-\d{2}-\d{2})", path.name)
    assert match is not None
    session_date = match.group(1)
    columns: dict[str, pa.Array] = {
        "asset": pa.array([asset] * rows),
        "session_date": pa.array([session_date] * rows),
        "origin_id": pa.array([f"{asset}-{index}" for index in range(rows)]),
    }
    for column in B2_FEATURE_COLUMNS:
        columns[column] = pa.array(values, type=pa.float64())
    pq.write_table(pa.table(columns), path)


def _write_attempts(
    path: Path,
    *,
    origin_ns: int,
    source_hash: str,
    contract: str,
    session_date: str = "2025-01-02",
) -> None:
    """Write a target-free B1 attempt fixture."""
    pq.write_table(
        pa.table(
            {
                "asset": pa.array(["AAPL"]),
                "session_date": pa.array([session_date]),
                "contract": pa.array([contract]),
                "source_request_hash": pa.array([source_hash]),
                "forecast_origin_ns": pa.array([origin_ns], type=pa.int64()),
                "spot": pa.array([100.0]),
                "strike": pa.array([100.0]),
                "dte": pa.array([30], type=pa.int64()),
                "rate": pa.array([0.01]),
                "dividend_yield": pa.array([0.0]),
                "option_type": pa.array(["call"]),
            }
        ),
        path,
    )


def _quote(sip_timestamp: int, sequence_number: int) -> dict[str, int | float]:
    """Return a valid compact quote fixture."""
    return {
        "sip_timestamp": sip_timestamp,
        "sequence_number": sequence_number,
        "bid_price": 3.25,
        "ask_price": 3.75,
    }


def _write_cache(
    path: Path,
    *,
    source_hash: str,
    quotes: list[dict[str, int | float]],
    session_date: str = "2025-01-02",
    request_params: dict[str, str] | None = None,
) -> Path:
    """Write a sanitized Massive cache envelope fixture."""
    contract = "O:AAPL250117C00100000"
    metadata = {
        "contract": contract,
        "expiry": "2025-01-17",
        "strike": 100.0,
        "option_type": "call",
    }
    cache_key = (
        f"provider=massive|asset=AAPL|session_date={session_date}|expiry=2025-01-17|"
        "strike=100.0|option_type=call|contract=O:AAPL250117C00100000|route=B1Q|"
        "schema_version=4"
    )
    params = request_params or _fixture_request_params(session_date=session_date)
    destination = path.parent / (
        f"AAPL_{session_date}_O_AAPL250117C00100000_"
        f"{hashlib.sha256(cache_key.encode('utf-8')).hexdigest()[:16]}.json"
    )
    destination.write_text(
        json.dumps(
            {
                "asset": "AAPL",
                "day": session_date,
                "contract": metadata,
                "cache_key": cache_key,
                "quote_cache_key": (
                    "provider=massive|contract=O:AAPL250117C00100000|"
                    f"session_date={session_date}|route=B1Q|schema_version=4"
                ),
                "route": "B1Q",
                "schema_version": 4,
                "http_status": 200,
                "source_request_hash": source_hash,
                "request_params_sanitized": params,
                "pages": 1,
                "results": quotes,
            }
        ),
        encoding="utf-8",
    )
    return destination


def _fixture_request_params(
    *, session_date: str, use_nominal_regular_close: bool = False
) -> dict[str, str]:
    """Return XNYS fixture parameters, including the observed early-close extension."""
    values = {
        "2025-01-02": ("1735828200000000000", "1735851600000000000"),
        "2025-11-28": (
            "1764340200000000000",
            "1764363600000000000" if use_nominal_regular_close else "1764352800000000000",
        ),
    }
    start, end = values[session_date]
    return {
        "timestamp.gte": start,
        "timestamp.lte": end,
        "sort": "timestamp",
        "order": "asc",
        "limit": "50000",
    }


def _fixture_source_hash(contract: str, *, request_params: dict[str, str] | None = None) -> str:
    """Return the exact sanitized request digest for a valid fixture cache."""
    params = request_params or _fixture_request_params(session_date="2025-01-02")
    return hashlib.sha256(
        (
            f"https://api.massive.com/v3/quotes/{contract}|"
            f"{json.dumps(params, sort_keys=True)}|route=B1Q|schema_version=4"
        ).encode()
    ).hexdigest()
