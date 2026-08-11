"""Tests for the offline, fail-closed successor-confirmation readiness gate."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator

from mds650.confirmation_readiness_v1 import (
    ConfirmationReadinessConfig,
    build_confirmation_readiness,
)

ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest for a small deterministic test file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(payload: dict[str, object]) -> str:
    """Return the canonical JSON hash used by the preregistration fixture."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_bound_artifacts(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object], Path, Path, Path]:
    """Create target-free bound-panel artefacts for a readiness-gate fixture."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    panel = pl.DataFrame(
        {
            "origin_id": ["a", "b"],
            "asset": ["AAPL", "AAPL"],
            "common_predictor_complete": [True, False],
            "b0v2_log_spot": [1.0, 2.0],
            "b2v2_z_log_trade_count": [0.1, 0.2],
        }
    )
    common = panel.filter(pl.col("common_predictor_complete"))
    panel_path = tmp_path / "target_blind_common_predictors_v22.parquet"
    common_path = tmp_path / "target_blind_common_complete_v22.parquet"
    sidecar_path = tmp_path / "b2_row_availability_v22.parquet"
    panel.write_parquet(panel_path)
    common.write_parquet(common_path)
    sidecar_path.write_bytes(b"target-blind-sidecar")

    manifest: dict[str, object] = {
        "schema_version": "target-blind-common-predictor-manifest-v2.2",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "source_hashes": {"b2_availability_sidecar_sha256": _sha256(sidecar_path)},
        "output": {
            "panel_sha256": _sha256(panel_path),
            "row_count": panel.height,
            "common_complete_row_count": common.height,
        },
        "summary": {
            "asset_count": 1,
            "row_count": panel.height,
            "completion_counts": {"common_predictor_complete": common.height},
        },
        "timing_rules": {
            "fmp_primary_delay_minutes": 1,
            "fmp_sensitivity_delay_minutes": 2,
            "b1q_primary_state": "SIP_ASOF_ORIGIN_MAX_AGE_60S",
            "b2_created_at_rule": "OPERATIONAL_AVAILABILITY_PROXY_ORIGIN_MINUS_60_SECONDS",
        },
    }
    preregistration: dict[str, object] = {
        "schema_version": "target-blind-confirmation-preregistration-v2.0",
        "status": "SEALED_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "bound_panel": {"panel_sha256": _sha256(panel_path)},
        "fixed_claim_boundary": {
            "fmp": "TIMESTAMP_RAW_PLUS_1_MINUTE_CONSERVATIVE_STUDY_ASSUMPTION",
            "massive": "SIP_ASOF_ORIGIN_PRIMARY_WITH_60_300_SECOND_RESELECTION_SENSITIVITIES",
            "unusual_whales": (
                "CREATED_AT_OPERATIONAL_AVAILABILITY_PROXY_NOT_PUBLICATION_OR_RECEIPT"
            ),
        },
    }
    preregistration["preregistration_sha256"] = _canonical_sha256(preregistration)
    return manifest, preregistration, panel_path, common_path, sidecar_path


def _config(tmp_path: Path, *, acquisition_requested: bool = False) -> ConfirmationReadinessConfig:
    """Return a deterministic readiness configuration backed by fixture files."""
    manifest, preregistration, panel_path, common_path, sidecar_path = _write_bound_artifacts(
        tmp_path
    )
    return ConfirmationReadinessConfig(
        panel_manifest=manifest,
        preregistration=preregistration,
        panel_path=panel_path,
        common_path=common_path,
        availability_sidecar_path=sidecar_path,
        data_root=tmp_path,
        acquisition_requested=acquisition_requested,
        projected_peak_additional_bytes=10 * 1024**3 if acquisition_requested else None,
        cost_authorization_id="MDS650-CONFIRMATION-1" if acquisition_requested else None,
        environment={
            "FMP_API_KEY": "present",
            "MASSIVE_API_KEY": "present",
            "UNUSUALWHALES_API_KEY": "present",
        },
        observed_free_bytes=100 * 1024**3,
        write_probe_pass=True,
    )


def test_readiness_binds_target_blind_subset_without_authorising_evaluation(tmp_path: Path) -> None:
    """A valid current state is ready for confirmation but never opens OOS."""
    result = build_confirmation_readiness(_config(tmp_path))

    assert result["status"] == "PASS_READY_FOR_CONFIRMATION_ACQUISITION_NOT_REQUESTED"
    assert result["bound_artifact_integrity"]["status"] == "PASS"
    assert result["common_subset_validation"]["status"] == "PASS"
    assert result["safe_to_acquire_new_sample"] == "NO"
    assert result["safe_to_open_or_evaluate_oos"] == "NO"
    assert result["model_fit_performed"] is False
    assert "C:\\Users\\" not in json.dumps(result)
    assert "present" not in json.dumps(result)


def test_readiness_fails_closed_when_common_panel_is_not_exact_subset(tmp_path: Path) -> None:
    """An altered common subset cannot be treated as bound confirmation input."""
    config = _config(tmp_path)
    pl.DataFrame(
        {
            "origin_id": ["a"],
            "asset": ["AAPL"],
            "common_predictor_complete": [True],
            "b0v2_log_spot": [999.0],
            "b2v2_z_log_trade_count": [0.1],
        }
    ).write_parquet(config.common_path)

    result = build_confirmation_readiness(config)

    assert result["status"] == "FAIL_CONFIRMATION_READINESS"
    assert result["common_subset_validation"]["status"] == "FAIL"
    assert result["safe_to_acquire_new_sample"] == "NO"
    assert result["safe_to_open_or_evaluate_oos"] == "NO"


def test_acquisition_request_requires_named_secrets_and_cost_reference(tmp_path: Path) -> None:
    """A proposed acquisition fails when its required operational inputs are absent."""
    config = _config(tmp_path, acquisition_requested=True)
    config = ConfirmationReadinessConfig(
        **{
            **config.__dict__,
            "cost_authorization_id": None,
            "environment": {},
        }
    )

    result = build_confirmation_readiness(config)

    assert result["acquisition_preflight"]["credentials_status"] == "FAIL_MISSING_REQUIRED_NAMES"
    assert result["acquisition_preflight"]["cost_status"] == "FAIL_EXPLICIT_REFERENCE_REQUIRED"
    assert result["safe_to_acquire_new_sample"] == "NO"


def test_operational_inputs_do_not_authorise_acquisition_without_exact_plan(tmp_path: Path) -> None:
    """Secrets, cost and storage cannot replace date-level PIT and a session plan."""
    result = build_confirmation_readiness(_config(tmp_path, acquisition_requested=True))

    assert (
        result["acquisition_preflight"]["status"]
        == "BLOCKED_EXACT_PLAN_AND_PROVIDER_PIT_REQUIRED"
    )
    assert result["safe_to_acquire_new_sample"] == "NO"
    assert result["safe_to_open_or_evaluate_oos"] == "NO"
    assert result["safe_to_reconcile_existing_results"] == "NO"


def test_readiness_snapshot_is_deterministic_for_identical_inputs(tmp_path: Path) -> None:
    """The same bound files and observed values produce one stable report hash."""
    first = build_confirmation_readiness(_config(tmp_path / "first"))
    second = build_confirmation_readiness(_config(tmp_path / "second"))

    assert first["readiness_sha256"] == second["readiness_sha256"]


def test_readiness_rejects_changed_pit_boundary_and_invalid_coverage(tmp_path: Path) -> None:
    """Registered timing rules and coverage provenance are both fail-closed."""
    config = _config(tmp_path)
    manifest = deepcopy(config.panel_manifest)
    assert isinstance(manifest["timing_rules"], dict)
    manifest["timing_rules"]["fmp_primary_delay_minutes"] = 2
    manifest["summary"] = {}

    result = build_confirmation_readiness(replace(config, panel_manifest=manifest))

    assert result["pit_claim_boundary"]["status"] == "FAIL"
    assert "PIT_TIMING_RULE_INVALID_FMP_PRIMARY_DELAY_MINUTES" in result["pit_claim_boundary"][
        "failure_codes"
    ]
    assert result["coverage_observation"]["status"] == "FAIL"
    assert result["ready_for_confirmation"] == "NO"


def test_readiness_rejects_target_like_column_in_bound_panel(tmp_path: Path) -> None:
    """A target-like column invalidates a panel even when the file is readable."""
    config = _config(tmp_path)
    panel = pl.read_parquet(config.panel_path).with_columns(pl.lit(0.1).alias("rv30"))
    common = panel.filter(pl.col("common_predictor_complete"))
    panel.write_parquet(config.panel_path)
    common.write_parquet(config.common_path)

    result = build_confirmation_readiness(config)

    assert result["common_subset_validation"]["status"] == "FAIL"
    assert "TARGET_BLIND_OUTCOME_LIKE_COLUMN_PRESENT" in result["common_subset_validation"][
        "failure_codes"
    ]
    assert result["safe_to_open_or_evaluate_oos"] == "NO"


@pytest.mark.parametrize(
    ("projected_peak", "free_bytes", "write_probe", "expected_storage_status"),
    [
        (None, 100 * 1024**3, True, "FAIL_PROJECTED_PEAK_REQUIRED"),
        (20 * 1024**3, 90 * 1024**3, True, "FAIL_PROJECTED_MINIMUM_BELOW_80_GIB"),
        (10 * 1024**3, 100 * 1024**3, False, "FAIL_DATA_ROOT_WRITE_PROBE"),
    ],
)
def test_acquisition_preflight_rejects_each_storage_gate(
    tmp_path: Path,
    projected_peak: int | None,
    free_bytes: int,
    write_probe: bool,
    expected_storage_status: str,
) -> None:
    """Each missing peak, capacity shortfall and write failure remains explicit."""
    config = _config(tmp_path, acquisition_requested=True)
    config = replace(
        config,
        projected_peak_additional_bytes=projected_peak,
        observed_free_bytes=free_bytes,
        write_probe_pass=write_probe,
    )

    result = build_confirmation_readiness(config)

    assert result["acquisition_preflight"]["storage_status"] == expected_storage_status
    assert result["safe_to_acquire_new_sample"] == "NO"


def test_readiness_rejects_non_positive_declared_storage_peak(tmp_path: Path) -> None:
    """A non-positive peak is invalid configuration rather than unlimited capacity."""
    config = _config(tmp_path)

    with pytest.raises(ValueError, match="CONFIRMATION_PROJECTED_PEAK_BYTES_MUST_BE_POSITIVE"):
        replace(config, projected_peak_additional_bytes=0)


def test_readiness_reports_all_invalid_bound_artifact_guards(tmp_path: Path) -> None:
    """Malformed manifest and preregistration fields cannot pass by partial matching."""
    config = _config(tmp_path)
    manifest = deepcopy(config.panel_manifest)
    preregistration = deepcopy(config.preregistration)
    manifest["schema_version"] = "wrong"
    manifest["status"] = "wrong"
    manifest["safe_to_reconcile_existing_results"] = "YES"
    assert isinstance(manifest["source_hashes"], dict)
    manifest["source_hashes"]["b2_availability_sidecar_sha256"] = "0" * 64
    preregistration["schema_version"] = "wrong"
    preregistration["status"] = "wrong"
    preregistration["safe_to_reconcile_existing_results"] = "YES"
    preregistration["safe_to_open_or_evaluate_oos"] = "YES"
    preregistration["model_fit_performed"] = True
    assert isinstance(preregistration["bound_panel"], dict)
    preregistration["bound_panel"]["panel_sha256"] = "0" * 64
    preregistration["preregistration_sha256"] = "0" * 64

    result = build_confirmation_readiness(
        replace(config, panel_manifest=manifest, preregistration=preregistration)
    )

    failures = result["bound_artifact_integrity"]["failure_codes"]
    assert result["bound_artifact_integrity"]["status"] == "FAIL"
    assert "PANEL_MANIFEST_SCHEMA_INVALID" in failures
    assert "B2_AVAILABILITY_SIDECAR_HASH_MISMATCH" in failures
    assert "PREREGISTRATION_OOS_GATE_INVALID" in failures
    assert "PREREGISTRATION_SELF_HASH_INVALID" in failures


def test_readiness_fails_when_common_file_is_unreadable(tmp_path: Path) -> None:
    """A missing target-blind common file is a failed gate, never an empty sample."""
    config = _config(tmp_path)
    config.common_path.unlink()

    result = build_confirmation_readiness(config)

    assert result["common_subset_validation"]["status"] == "FAIL"
    assert result["common_subset_validation"]["failure_codes"] == [
        "TARGET_BLIND_PARQUET_UNREADABLE"
    ]


def test_acquisition_preflight_fails_for_unavailable_data_root(tmp_path: Path) -> None:
    """A missing storage root is explicit even when secret names and cost are present."""
    config = _config(tmp_path, acquisition_requested=True)
    config = replace(
        config,
        data_root=tmp_path / "missing-root",
        observed_free_bytes=None,
        write_probe_pass=None,
    )

    result = build_confirmation_readiness(config)

    assert result["acquisition_preflight"]["storage_status"] == "FAIL_DATA_ROOT_UNAVAILABLE"
    assert result["safe_to_acquire_new_sample"] == "NO"


def test_readiness_report_conforms_to_committed_json_schema(tmp_path: Path) -> None:
    """The machine-readable readiness snapshot remains contract-valid."""
    schema_path = (
        ROOT
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "confirmation-readiness-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    errors = sorted(
        validator.iter_errors(build_confirmation_readiness(_config(tmp_path))),
        key=str,
    )

    assert errors == []
