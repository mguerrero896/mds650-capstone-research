"""Unit coverage for the offline, evidence-scoped provider-timing v2 audit."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mds650.provider_timing_v2 import (
    audit_massive_cache_sample,
    audit_massive_selected_quotes,
    audit_uw_b2_feature_windows,
    build_pit_claim_matrix_v2,
    fmp_timing_evidence_v2,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
audit_script = importlib.import_module("audit_provider_timing_v2")
renderer_script = importlib.import_module("render_provider_timing_v2_docs")
determinism_script = importlib.import_module("verify_provider_timing_v2")


def test_claim_matrix_separates_provider_payload_and_study_rule() -> None:
    """Every provider timing assertion has one permitted evidence class."""
    claims = build_pit_claim_matrix_v2()
    by_key = {claim["claim_key"]: claim for claim in claims}

    assert by_key["fmp_timestamp_timezone"]["claim_class"] == "UNVERIFIED"
    assert by_key["fmp_raw_timestamp_payload"]["claim_class"] == "PAYLOAD_OBSERVED"
    assert by_key["fmp_plus_one_minute"]["claim_class"] == "STUDY_CONSERVATIVE_RULE"
    assert by_key["uw_created_at"]["claim_class"] == "PROVIDER_DOCUMENTED"
    assert "publication" not in by_key["uw_created_at"]["permitted_conclusion"].lower()
    assert by_key["massive_sip_timestamp"]["claim_class"] == "PROVIDER_DOCUMENTED"
    assert by_key["massive_cache_timestamp_lte"]["claim_class"] == "PAYLOAD_OBSERVED"


def test_fmp_timing_evidence_keeps_documentation_payload_and_rule_separate() -> None:
    """FMP's conservative rule cannot become a provider timestamp specification."""
    evidence = fmp_timing_evidence_v2()

    assert evidence["payload_observed"]["raw_timestamp_format"] == "YYYY-MM-DD HH:mm:ss"
    assert evidence["provider_documented"]["raw_timestamp_timezone"] == "UNVERIFIED"
    assert evidence["provider_documented"]["bar_start_or_close"] == "UNVERIFIED"
    assert evidence["study_rules"]["primary_available_at"] == "raw_timestamp_plus_60_seconds"


def test_uw_feature_window_uses_half_open_bounds_and_both_timestamps(tmp_path: Path) -> None:
    """B2 eligibility keeps the exact registered five-minute, delayed contract."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-07-07" / "asset=AAPL" / "events.parquet",
        executed=(
            "2025-07-07T13:29:00Z",  # Inclusive lower bound.
            "2025-07-07T13:30:00Z",  # Eligible.
            "2025-07-07T13:33:59Z",  # Late record, hence ineligible.
            "2025-07-07T13:34:00Z",  # Exclusive upper bound.
        ),
        created=(
            "2025-07-07T13:29:00Z",
            "2025-07-07T13:30:20Z",
            "2025-07-07T13:34:01Z",
            "2025-07-07T13:34:00Z",
        ),
    )
    origins = tmp_path / "origins.parquet"
    _write_origins(origins, ("2025-07-07T13:35:00Z",))

    audit = audit_uw_b2_feature_windows(
        event_root=event_root,
        origins_path=origins,
        buffers_seconds=(60,),
        batch_size=2,
    )

    row = audit["feature_window_eligibility"][0]
    assert row["candidate_trade_count"] == 3
    assert row["eligible_trade_count"] == 2
    assert row["late_record_count"] == 1
    assert row["eligible_trade_retention_share"] == pytest.approx(2 / 3)
    assert row["origins_with_eligible_activity"] == 1


def test_uw_record_creation_lag_cdf_is_monotonic(tmp_path: Path) -> None:
    """The nested lag CDF, unlike shifted feature windows, must be monotonic."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-07-07" / "asset=AAPL" / "events.parquet",
        executed=(
            "2025-07-07T13:30:00Z",
            "2025-07-07T13:31:00Z",
            "2025-07-07T13:32:00Z",
        ),
        created=(
            "2025-07-07T13:30:30Z",
            "2025-07-07T13:33:00Z",
            "2025-07-07T13:42:00Z",
        ),
    )
    origins = tmp_path / "origins.parquet"
    _write_origins(origins, ("2025-07-07T13:35:00Z",))

    audit = audit_uw_b2_feature_windows(
        event_root=event_root,
        origins_path=origins,
        buffers_seconds=(60, 120, 300),
        batch_size=3,
    )

    cdf = audit["record_creation_lag_cdf"]
    shares = [row["within_buffer_share"] for row in cdf]
    assert shares == sorted(shares)
    assert audit["record_creation_lag_cdf_monotonic"] is True
    assert audit["extreme_tail"]["lag_over_300_seconds_count"] == 1


