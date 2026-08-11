"""Contract tests for the target-blind PIT v2.1 reconciliation gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import mds650.pit_reconciliation_gate_v21 as gate_module
from mds650.pit_reconciliation_gate_v21 import (
    build_pit_reconciliation_gate_v21,
    canonical_sha256,
    write_pit_reconciliation_gate_v21,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "pit-reconciliation-gate-v21.schema.json"
)
PROMOTED_ARTIFACT_PATH = (
    ROOT / "artifacts" / "provider_timing_v21" / "pit_reconciliation_gate_v21_20260812.json"
)
ADDENDUM_PATH = ROOT / "docs" / "pit_reconciliation_gate_v21_addendum_20260812.md"


def test_gate_preserves_conservative_and_fail_closed_pit_states(tmp_path: Path) -> None:
    """The gate must retain study assumptions and B2 failure without an edge claim."""
    sources = _write_valid_sources(tmp_path)

    document = build_pit_reconciliation_gate_v21(**sources)

    assert document["status"] == "CONDITIONAL_NOT_CLOSED"
    assert document["fmp_bar_availability"]["baseline_study_rule"] == (
        "timestamp_raw_plus_1_minute"
    )
    assert document["fmp_bar_availability"]["sensitivity_study_rule"] == (
        "timestamp_raw_plus_2_minutes"
    )
    assert document["fmp_bar_availability"]["provider_semantics_status"] == "UNVERIFIED"
    assert document["massive_b1q_reselection"]["status"] == "PASS_TECHNICAL_TARGET_FREE"
    assert document["legacy_uw_b2_raw_diagnostic"]["status"] == (
        "FAIL_ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY"
    )
    assert document["corrected_uw_b2_availability_sidecar_v22"]["status"] == (
        "PASS_WITH_EXCLUSIONS"
    )
    assert document["corrected_uw_b2_availability_sidecar_v22"]["primary_excluded_row_count"] == 451
    assert (
        document["corrected_uw_b2_availability_sidecar_v22"]["corrected_panel_preparation"]
        == "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD"
    )
    assert document["SAFE_TO_RECONCILE_EXISTING_RESULTS"] == "NO"
    assert document["SAFE_TO_OPEN_OR_EVALUATE_OOS"] == "NO"
    assert document["edge_conclusion"] == "NOT_EVALUATED_TARGET_BLIND"
    assert document["secret_values_emitted"] is False
    assert document["personal_paths_emitted"] is False
    assert all(":" not in item["logical_path"] for item in document["source_evidence"])
    unsigned = dict(document)
    assert document["aggregation_sha256"] == canonical_sha256(
        {key: value for key, value in unsigned.items() if key != "aggregation_sha256"}
    )


def test_gate_rejects_noncanonical_uw_failure_reason(tmp_path: Path) -> None:
    """A differently named UW failure cannot silently satisfy the v2.1 gate."""
    sources = _write_valid_sources(tmp_path)
    uw_payload = json.loads(sources["uw_artifact_path"].read_text(encoding="utf-8"))
    uw_payload["activity_availability_gate_reasons"] = ["UNEXPECTED_REASON"]
    _write_self_hashed_json(sources["uw_artifact_path"], uw_payload, "artifact_sha256")

    try:
        build_pit_reconciliation_gate_v21(**sources)
    except ValueError as exc:
        assert str(exc) == "PIT_V21_UW_REASON_NOT_CANONICAL"
    else:
        raise AssertionError("Expected the gate to reject a noncanonical UW failure reason")


def test_gate_write_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    """Equivalent source evidence must produce stable bytes without overwriting drift."""
    sources = _write_valid_sources(tmp_path)
    output_path = tmp_path / "pit_gate.json"

    first = write_pit_reconciliation_gate_v21(output_path=output_path, **sources)
    first_bytes = output_path.read_bytes()
    second = write_pit_reconciliation_gate_v21(output_path=output_path, **sources)
    second_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()

    assert first == second
    assert first_bytes == output_path.read_bytes()
    assert hashlib.sha256(first_bytes).hexdigest() == second_hash


def test_gate_cli_writes_a_secret_free_contract_artifact(tmp_path: Path) -> None:
    """The local CLI must emit only a compact status and a validated aggregate."""
    sources = _write_valid_sources(tmp_path)
    output_path = tmp_path / "cli_gate.json"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "aggregate_pit_reconciliation_gate_v21.py"),
        "--massive-artifact",
        str(sources["massive_artifact_path"]),
        "--uw-artifact",
        str(sources["uw_artifact_path"]),
        "--pit-contract",
        str(sources["pit_contract_path"]),
        "--decision-ledger",
        str(sources["decision_ledger_path"]),
        "--b2-availability-manifest-v22",
        str(sources["b2_availability_manifest_v22_path"]),
        "--pit-contract-v22",
        str(sources["pit_contract_v22_path"]),
        "--output",
        str(output_path),
    ]

    completed = subprocess.run(command, check=True, capture_output=True, text=True)

    assert "PASS" not in completed.stdout
    assert "CONDITIONAL_NOT_CLOSED" in completed.stdout
    assert str(tmp_path) not in completed.stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["secret_values_emitted"] is False
    assert payload["personal_paths_emitted"] is False


def test_promoted_gate_matches_schema_self_hash_and_hygiene() -> None:
    """The promoted aggregate must be a portable, schema-valid target-blind record."""
    assert SCHEMA_PATH.is_file()
    assert PROMOTED_ARTIFACT_PATH.is_file()
    assert ADDENDUM_PATH.is_file()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    artifact_bytes = PROMOTED_ARTIFACT_PATH.read_bytes()
    payload = json.loads(artifact_bytes)

    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert not errors, "\n".join(error.message for error in errors)
    unsigned = dict(payload)
    recorded_hash = unsigned.pop("aggregation_sha256")
    assert recorded_hash == canonical_sha256(unsigned)
    serialized = artifact_bytes.decode("utf-8")
    assert "C:\\Users\\" not in serialized
    assert "D:\\" not in serialized
    assert "apiKey" not in serialized
    assert recorded_hash in ADDENDUM_PATH.read_text(encoding="utf-8")


def test_gate_fails_closed_for_missing_or_malformed_massive_source(tmp_path: Path) -> None:
    """Missing, malformed, and non-object inputs must not create a gate."""
    sources = _write_valid_sources(tmp_path)
    sources["massive_artifact_path"] = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="PIT_V21_MASSIVE_ARTIFACT_MISSING"):
        build_pit_reconciliation_gate_v21(**sources)

    sources = _write_valid_sources(tmp_path / "invalid")
    sources["massive_artifact_path"].write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="PIT_V21_MASSIVE_ARTIFACT_INVALID_JSON"):
        build_pit_reconciliation_gate_v21(**sources)

    sources = _write_valid_sources(tmp_path / "non_object")
    sources["massive_artifact_path"].write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="PIT_V21_MASSIVE_ARTIFACT_NOT_OBJECT"):
        build_pit_reconciliation_gate_v21(**sources)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("recomputed_result_sha256", "not-a-sha", "PIT_V21_MASSIVE_SELF_HASH_INVALID"),
        ("recomputed_result_sha256", "0" * 64, "PIT_V21_MASSIVE_SELF_HASH_MISMATCH"),
        ("status", "FAIL", "PIT_V21_MASSIVE_STATUS_NOT_TECHNICAL_PASS"),
        ("selection_rule", "not-a-reselection-rule", "PIT_V21_MASSIVE_SELECTION_RULE_INVALID"),
        (
            "no_targets_or_predictive_metrics_read",
            False,
            "PIT_V21_MASSIVE_TARGET_BLIND_ASSERTION_INVALID",
        ),
    ],
)
def test_gate_rejects_invalid_massive_identity_or_claim(
    tmp_path: Path, field: str, value: object, expected: str
) -> None:
    """A Massive self-hash or technical-claim mutation must fail closed."""
    sources = _write_valid_sources(tmp_path)
    payload = json.loads(sources["massive_artifact_path"].read_text(encoding="utf-8"))
    payload[field] = value
    if field == "recomputed_result_sha256":
        sources["massive_artifact_path"].write_text(json.dumps(payload), encoding="utf-8")
    else:
        _write_self_hashed_json(
            sources["massive_artifact_path"], payload, "recomputed_result_sha256"
        )

    with pytest.raises(ValueError, match=expected):
        build_pit_reconciliation_gate_v21(**sources)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("schema_version", "bad", "PIT_V21_UW_SCHEMA_VERSION_INVALID"),
        ("activity_availability_gate", "PASS", "PIT_V21_UW_GATE_NOT_FAIL_CLOSED"),
        ("no_model_or_oos_artifacts_read", False, "PIT_V21_UW_OOS_ASSERTION_INVALID"),
        (
            "no_provider_http_requests_performed",
            False,
            "PIT_V21_UW_PROVIDER_HTTP_ASSERTION_INVALID",
        ),
    ],
)
def test_gate_rejects_invalid_uw_state_assertions(
    tmp_path: Path, field: str, value: object, expected: str
) -> None:
    """The legacy UW failure remains strict about source and OOS assertions."""
    sources = _write_valid_sources(tmp_path)
    payload = json.loads(sources["uw_artifact_path"].read_text(encoding="utf-8"))
    payload[field] = value
    _write_self_hashed_json(sources["uw_artifact_path"], payload, "artifact_sha256")

    with pytest.raises(ValueError, match=expected):
        build_pit_reconciliation_gate_v21(**sources)


@pytest.mark.parametrize(
    ("source_key", "contents", "expected"),
    [
        (
            "pit_contract_path",
            "Completed-bar latency remains unresolved provider facts.",
            "PIT_V21_FMP_BASELINE_RULE_MISSING",
        ),
        (
            "pit_contract_path",
            "timestamp_raw + 1 minute remains a study rule.",
            "PIT_V21_FMP_SEMANTICS_BOUNDARY_MISSING",
        ),
        (
            "decision_ledger_path",
            "SAFE_TO_RECONCILE_EXISTING_RESULTS=NO",
            "PIT_V21_LEDGER_STATUS_MISSING",
        ),
        (
            "decision_ledger_path",
            "PIT_V21=CONDITIONAL_NOT_CLOSED",
            "PIT_V21_LEDGER_RECONCILIATION_GATE_MISSING",
        ),
    ],
)
def test_gate_rejects_missing_fmp_or_ledger_boundaries(
    tmp_path: Path, source_key: str, contents: str, expected: str
) -> None:
    """Study assumptions and sealed-result gates must be explicitly recorded."""
    sources = _write_valid_sources(tmp_path)
    sources[source_key].write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=expected):
        build_pit_reconciliation_gate_v21(**sources)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("b2_availability_sidecar_status", "FAIL", "PIT_V21_B2_V22_STATUS_INVALID"),
        (
            "model_or_metric_payload_read",
            True,
            "PIT_V21_B2_V22_MODEL_ASSERTION_INVALID",
        ),
        ("summary", "not-an-object", "PIT_V21_B2_V22_SUMMARY_INVALID"),
    ],
)
def test_gate_rejects_invalid_v22_sidecar_manifest(
    tmp_path: Path, field: str, value: object, expected: str
) -> None:
    """The corrected sidecar must retain its exact target-blind closure contract."""
    sources = _write_valid_sources(tmp_path)
    manifest_path = sources["b2_availability_manifest_v22_path"]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload[field] = value
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=expected):
        build_pit_reconciliation_gate_v21(**sources)


def test_gate_rejects_missing_v22_contract_boundary(tmp_path: Path) -> None:
    """A corrected sidecar without its new-panel boundary cannot be promoted."""
    sources = _write_valid_sources(tmp_path)
    sources["pit_contract_v22_path"].write_text(
        "B2_AVAILABILITY_SIDECAR = PASS_WITH_EXCLUSIONS. SAFE_TO_RECONCILE_EXISTING_RESULTS = NO.",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="PIT_V21_B2_V22_CONTRACT_NEW_PANEL_BOUNDARY_MISSING"):
        build_pit_reconciliation_gate_v21(**sources)


def test_gate_write_rejects_existing_different_bytes(tmp_path: Path) -> None:
    """An existing output with drift must not be overwritten."""
    sources = _write_valid_sources(tmp_path)
    output_path = tmp_path / "gate.json"
    write_pit_reconciliation_gate_v21(output_path=output_path, **sources)
    output_path.write_bytes(b"drift")

    with pytest.raises(FileExistsError, match="PIT_V21_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"):
        write_pit_reconciliation_gate_v21(output_path=output_path, **sources)


def test_gate_write_rejects_racing_conflicting_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent conflicting writer must not be silently replaced."""
    sources = _write_valid_sources(tmp_path)
    output_path = tmp_path / "race.json"

    def conflicting_link(source: Path, target: Path) -> None:
        del source
        target.write_bytes(b"racing-drift")
        raise FileExistsError

    monkeypatch.setattr(gate_module.os, "link", conflicting_link)
    with pytest.raises(FileExistsError, match="PIT_V21_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"):
        write_pit_reconciliation_gate_v21(output_path=output_path, **sources)
    assert output_path.read_bytes() == b"racing-drift"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"probe": "api_key=not-allowed"}, "PIT_V21_OUTPUT_SECRET_LIKE_CONTENT"),
        ({"probe": "C:\\Users\\someone"}, "PIT_V21_OUTPUT_PERSONAL_PATH"),
    ],
)
def test_gate_sanitization_rejects_secret_like_values_and_personal_paths(
    value: dict[str, str], expected: str
) -> None:
    """The output hygiene guard rejects values that could expose credentials or paths."""
    with pytest.raises(ValueError, match=expected):
        gate_module._assert_sanitized(value)


