from __future__ import annotations

import json
from pathlib import Path

import pytest

from mds650.errors import QualityGateError
from mds650.manifests import load_and_validate_audit_manifest


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "run_id": "run-1",
        "generated_at_utc": "2026-07-20T09:00:00Z",
        "research_feature": "001-pit-options-rv30",
        "research_only": True,
        "secrets_present": True,
        "secret_values_emitted": False,
        "provider_results": [],
        "cross_provider_summary": {
            "b1_point_in_time_status": "BLOCKED_PENDING_HISTORICAL_PIT_OPTION_STATE_PROBE",
        },
        "acceptance": {},
    }


def test_load_and_validate_audit_manifest_returns_explicit_blockers(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")

    result = load_and_validate_audit_manifest(path)

    assert result.sanitized is True
    assert "B1_NOT_AUTHORIZED" in result.blockers


def test_load_and_validate_audit_manifest_rejects_secret_like_content(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest["api_key"] = "must-never-appear"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(QualityGateError, match="AUDIT_MANIFEST_SECRET_CONTENT"):
        load_and_validate_audit_manifest(path)


def _v11_record(
    *,
    record_key: str,
    raw_hash: str,
    request_id: str,
    request_start: str = "2026-07-16T00:00:00Z",
    request_end: str = "2026-07-17T00:00:00Z",
) -> dict[str, object]:
    return {
        "run_id": "run-1",
        "request_id": request_id,
        "provider": "fmp",
        "component": "underlying_1min",
        "asset": "AAPL",
        "request_start": request_start,
        "request_end": request_end,
        "endpoint_fingerprint": "abcdef0123456789",
        "record_key": record_key,
        "raw_response_hashes": [raw_hash],
        "sanitized_response_path": "evidence/fmp/aapl.json",
    }


def test_v11_manifest_rejects_duplicate_composite_record_key(tmp_path: Path) -> None:
    """A repeated seven-field request identity fails instead of being collapsed."""
    manifest = _manifest()
    manifest["schema_version"] = "1.1"
    manifest["provider_results"] = [
        _v11_record(
            record_key=(
                "run-1|fmp|underlying_1min|AAPL|2026-07-16T00:00:00Z|"
                "2026-07-17T00:00:00Z|abcdef0123456789"
            ),
            raw_hash="a" * 64,
            request_id="req-1",
        ),
        _v11_record(
            record_key=(
                "run-1|fmp|underlying_1min|AAPL|2026-07-16T00:00:00Z|"
                "2026-07-17T00:00:00Z|abcdef0123456789"
            ),
            raw_hash="b" * 64,
            request_id="req-2",
        ),
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(QualityGateError, match="AUDIT_MANIFEST_DUPLICATE_RECORD_KEY"):
        load_and_validate_audit_manifest(path)


def test_v11_manifest_rejects_duplicate_identity_with_different_record_key(
    tmp_path: Path,
) -> None:
    """The seven identity fields cannot be repeated by changing serialization."""
    manifest = _manifest()
    manifest["schema_version"] = "1.1"
    first = _v11_record(
        record_key=(
            "run-1|fmp|underlying_1min|AAPL|2026-07-16T00:00:00Z|"
            "2026-07-17T00:00:00Z|abcdef0123456789"
        ),
        raw_hash="a" * 64,
        request_id="req-1",
    )
    second = _v11_record(
        record_key="attacker-chosen-key-that-is-different",
        raw_hash="b" * 64,
        request_id="req-2",
    )
    manifest["provider_results"] = [first, second]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(QualityGateError, match="AUDIT_MANIFEST_DUPLICATE_RECORD_KEY"):
        load_and_validate_audit_manifest(path)


def test_v11_manifest_rejects_hash_reuse_under_distinct_requests(tmp_path: Path) -> None:
    """The same raw response hash cannot silently represent two distinct requests."""
    manifest = _manifest()
    manifest["schema_version"] = "1.1"
    manifest["provider_results"] = [
        _v11_record(
            record_key=(
                "run-1|fmp|underlying_1min|AAPL|2026-07-16T00:00:00Z|"
                "2026-07-17T00:00:00Z|abcdef0123456789"
            ),
            raw_hash="a" * 64,
            request_id="req-1",
        ),
        _v11_record(
            record_key=(
                "run-1|fmp|underlying_1min|AAPL|2026-07-18T00:00:00Z|"
                "2026-07-19T00:00:00Z|abcdef0123456789"
            ),
            raw_hash="a" * 64,
            request_id="req-2",
            request_start="2026-07-18T00:00:00Z",
            request_end="2026-07-19T00:00:00Z",
        ),
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(QualityGateError, match="AUDIT_MANIFEST_DUPLICATE_RAW_HASH"):
        load_and_validate_audit_manifest(path)


def test_v11_manifest_rejects_personal_absolute_paths(tmp_path: Path) -> None:
    """Distributable v1 evidence cannot carry a user's absolute profile path."""
    manifest = _manifest()
    manifest["schema_version"] = "1.1"
    record = _v11_record(
        record_key=(
            "run-1|fmp|underlying_1min|AAPL|2026-07-16T00:00:00Z|"
            "2026-07-17T00:00:00Z|abcdef0123456789"
        ),
        raw_hash="a" * 64,
        request_id="req-1",
    )
    record["sanitized_response_path"] = r"C:\Users\person\AppData\Local\Temp\raw.json"
    manifest["provider_results"] = [record]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(QualityGateError, match="AUDIT_MANIFEST_PERSONAL_PATH"):
        load_and_validate_audit_manifest(path)
