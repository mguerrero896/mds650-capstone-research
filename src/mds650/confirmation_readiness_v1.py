"""Fail-closed readiness checks for a future MDS650 confirmation study.

The module intentionally accepts only target-blind predictor artefacts and
operational metadata.  It cannot read RV30, forecasts, losses, model outputs,
or sealed out-of-sample payloads. It can report whether operational acquisition
inputs are present, but it never authorises an acquisition, an out-of-sample
read, or reconciliation of pre-v2.2 results.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from mds650.phase5_storage import MINIMUM_PHASE5_FREE_BYTES
from mds650.study_design import canonical_sha256

REQUIRED_PROVIDER_SECRET_NAMES: tuple[str, ...] = (
    "FMP_API_KEY",
    "MASSIVE_API_KEY",
    "UNUSUALWHALES_API_KEY",
)
_FORBIDDEN_EXACT = frozenset({"rv30", "qlike", "target", "prediction", "outcome"})
_FORBIDDEN_PREFIXES = ("rv30_", "target_", "prediction_", "outcome_")
_COST_AUTHORIZATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


@dataclass(frozen=True)
class ConfirmationReadinessConfig:
    """Describe one offline readiness assessment for a future confirmation.

    Parameters
    ----------
    panel_manifest:
        Parsed target-blind v2.2 common-predictor manifest.
    preregistration:
        Parsed, self-hashed successor preregistration bound to the panel.
    panel_path, common_path, availability_sidecar_path:
        Local target-blind artefacts.  Their absolute paths are never emitted.
    data_root:
        Persistent storage root used only for a future acquisition preflight.
    acquisition_requested:
        Whether this invocation evaluates a specifically proposed acquisition.
    projected_peak_additional_bytes:
        Conservative temporary-plus-permanent peak for that proposal.  It is
        mandatory when ``acquisition_requested`` is true.
    cost_authorization_id:
        Non-secret reference to a separately approved acquisition cost.
    environment:
        Environment mapping used only to test whether required secret *names*
        are populated; values are never retained or emitted.
    observed_free_bytes, write_probe_pass:
        Optional injected storage observations for deterministic tests.  With
        ``None``, the module reads current free space and uses a tiny temporary
        write probe only when an acquisition was requested.

    Raises
    ------
    ValueError
        If a proposed peak is not a positive integer.

    Notes
    -----
    This configuration cannot authorise model fitting, OOS access, provider
    calls, or reconciliation.  It only reports whether an acquisition request
    has supplied the operational evidence needed for a later, separate gate.
    """

    panel_manifest: Mapping[str, Any]
    preregistration: Mapping[str, Any]
    panel_path: Path
    common_path: Path
    availability_sidecar_path: Path
    data_root: Path
    acquisition_requested: bool
    projected_peak_additional_bytes: int | None
    cost_authorization_id: str | None
    environment: Mapping[str, str | None]
    observed_free_bytes: int | None = None
    write_probe_pass: bool | None = None

    def __post_init__(self) -> None:
        """Reject an invalid declared peak before any readiness state is emitted."""
        if (
            self.projected_peak_additional_bytes is not None
            and self.projected_peak_additional_bytes <= 0
        ):
            raise ValueError("CONFIRMATION_PROJECTED_PEAK_BYTES_MUST_BE_POSITIVE")


def build_confirmation_readiness(config: ConfirmationReadinessConfig) -> dict[str, Any]:
    """Build a sanitized, fail-closed confirmation-readiness snapshot.

    Parameters
    ----------
    config:
        Target-blind input identity plus optional acquisition metadata.

    Returns
    -------
    dict[str, Any]
        A self-hashing report with separate artefact, PIT, coverage and
        acquisition statuses.  ``safe_to_open_or_evaluate_oos`` and
        ``safe_to_reconcile_existing_results`` are always ``"NO"``.

    Raises
    ------
    ValueError
        If ``config`` declares a non-positive storage peak.

    Notes
    -----
    A pass means that the supplied target-blind artefacts are internally
    consistent.  It is not evidence of an edge, a model fit, a provider
    entitlement, or permission to read a sealed holdout.
    """
    artifact_integrity = _validate_bound_artifacts(config)
    common_subset = _validate_common_subset(config)
    pit_boundary = _validate_pit_boundary(config)
    coverage = _coverage_observation(config)
    acquisition = _acquisition_preflight(config)

    core_pass = all(
        record["status"] == "PASS"
        for record in (artifact_integrity, common_subset, pit_boundary, coverage)
    )
    if not core_pass:
        status = "FAIL_CONFIRMATION_READINESS"
    elif not config.acquisition_requested:
        status = "PASS_READY_FOR_CONFIRMATION_ACQUISITION_NOT_REQUESTED"
    else:
        status = "BLOCKED_CONFIRMATION_ACQUISITION_PREFLIGHT_INCOMPLETE"

    report: dict[str, Any] = {
        "schema_version": "confirmation-readiness-v1.0",
        "status": status,
        "scope": "offline_target_blind_readiness_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "safe_to_reconcile_existing_results": "NO",
        "safe_to_open_or_evaluate_oos": "NO",
        "ready_for_confirmation": "YES" if core_pass else "NO",
        "safe_to_acquire_new_sample": "NO",
        "bound_artifact_integrity": artifact_integrity,
        "common_subset_validation": common_subset,
        "pit_claim_boundary": pit_boundary,
        "coverage_observation": coverage,
        "acquisition_preflight": acquisition,
        "required_before_any_oos_access": [
            "separate_successor_method_freeze",
            "zero_oos_read_access_ledger_at_freeze",
            "literature_owner_verification",
            "explicit_human_authorization_for_one_oos_access",
        ],
        "acquisition_preflight_requirements": [
            "exact_session_allowlist_and_holdout_exclusion",
            "provider_entitlement_and_date_level_pit_preflight",
            "projected_peak_storage_bytes",
            "named_secret_presence_without_secret_emission",
            "explicit_cost_authorization_reference",
        ],
    }
    report["readiness_sha256"] = canonical_sha256(report)
    return report


def _validate_bound_artifacts(config: ConfirmationReadinessConfig) -> dict[str, Any]:
    """Validate hashes and preregistration binding without reading outcomes."""
    panel_manifest = config.panel_manifest
    preregistration = config.preregistration
    failures: list[str] = []
    expected_panel_hash = _nested_string(panel_manifest, "output", "panel_sha256")
    expected_sidecar_hash = _nested_string(
        panel_manifest, "source_hashes", "b2_availability_sidecar_sha256"
    )
    observed_panel_hash = _safe_sha256(config.panel_path)
    observed_sidecar_hash = _safe_sha256(config.availability_sidecar_path)
    if panel_manifest.get("schema_version") != "target-blind-common-predictor-manifest-v2.2":
        failures.append("PANEL_MANIFEST_SCHEMA_INVALID")
    if panel_manifest.get("status") != "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED":
        failures.append("PANEL_MANIFEST_STATUS_INVALID")
    if panel_manifest.get("safe_to_reconcile_existing_results") != "NO":
        failures.append("PANEL_MANIFEST_RECONCILIATION_GATE_INVALID")
    if expected_panel_hash is None or observed_panel_hash != expected_panel_hash:
        failures.append("TARGET_BLIND_PANEL_HASH_MISMATCH")
    if expected_sidecar_hash is None or observed_sidecar_hash != expected_sidecar_hash:
        failures.append("B2_AVAILABILITY_SIDECAR_HASH_MISMATCH")
    if preregistration.get("schema_version") != "target-blind-confirmation-preregistration-v2.0":
        failures.append("PREREGISTRATION_SCHEMA_INVALID")
    if preregistration.get("status") != "SEALED_PRE_METHOD_FREEZE_NOT_AUTHORIZED_FOR_OOS":
        failures.append("PREREGISTRATION_STATUS_INVALID")
    if preregistration.get("safe_to_reconcile_existing_results") != "NO":
        failures.append("PREREGISTRATION_RECONCILIATION_GATE_INVALID")
    if preregistration.get("safe_to_open_or_evaluate_oos") != "NO":
        failures.append("PREREGISTRATION_OOS_GATE_INVALID")
    if preregistration.get("model_fit_performed") is not False:
        failures.append("PREREGISTRATION_MODEL_FIT_GATE_INVALID")
    if _nested_string(preregistration, "bound_panel", "panel_sha256") != expected_panel_hash:
        failures.append("PREREGISTRATION_PANEL_BINDING_MISMATCH")
    preregistration_hash = preregistration.get("preregistration_sha256")
    unsigned = {
        key: value for key, value in preregistration.items() if key != "preregistration_sha256"
    }
    if not isinstance(preregistration_hash, str) or preregistration_hash != canonical_sha256(
        unsigned
    ):
        failures.append("PREREGISTRATION_SELF_HASH_INVALID")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": failures,
        "panel_sha256_expected": expected_panel_hash,
        "panel_sha256_observed": observed_panel_hash,
        "availability_sidecar_sha256_expected": expected_sidecar_hash,
        "availability_sidecar_sha256_observed": observed_sidecar_hash,
    }


def _validate_common_subset(config: ConfirmationReadinessConfig) -> dict[str, Any]:
    """Require the common file to be the exact complete subset of the full panel."""
    failures: list[str] = []
    try:
        panel = pl.read_parquet(config.panel_path)
        common = pl.read_parquet(config.common_path)
    except (OSError, pl.exceptions.PolarsError):
        return {
            "status": "FAIL",
            "failure_codes": ["TARGET_BLIND_PARQUET_UNREADABLE"],
            "panel_row_count": None,
            "common_complete_row_count": None,
            "common_complete_sha256_observed": _safe_sha256(config.common_path),
        }
    required = {"origin_id", "common_predictor_complete"}
    if not required <= set(panel.columns) or not required <= set(common.columns):
        failures.append("TARGET_BLIND_COMMON_REQUIRED_COLUMNS_MISSING")
    if _contains_outcome_like_columns(panel.columns) or _contains_outcome_like_columns(
        common.columns
    ):
        failures.append("TARGET_BLIND_OUTCOME_LIKE_COLUMN_PRESENT")
    expected_rows = _nested_int(config.panel_manifest, "output", "row_count")
    expected_common = _nested_int(config.panel_manifest, "output", "common_complete_row_count")
    if expected_rows != panel.height:
        failures.append("TARGET_BLIND_PANEL_ROW_COUNT_MISMATCH")
    if expected_common != common.height:
        failures.append("TARGET_BLIND_COMMON_ROW_COUNT_MISMATCH")
    if "origin_id" in panel.columns and panel.get_column("origin_id").n_unique() != panel.height:
        failures.append("TARGET_BLIND_PANEL_ORIGIN_ID_DUPLICATE")
    if "origin_id" in common.columns and common.get_column("origin_id").n_unique() != common.height:
        failures.append("TARGET_BLIND_COMMON_ORIGIN_ID_DUPLICATE")
    if not failures:
        if not common.get_column("common_predictor_complete").all():
            failures.append("TARGET_BLIND_COMMON_COMPLETENESS_FLAG_FALSE")
        common_ids = common.get_column("origin_id").to_list()
        expected_common_frame = panel.filter(pl.col("origin_id").is_in(common_ids)).sort(
            "origin_id"
        )
        observed_common_frame = common.sort("origin_id")
        if not expected_common_frame.equals(observed_common_frame):
            failures.append("TARGET_BLIND_COMMON_NOT_EXACT_SUBSET")
        expected_origin_count = panel.filter(pl.col("common_predictor_complete")).height
        if expected_origin_count != common.height:
            failures.append("TARGET_BLIND_COMMON_COMPLETENESS_COUNT_MISMATCH")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": failures,
        "panel_row_count": panel.height,
        "common_complete_row_count": common.height,
        "common_complete_sha256_observed": _safe_sha256(config.common_path),
    }


def _validate_pit_boundary(config: ConfirmationReadinessConfig) -> dict[str, Any]:
    """Check that the registered proxy-only timing boundary remains unchanged."""
    rules = config.panel_manifest.get("timing_rules")
    claims = config.preregistration.get("fixed_claim_boundary")
    failures: list[str] = []
    if not isinstance(rules, Mapping):
        failures.append("PANEL_TIMING_RULES_MISSING")
    else:
        expected_rules = {
            "fmp_primary_delay_minutes": 1,
            "fmp_sensitivity_delay_minutes": 2,
            "b1q_primary_state": "SIP_ASOF_ORIGIN_MAX_AGE_60S",
            "b2_created_at_rule": "OPERATIONAL_AVAILABILITY_PROXY_ORIGIN_MINUS_60_SECONDS",
        }
        for key, value in expected_rules.items():
            if rules.get(key) != value:
                failures.append(f"PIT_TIMING_RULE_INVALID_{key.upper()}")
    if not isinstance(claims, Mapping):
        failures.append("PREREGISTRATION_CLAIM_BOUNDARY_MISSING")
    else:
        expected_claims = {
            "fmp": "TIMESTAMP_RAW_PLUS_1_MINUTE_CONSERVATIVE_STUDY_ASSUMPTION",
            "massive": "SIP_ASOF_ORIGIN_PRIMARY_WITH_60_300_SECOND_RESELECTION_SENSITIVITIES",
            "unusual_whales": (
                "CREATED_AT_OPERATIONAL_AVAILABILITY_PROXY_NOT_PUBLICATION_OR_RECEIPT"
            ),
        }
        for key, value in expected_claims.items():
            if claims.get(key) != value:
                failures.append(f"PIT_CLAIM_BOUNDARY_INVALID_{key.upper()}")
    return {"status": "PASS" if not failures else "FAIL", "failure_codes": failures}


def _coverage_observation(config: ConfirmationReadinessConfig) -> dict[str, Any]:
    """Expose target-free coverage provenance without declaring model viability."""
    summary = config.panel_manifest.get("summary")
    if not isinstance(summary, Mapping):
        return {"status": "FAIL", "failure_codes": ["PANEL_COVERAGE_SUMMARY_MISSING"]}
    row_count = summary.get("row_count")
    common_count = summary.get("completion_counts", {}).get("common_predictor_complete")
    asset_count = summary.get("asset_count")
    if (
        not isinstance(row_count, int)
        or not isinstance(common_count, int)
        or not isinstance(asset_count, int)
        or row_count <= 0
        or common_count <= 0
        or common_count > row_count
        or asset_count <= 0
    ):
        return {"status": "FAIL", "failure_codes": ["PANEL_COVERAGE_SUMMARY_INVALID"]}
    return {
        "status": "PASS",
        "classification": "OBSERVED_TARGET_BLIND_COVERAGE_NOT_MODEL_EVALUATED",
        "asset_count": asset_count,
        "origin_count": row_count,
        "common_complete_origin_count": common_count,
        "common_complete_rate": common_count / row_count,
    }


def _acquisition_preflight(config: ConfirmationReadinessConfig) -> dict[str, Any]:
    """Check only operational conditions for an explicitly requested acquisition."""
    if not config.acquisition_requested:
        return {
            "status": "NOT_APPLICABLE",
            "credentials_status": "NOT_APPLICABLE",
            "cost_status": "NOT_APPLICABLE",
            "storage_status": "OBSERVED_NOT_USED_FOR_ACQUISITION",
            "data_root_label": "MDS650_DATA_ROOT",
            "observed_free_bytes": _observed_free_bytes(config),
            "write_probe_pass": None,
        }
    missing = [name for name in REQUIRED_PROVIDER_SECRET_NAMES if not config.environment.get(name)]
    credentials_status = "PASS_PRESENT_BY_NAME" if not missing else "FAIL_MISSING_REQUIRED_NAMES"
    cost_status = (
        "PASS_EXPLICIT_REFERENCE_PRESENT"
        if (
            config.cost_authorization_id
            and _COST_AUTHORIZATION_PATTERN.fullmatch(config.cost_authorization_id)
        )
        else "FAIL_EXPLICIT_REFERENCE_REQUIRED"
    )
    storage = _storage_status(config)
    operational_inputs_pass = (
        credentials_status == "PASS_PRESENT_BY_NAME"
        and cost_status == "PASS_EXPLICIT_REFERENCE_PRESENT"
        and storage["status"] == "PASS"
    )
    status = "BLOCKED_EXACT_PLAN_AND_PROVIDER_PIT_REQUIRED" if operational_inputs_pass else "FAIL"
    return {
        "status": status,
        "operational_inputs_pass": operational_inputs_pass,
        "credentials_status": credentials_status,
        "missing_credential_names": missing,
        "cost_status": cost_status,
        "cost_authorization_reference_present": cost_status == "PASS_EXPLICIT_REFERENCE_PRESENT",
        "storage_status": storage["status"],
        "data_root_label": "MDS650_DATA_ROOT",
        "observed_free_bytes": storage["observed_free_bytes"],
        "projected_peak_additional_bytes": config.projected_peak_additional_bytes,
        "projected_minimum_free_bytes": storage["projected_minimum_free_bytes"],
        "minimum_free_bytes": MINIMUM_PHASE5_FREE_BYTES,
        "write_probe_pass": storage["write_probe_pass"],
    }


def _storage_status(config: ConfirmationReadinessConfig) -> dict[str, Any]:
    """Evaluate the declared peak while preserving a strict 80-GiB floor."""
    if config.projected_peak_additional_bytes is None:
        return {
            "status": "FAIL_PROJECTED_PEAK_REQUIRED",
            "observed_free_bytes": _observed_free_bytes(config),
            "projected_minimum_free_bytes": None,
            "write_probe_pass": None,
        }
    free_bytes = _observed_free_bytes(config)
    if free_bytes is None:
        return {
            "status": "FAIL_DATA_ROOT_UNAVAILABLE",
            "observed_free_bytes": None,
            "projected_minimum_free_bytes": None,
            "write_probe_pass": False,
        }
    projected_minimum = free_bytes - config.projected_peak_additional_bytes
    write_probe_pass = _write_probe(config)
    if projected_minimum < MINIMUM_PHASE5_FREE_BYTES:
        status = "FAIL_PROJECTED_MINIMUM_BELOW_80_GIB"
    elif not write_probe_pass:
        status = "FAIL_DATA_ROOT_WRITE_PROBE"
    else:
        status = "PASS"
    return {
        "status": status,
        "observed_free_bytes": free_bytes,
        "projected_minimum_free_bytes": projected_minimum,
        "write_probe_pass": write_probe_pass,
    }


def _observed_free_bytes(config: ConfirmationReadinessConfig) -> int | None:
    """Return injected free space or a local storage observation without emitting paths."""
    if config.observed_free_bytes is not None:
        return config.observed_free_bytes
    try:
        return shutil.disk_usage(config.data_root).free
    except OSError:
        return None


def _write_probe(config: ConfirmationReadinessConfig) -> bool:
    """Perform a tiny local write probe only for a requested acquisition."""
    if config.write_probe_pass is not None:
        return config.write_probe_pass
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=config.data_root,
            prefix=".mds650-confirmation-preflight-",
            delete=True,
        ) as handle:
            handle.write(b"MDS650_CONFIRMATION_PREFLIGHT")
            handle.flush()
    except OSError:
        return False
    return True


def _safe_sha256(path: Path) -> str | None:
    """Hash one file incrementally, returning ``None`` instead of leaking a path."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _nested_string(payload: Mapping[str, Any], key: str, nested_key: str) -> str | None:
    """Return one nested string only when its type is valid."""
    nested = payload.get(key)
    value = nested.get(nested_key) if isinstance(nested, Mapping) else None
    return value if isinstance(value, str) else None


def _nested_int(payload: Mapping[str, Any], key: str, nested_key: str) -> int | None:
    """Return one nested integer only when its type is valid."""
    nested = payload.get(key)
    value = nested.get(nested_key) if isinstance(nested, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _contains_outcome_like_columns(columns: list[str]) -> bool:
    """Return whether a target-like field escaped into a target-blind table."""
    return any(
        column.casefold() in _FORBIDDEN_EXACT or column.casefold().startswith(_FORBIDDEN_PREFIXES)
        for column in columns
    )