def _write_valid_sources(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    massive_path = tmp_path / "massive.json"
    uw_path = tmp_path / "uw.json"
    pit_contract_path = tmp_path / "pit_contract.md"
    decision_ledger_path = tmp_path / "decision_ledger.md"
    b2_availability_manifest_v22_path = tmp_path / "b2_availability_manifest_v22.json"
    pit_contract_v22_path = tmp_path / "pit_contract_v22.md"
    massive_payload = {
        "schema_version": "provider-timing-v2.1",
        "status": "PASS",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "selection_rule": (
            "last_quote_by_sip_timestamp_then_sequence_at_or_before_origin_minus_delay"
        ),
    }
    _write_self_hashed_json(massive_path, massive_payload, "recomputed_result_sha256")
    uw_payload = {
        "schema_version": "uw-anomaly-evidence-v2.1",
        "activity_availability_gate": "FAIL",
        "activity_availability_gate_reasons": ["ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY"],
        "no_model_or_oos_artifacts_read": True,
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
    }
    _write_self_hashed_json(uw_path, uw_payload, "artifact_sha256")
    pit_contract_path.write_text(
        "timestamp_raw + 1 minute remains a conservative study rule. "
        "Completed-bar latency remains unresolved provider facts.",
        encoding="utf-8",
    )
    decision_ledger_path.write_text(
        "PIT_V21=CONDITIONAL_NOT_CLOSED\nSAFE_TO_RECONCILE_EXISTING_RESULTS=NO\n",
        encoding="utf-8",
    )
    b2_availability_manifest_v22_path.write_text(
        json.dumps(
            {
                "schema_version": "2.2",
                "b2_availability_sidecar_status": "PASS_WITH_EXCLUSIONS",
                "corrected_pit_panel_preparation": (
                    "PASS_MASK_READY_REQUIRES_NEW_TARGET_BLIND_PANEL_BUILD"
                ),
                "generation_mode": "deterministic_target_blind_rebuild",
                "safe_to_reconcile_existing_results": "NO",
                "sealed_result_reconciliation": "BLOCKED",
                "model_or_metric_payload_read": False,
                "oos_payload_read": False,
                "summary": {"primary_delayed_raw_zero_exclusion_count": 451},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    pit_contract_v22_path.write_text(
        "B2_AVAILABILITY_SIDECAR = PASS_WITH_EXCLUSIONS. "
        "451 rows are excluded. SAFE_TO_RECONCILE_EXISTING_RESULTS = NO. "
        "A new target-blind common B0/B1/B2 panel is required.",
        encoding="utf-8",
    )
    return {
        "massive_artifact_path": massive_path,
        "uw_artifact_path": uw_path,
        "pit_contract_path": pit_contract_path,
        "decision_ledger_path": decision_ledger_path,
        "b2_availability_manifest_v22_path": b2_availability_manifest_v22_path,
        "pit_contract_v22_path": pit_contract_v22_path,
    }


def _write_self_hashed_json(path: Path, payload: dict[str, object], hash_field: str) -> None:
    unsigned = {key: value for key, value in payload.items() if key != hash_field}
    rendered = {**unsigned, hash_field: _fixture_sha256(unsigned)}
    path.write_text(json.dumps(rendered, sort_keys=True), encoding="utf-8")


def _fixture_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