def test_uw_audit_fails_closed_for_bad_root_and_reports_missing_partition(tmp_path: Path) -> None:
    """Missing Full Tape evidence is explicit and cannot become zero activity."""
    origins = tmp_path / "origins.parquet"
    _write_origins(origins, ("2025-07-07T13:35:00Z",))

    with pytest.raises(FileNotFoundError, match="TIMING_V2_FULL_TAPE_ROOT_MISSING"):
        audit_uw_b2_feature_windows(
            event_root=tmp_path / "missing-events",
            origins_path=origins,
            buffers_seconds=(60,),
        )
    with pytest.raises(ValueError, match="TIMING_V2_BATCH_SIZE_MUST_BE_POSITIVE"):
        audit_uw_b2_feature_windows(
            event_root=tmp_path,
            origins_path=origins,
            buffers_seconds=(60,),
            batch_size=0,
        )

    event_root = tmp_path / "events"
    event_root.mkdir()
    audit = audit_uw_b2_feature_windows(
        event_root=event_root,
        origins_path=origins,
        buffers_seconds=(60,),
    )

    assert audit["missing_event_file_count"] == 1
    row = audit["feature_window_eligibility"][0]
    assert row["event_file_available"] is False
    assert row["candidate_trade_count"] == 0
    assert row["eligible_trade_retention_share"] is None


def test_massive_selected_quote_audit_detects_future_sip_and_negative_age(tmp_path: Path) -> None:
    """A future SIP quote is counted explicitly instead of being silently accepted."""
    matrix_path = tmp_path / "matrix.parquet"
    attempts_path = tmp_path / "attempts.parquet"
    origin_ns = 1_700_000_000_000_000_000
    _write_b1_matrix(matrix_path, origin_ns=origin_ns)
    _write_iv_attempts(attempts_path, origin_ns=origin_ns)

    audit = audit_massive_selected_quotes(
        origin_matrix_path=matrix_path,
        iv_attempts_path=attempts_path,
    )

    assert audit["origin_matrix"]["future_sip_timestamp_count"] == 1
    assert audit["iv_attempts"]["future_sip_timestamp_count"] == 1
    assert audit["iv_attempts"]["negative_quote_age_count"] == 1
    assert audit["selected_quote_future_free"] is False


def test_massive_cache_schema_sample_is_deterministic_and_sanitized(tmp_path: Path) -> None:
    """The cache schema audit reports logical evidence without personal paths or payloads."""
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    (cache_root / "a.json").write_text(
        """{"schema_version":4,"http_status":200,"request_params_sanitized":{"timestamp.lte":"1700000000000000000","sort":"timestamp","order":"asc","limit":"50000"},"results":[{"sip_timestamp":1700000000000000000,"sequence_number":7,"bid_price":1.0,"ask_price":1.1}]}""",
        encoding="utf-8",
    )

    first = audit_massive_cache_sample(cache_root=cache_root, sample_size=1)
    second = audit_massive_cache_sample(cache_root=cache_root, sample_size=1)

    assert first == second
    assert first["sampled_file_count"] == 1
    assert first["schema_valid_file_count"] == 1
    assert first["sequence_number_missing_count"] == 0
    assert first["sip_timestamp_non_nanosecond_count"] == 0
    assert str(tmp_path) not in str(first)


