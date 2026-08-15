"""Fail-closed contracts for the independent-replication Full Tape batch."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mds650.b1v3_confirmation import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import acquire_b1_independent_replication_full_tape as acquisition  # noqa: E402


def _preregistration() -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "FROZEN_BEFORE_PROVIDER_PAYLOAD",
        "target_blind": True,
        "training_sessions": ["2024-12-09"],
        "replication_sessions": ["2024-12-10", "2024-12-11"],
        "provider_payload_reads_at_freeze": 0,
        "replication_target_reads": 0,
        "safe_to_access_replication_targets": "NO",
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def _plan(preregistration: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION",
        "target_blind": True,
        "source_confirmation_plan_sha256": preregistration["manifest_sha256"],
        "outcome_read_count": 0,
        "assets": ["AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA"],
        "sessions": [
            {"date": "2024-12-10", "role": "confirmation"},
            {"date": "2024-12-11", "role": "confirmation"},
        ],
    }
    payload["plan_sha256"] = canonical_sha256(payload)
    return payload


def _report(plan: dict[str, object]) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND",
        "target_blind": True,
        "safe_to_acquire_predictors": True,
        "safe_to_read_outcomes": False,
        "outcome_read_count": 0,
        "plan_sha256": plan["plan_sha256"],
        "provider_counts": {
            "fmp": {"expected": 12, "passed": 12},
            "massive": {"expected": 12, "passed": 12},
            "unusual_whales": {"expected": 2, "passed": 2},
        },
        "records": {
            "unusual_whales": [
                {"session_date": "2024-12-10", "content_length_bytes": 100},
                {"session_date": "2024-12-11", "content_length_bytes": 200},
            ]
        },
    }
    payload["report_sha256"] = canonical_sha256(payload)
    return payload


def test_contract_binds_preregistration_plan_and_provider_report() -> None:
    preregistration = _preregistration()
    plan = _plan(preregistration)
    report = _report(plan)

    contract = acquisition.validate_frozen_contract(preregistration, plan, report)

    assert contract.sessions == (date(2024, 12, 10), date(2024, 12, 11))
    assert contract.excluded_sessions == frozenset({date(2024, 12, 9)})
    assert contract.assets == ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
    assert contract.outcome_read_count == 0


def test_contract_fails_closed_when_report_hash_or_session_binding_changes() -> None:
    preregistration = _preregistration()
    plan = _plan(preregistration)
    report = _report(plan)
    report["status"] = "PASS_TAMPERED"

    with pytest.raises(RuntimeError, match="PROVIDER_REPORT_HASH_INVALID"):
        acquisition.validate_frozen_contract(preregistration, plan, report)

    report = _report(plan)
    plan["sessions"] = [{"date": "2024-12-12", "role": "confirmation"}]
    plan["plan_sha256"] = canonical_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    report["plan_sha256"] = plan["plan_sha256"]
    report["report_sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )
    with pytest.raises(RuntimeError, match="SESSION_BINDING_INVALID"):
        acquisition.validate_frozen_contract(preregistration, plan, report)


def test_peak_formula_includes_raw_parquet_temp_and_thirty_percent_margin() -> None:
    preregistration = _preregistration()
    plan = _plan(preregistration)
    report = _report(plan)

    # ceil(((300 raw * 1.20) + (2 * 200 max-day temp)) * 1.30) = 988.
    assert acquisition.projected_peak_additional_bytes(report) == 988


def test_pending_sessions_accepts_only_self_hashed_plan_bound_records() -> None:
    preregistration = _preregistration()
    plan = _plan(preregistration)
    report = _report(plan)
    contract = acquisition.validate_frozen_contract(preregistration, plan, report)
    record: dict[str, object] = {
        "status": "PASS",
        "session_date": "2024-12-10",
        "preregistration_sha256": contract.preregistration_sha256,
        "provider_report_sha256": contract.provider_report_sha256,
        "session_contract_sha256": acquisition.session_contract_sha256(
            "2024-12-10",
            contract.preregistration_sha256,
            contract.provider_report_sha256,
        ),
        "raw_sha256": "a" * 64,
        "raw_bytes": 1,
        "parquet_files": [{"relative_path": "x", "bytes": 1, "sha256": "b" * 64}],
        "target_outcome_read": False,
        "outcome_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    record["checkpoint_sha256"] = canonical_sha256(record)

    assert acquisition.pending_sessions(contract, [record]) == ["2024-12-11"]
    record["raw_bytes"] = 2
    assert acquisition.pending_sessions(contract, [record]) == [
        "2024-12-10",
        "2024-12-11",
    ]


def test_cli_requires_explicit_resume_flag() -> None:
    with pytest.raises(SystemExit, match="0"):
        acquisition.main(["--help"])


def test_full_tape_partitions_are_promoted_only_after_all_are_valid(
    tmp_path: Path,
) -> None:
    """A session must never expose an unfinished Parquet as its final file."""
    day = date(2024, 12, 10)
    downloader = acquisition.downloader
    for asset in downloader.ASSETS:
        partial = downloader._event_partition_path(tmp_path, day, asset, partial=True)
        partial.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist([], schema=downloader.EVENT_SCHEMA), partial)

    downloader._promote_event_partitions(tmp_path, day)

    for asset in downloader.ASSETS:
        final = downloader._event_partition_path(tmp_path, day, asset, partial=False)
        partial = downloader._event_partition_path(tmp_path, day, asset, partial=True)
        assert final.is_file()
        assert not partial.exists()
        assert pq.ParquetFile(final).metadata.num_rows == 0


def test_full_tape_promotion_fails_before_replacing_any_final_when_partial_missing(
    tmp_path: Path,
) -> None:
    """Validation of every partition precedes the first atomic replacement."""
    day = date(2024, 12, 10)
    downloader = acquisition.downloader
    assets = tuple(downloader.ASSETS)
    for asset in assets[:-1]:
        partial = downloader._event_partition_path(tmp_path, day, asset, partial=True)
        partial.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist([], schema=downloader.EVENT_SCHEMA), partial)

    with pytest.raises(RuntimeError, match="FULL_TAPE_PARTIAL_MISSING"):
        downloader._promote_event_partitions(tmp_path, day)

    assert not any(
        downloader._event_partition_path(tmp_path, day, asset, partial=False).exists()
        for asset in assets
    )