def test_massive_cache_schema_audit_fails_closed_for_invalid_local_payloads(tmp_path: Path) -> None:
    """Malformed cached replies receive explicit counters instead of silent acceptance."""
    missing = tmp_path / "missing-cache"
    with pytest.raises(FileNotFoundError, match="TIMING_V2_MASSIVE_CACHE_ROOT_MISSING"):
        audit_massive_cache_sample(cache_root=missing, sample_size=1)

    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    with pytest.raises(ValueError, match="TIMING_V2_CACHE_SAMPLE_SIZE_MUST_BE_POSITIVE"):
        audit_massive_cache_sample(cache_root=cache_root, sample_size=0)

    (cache_root / "invalid-json.json").write_text("{not-json", encoding="utf-8")
    (cache_root / "top-level.json").write_text("[]", encoding="utf-8")
    (cache_root / "bad-envelope.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "http_status": 403,
                "request_params_sanitized": "not-a-mapping",
                "results": "not-a-list",
            }
        ),
        encoding="utf-8",
    )
    (cache_root / "bad-results.json").write_text(
        json.dumps(
            {
                "schema_version": 4,
                "http_status": 200,
                "request_params_sanitized": {
                    "timestamp.lte": "1700000000000000000",
                    "sort": "timestamp",
                    "order": "desc",
                    "limit": "1",
                },
                "results": [
                    None,
                    {"sip_timestamp": 3, "sequence_number": "not-an-int"},
                    {"sip_timestamp": 1700000000000000001, "sequence_number": 1},
                    {"sip_timestamp": 1700000000000000001, "sequence_number": 1},
                ],
            }
        ),
        encoding="utf-8",
    )

    audit = audit_massive_cache_sample(cache_root=cache_root, sample_size=10)

    assert audit["unreadable_or_invalid_json_count"] == 1
    assert audit["invalid_top_level_count"] == 1
    assert audit["schema_version_invalid_count"] == 1
    assert audit["http_status_invalid_count"] == 1
    assert audit["request_parameters_invalid_count"] == 1
    assert audit["results_invalid_count"] == 1
    assert audit["result_row_invalid_count"] == 1
    assert audit["sip_timestamp_non_nanosecond_count"] == 1
    assert audit["sequence_number_missing_count"] == 1
    assert audit["quote_after_request_upper_bound_count"] == 2
    assert audit["duplicate_sip_sequence_key_count"] == 1
    assert audit["schema_valid_file_count"] == 0


def test_offline_cli_writes_complete_sanitized_timing_evidence(tmp_path: Path) -> None:
    """The v2 CLI emits only compact, target-free timing evidence."""
    event_root = tmp_path / "events"
    _write_events(
        event_root / "date=2025-07-07" / "asset=AAPL" / "events.parquet",
        executed=("2025-07-07T13:30:00Z",),
        created=("2025-07-07T13:30:20Z",),
    )
    origins = tmp_path / "origins.parquet"
    _write_origins(origins, ("2025-07-07T13:35:00Z",))
    matrix = tmp_path / "matrix.parquet"
    attempts = tmp_path / "attempts.parquet"
    origin_ns = 1_700_000_000_000_000_000
    _write_b1_matrix(matrix, origin_ns=origin_ns)
    _write_iv_attempts(attempts, origin_ns=origin_ns)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    (cache_root / "quote.json").write_text(
        """{"schema_version":4,"http_status":200,"request_params_sanitized":{"timestamp.lte":"1700000000000000000","sort":"timestamp","order":"asc","limit":"50000"},"results":[{"sip_timestamp":1700000000000000000,"sequence_number":7,"bid_price":1.0,"ask_price":1.1}]}""",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    assert (
        audit_script.main(
            [
                "--event-root",
                str(event_root),
                "--origins-path",
                str(origins),
                "--origin-matrix-path",
                str(matrix),
                "--iv-attempts-path",
                str(attempts),
                "--massive-cache-root",
                str(cache_root),
                "--output-dir",
                str(output),
                "--cache-sample-size",
                "1",
                "--batch-size",
                "2",
            ]
        )
        == 0
    )

    manifest = json.loads((output / "pit_timing_audit_v2.json").read_text(encoding="utf-8"))
    serialized = json.dumps(manifest, sort_keys=True)
    assert manifest["no_provider_http_requests_performed"] is True
    assert manifest["no_targets_or_predictive_metrics_read"] is True
    assert str(tmp_path) not in serialized
    assert (output / "pit_claim_matrix_v2.json").is_file()
    assert (output / "massive_quote_audit_v2.json").is_file()
    assert (output / "uw_b2_retention_by_buffer.csv").is_file()
    assert (output / "uw_b2_retention_by_asset.csv").is_file()
    assert len(list((output / "official_sources").glob("*.json"))) == 4


def test_renderer_separates_provider_facts_payload_and_study_rules(tmp_path: Path) -> None:
    """Rendered v2 documents cannot relabel an inference as provider documentation."""
    audit_dir = tmp_path / "audit"
    source_dir = audit_dir / "official_sources"
    source_dir.mkdir(parents=True)
    claims = build_pit_claim_matrix_v2()
    (audit_dir / "pit_claim_matrix_v2.json").write_text(
        json.dumps({"claims": claims}), encoding="utf-8"
    )
    for index, source in enumerate(
        (
            {
                "source_id": "fmp_1min_endpoint",
                "provider": "FMP",
                "title": "FMP 1 minute",
                "url": "https://example.test/fmp",
            },
            {
                "source_id": "uw_option_trade",
                "provider": "Unusual Whales",
                "title": "UW OptionTrade",
                "url": "https://example.test/uw",
            },
            {
                "source_id": "massive_options_quotes",
                "provider": "Massive",
                "title": "Massive Quotes",
                "url": "https://example.test/massive",
            },
        )
    ):
        (source_dir / f"source-{index}.json").write_text(json.dumps(source), encoding="utf-8")
    manifest = {
        "gates": {
            "EXISTING_FMP_EVIDENCE": "CONDITIONAL_STUDY_RULE_ONLY",
            "EXISTING_UW_RECORD_CREATION_EVIDENCE": "PASS_PROXY_ONLY",
            "EXISTING_MASSIVE_SELECTED_QUOTE_EVIDENCE": "PASS",
            "EXISTING_MASSIVE_CACHE_SCHEMA_SAMPLE": "PASS",
            "NEW_HISTORICAL_SAMPLE": "REQUIRES_DATE_LEVEL_PIT_PREFLIGHT",
            "NEW_PROSPECTIVE_CAPTURE": "REQUIRES_PROVIDER_RECEIPT_LOGGER",
            "UNIVERSAL_PROVIDER_PUBLICATION_OR_RECEIPT_LATENCY": "NOT_SUPPORTED",
        },
        "uw": {
            "record_creation_lag_cdf_monotonic": True,
            "record_creation_lag_cdf": [
                {"buffer_seconds": 60, "within_buffer_share": 0.9},
                {"buffer_seconds": 120, "within_buffer_share": 0.95},
                {"buffer_seconds": 300, "within_buffer_share": 0.99},
            ],
            "extreme_tail": {"lag_over_300_seconds_count": 2},
            "feature_window_summary": [
                {"buffer_seconds": 60, "eligible_trade_retention_share": 0.9},
            ],
        },
        "massive": {
            "selected_quote_future_free": True,
            "origin_matrix": {"future_sip_timestamp_count": 0},
            "iv_attempts": {"future_sip_timestamp_count": 0},
        },
        "massive_cache_schema_sample": {"schema_valid_file_count": 1},
    }
    (audit_dir / "pit_timing_audit_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
    docs_dir = tmp_path / "docs"
    reports_dir = tmp_path / "reports"

    assert (
        renderer_script.main(
            [
                "--audit-dir",
                str(audit_dir),
                "--docs-dir",
                str(docs_dir),
                "--reports-dir",
                str(reports_dir),
            ]
        )
        == 0
    )

    contract = (docs_dir / "provider_timing_pit_contract_v2.md").read_text(encoding="utf-8")
    claims_document = (docs_dir / "provider_timing_claim_matrix_v2.md").read_text(encoding="utf-8")
    appendix = (docs_dir / "provider_timing_academic_appendix_v2.md").read_text(encoding="utf-8")
    handoff = (reports_dir / "CODEX_PIT_V2_HANDOFF.md").read_text(encoding="utf-8")
    combined = contract + claims_document + appendix + handoff
    assert "STUDY_CONSERVATIVE_RULE" in claims_document
    assert "not provider-documented" in contract
    assert "record-creation lag" in contract
    assert "FMP +1 minute" in contract
    assert "NEW_HISTORICAL_SAMPLE" in handoff
    assert "created_at is publication time" not in combined
    assert str(tmp_path) not in combined


def test_determinism_verifier_compares_sanitized_artifact_trees(tmp_path: Path) -> None:
    """A replay is accepted only when every compact evidence file hashes identically."""
    expected = tmp_path / "expected"
    replay = tmp_path / "replay"
    for directory in (expected, replay):
        (directory / "official_sources").mkdir(parents=True)
        (directory / "pit_timing_audit_v2.json").write_text('{"ok":true}\n', encoding="utf-8")
        (directory / "official_sources" / "uw.json").write_text("{}\n", encoding="utf-8")
    output = tmp_path / "determinism.json"

    assert (
        determinism_script.main(
            [
                "--expected-dir",
                str(expected),
                "--replay-dir",
                str(replay),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["deterministic"] is True
    assert str(tmp_path) not in json.dumps(evidence, sort_keys=True)


def test_determinism_verifier_ignores_transient_process_logs(tmp_path: Path) -> None:
    """Operational logs beside a replay must not change the evidence comparison."""
    expected = tmp_path / "expected"
    replay = tmp_path / "replay"
    for directory in (expected, replay):
        directory.mkdir()
        (directory / "pit_timing_audit_v2.json").write_text('{"ok":true}\n', encoding="utf-8")
    (replay / "audit.stdout.log").write_text("local operational log\n", encoding="utf-8")
    (replay / "audit.stderr.log").write_text("", encoding="utf-8")
    output = tmp_path / "determinism.json"

    assert (
        determinism_script.main(
            [
                "--expected-dir",
                str(expected),
                "--replay-dir",
                str(replay),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["deterministic"] is True
    assert evidence["expected_file_count"] == 1
    assert evidence["replay_file_count"] == 1


def _write_events(
    path: Path,
    *,
    executed: tuple[str, ...],
    created: tuple[str, ...],
) -> None:
    """Write UTC timestamp-only Full Tape fixtures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "executed_at": pa.array(
                [_timestamp(value) for value in executed], type=pa.timestamp("us", tz="UTC")
            ),
            "created_at": pa.array(
                [_timestamp(value) for value in created], type=pa.timestamp("us", tz="UTC")
            ),
        }
    )
    pq.write_table(table, path)


def _write_origins(path: Path, values: tuple[str, ...]) -> None:
    """Write the target-free B1 origin projection used by the audit."""
    table = pa.table(
        {
            "origin_id": [f"AAPL-{index}" for index, _ in enumerate(values)],
            "asset": ["AAPL"] * len(values),
            "session_date": ["2025-07-07"] * len(values),
            "forecast_origin_utc": pa.array(
                [_timestamp(value) for value in values], type=pa.timestamp("us", tz="UTC")
            ),
        }
    )
    pq.write_table(table, path)


def _write_b1_matrix(path: Path, *, origin_ns: int) -> None:
    """Write two non-outcome rows, one intentionally future-dated."""
    table = pa.table(
        {
            "origin_id": ["a", "b"],
            "forecast_origin_utc": pa.array(
                [_timestamp("2023-11-14T22:13:20Z")] * 2, type=pa.timestamp("us", tz="UTC")
            ),
            "b1q_max_sip_timestamp_ns": [origin_ns - 1, origin_ns + 1],
            "b1q_quote_not_after_origin": [True, False],
            "b1q_pit_evidence_valid": [True, False],
        }
    )
    pq.write_table(table, path)


def _write_iv_attempts(path: Path, *, origin_ns: int) -> None:
    """Write quote attempts with one valid and one future SIP timestamp."""
    table = pa.table(
        {
            "origin_id": ["a", "b"],
            "forecast_origin_ns": [origin_ns, origin_ns],
            "sip_timestamp": [origin_ns - 60_000_000_000, origin_ns + 1],
            "quote_age_seconds": [60.0, -0.000000001],
        }
    )
    pq.write_table(table, path)


def _timestamp(value: str) -> datetime:
    """Parse a compact UTC fixture timestamp."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
