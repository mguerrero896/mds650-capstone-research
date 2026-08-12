"""Fail-closed, target-free controls for the corrected development release.

This module accepts predictor-only rows that were already bound to the v2.4
source contract.  It deliberately has no target, metric, model or holdout I/O
surface.  RV30 binding is a later, separately guarded stage.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

import polars as pl

from mds650.phase6 import B2V2_FEATURES

FROZEN_B2_FEATURES = tuple(B2V2_FEATURES)
REQUIRED_SOURCE_HASH_KEYS = (
    "target_blind_predictor_manifest_sha256",
    "b2_availability_sidecar_sha256",
    "pit_reconciliation_gate_sha256",
    "massive_reselection_sha256",
    "development_source_manifest_sha256",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_COLUMN_TOKENS = frozenset(
    {"target", "rv30", "outcome", "prediction", "qlike", "metric", "model", "loss"}
)
_REQUIRED_PANEL_COLUMNS = frozenset(
    {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "forecast_origin_ns",
        "b0v2_max_predictor_available_at_utc",
        "max_sip_timestamp_ns",
        "b2v2_cutoff_utc",
        "b2v2_max_created_at_utc",
        "b2v2_availability_eligible",
        "b2v2_availability_status",
        "b2v2_predictor_missing_reason",
        "b2v2_predictor_complete",
        "common_predictor_complete",
        *FROZEN_B2_FEATURES,
    }
)


class _JsonSchemaValidator(Protocol):
    """Typed surface required from one runtime JSON Schema validator."""

    def iter_errors(self, instance: object) -> Iterable[object]:
        """Yield validation errors for one JSON-compatible value."""


class _Draft202012ValidatorFactory(Protocol):
    """Typed boundary for the required Draft 2020-12 operations."""

    def __call__(self, schema: Mapping[str, object]) -> _JsonSchemaValidator:
        """Build one validator from a schema mapping."""

    def check_schema(self, schema: Mapping[str, object]) -> None:
        """Raise when the supplied schema is invalid."""


def _load_draft202012_validator() -> _Draft202012ValidatorFactory:
    """Load the untyped runtime package behind the explicit narrow protocol."""
    module = import_module("jsonschema")
    candidate = cast(object, getattr(module, "Draft202012Validator", None))
    if not callable(candidate) or not callable(getattr(candidate, "check_schema", None)):
        raise RuntimeError("CORRECTED_DEVELOPMENT_JSONSCHEMA_VALIDATOR_UNAVAILABLE")
    return cast(_Draft202012ValidatorFactory, candidate)


_DRAFT202012_VALIDATOR = _load_draft202012_validator()


@dataclass(frozen=True)
class PreparedCorrectedDevelopmentPanel:
    """Target-free predictor frames and observed B2 exclusion count.

    Parameters
    ----------
    panel:
        All predictor rows from the fixed development sessions, including
        explicit B2 exclusions.
    common:
        The nested common-complete subset, still target-free.
    development_sessions:
        Ordered fixed development session dates.
    b2_excluded_origin_count:
        Count of rows excluded by the B2 availability policy.
    """

    panel: pl.DataFrame
    common: pl.DataFrame
    development_sessions: tuple[str, ...]
    b2_excluded_origin_count: int


def prepare_corrected_development_panel(
    *,
    panel: pl.DataFrame,
    development_sessions: Sequence[str],
    holdout_sessions: Sequence[str],
) -> PreparedCorrectedDevelopmentPanel:
    """Filter and validate a target-free corrected development predictor panel.

    Parameters
    ----------
    panel:
        Predictor-only v2.4 panel. It may contain dates outside development,
        which are removed before the release is materialized.
    development_sessions:
        Ordered, unique list of exactly 80 approved XNYS development dates.
    holdout_sessions:
        Ordered, unique list of the ten prospective dates to exclude.

    Returns
    -------
    PreparedCorrectedDevelopmentPanel
        Deterministically sorted development-only rows and their
        common-complete subset.

    Raises
    ------
    ValueError
        If session identity, predictor timing, B2 availability encoding or a
        forbidden target-like column violates the release contract.

    Notes
    -----
    This routine only receives predictor rows. It does not accept a target
    path, target value, loss, forecast or model object.
    """
    development = _validated_development_sessions(development_sessions, holdout_sessions)
    _assert_predictor_columns(panel)

    development_panel = panel.filter(pl.col("session_date").is_in(development)).sort(
        ["session_date", "origin_id"]
    )
    observed_dates = development_panel.get_column("session_date").unique().sort().to_list()
    if observed_dates != development:
        raise ValueError("CORRECTED_DEVELOPMENT_SESSION_COVERAGE_MISMATCH")
    _assert_unique_origins(development_panel)
    _assert_predictor_timing(development_panel)
    _assert_b2_encoding(development_panel)

    common = development_panel.filter(pl.col("common_predictor_complete").fill_null(False))
    _assert_common_rows_have_complete_b2(common)
    excluded_count = development_panel.filter(
        ~pl.col("b2v2_availability_eligible").fill_null(False)
    ).height
    return PreparedCorrectedDevelopmentPanel(
        panel=development_panel,
        common=common,
        development_sessions=tuple(development),
        b2_excluded_origin_count=excluded_count,
    )


def build_corrected_development_release(
    *,
    prepared: PreparedCorrectedDevelopmentPanel,
    source_hashes: Mapping[str, str],
    output_hashes: Mapping[str, str | int],
    source_locations: Mapping[str, str],
    release_id: str,
) -> dict[str, Any]:
    """Create a deterministic, target-free corrected release manifest.

    Parameters
    ----------
    prepared:
        Passing predictor-only release prepared by
        :func:`prepare_corrected_development_panel`.
    source_hashes:
        Five SHA-256 records mandated by the corrected-release contract.
    output_hashes:
        SHA-256 identities and row counts of the newly written target-free
        predictor and common-complete Parquet outputs.
    source_locations:
        Logical D: locations for input and newly written predictor outputs.
        They are validated but intentionally omitted from the manifest so the
        release contains no personal filesystem path.
    release_id:
        Stable, lower-case release identifier.

    Returns
    -------
    dict[str, Any]
        Draft 2020-12 compatible manifest with a canonical self-hash.

    Raises
    ------
    ValueError
        If a hash, location or release identity is invalid.
    """
    _assert_release_id(release_id)
    _assert_source_hashes(source_hashes)
    _assert_output_hashes(output_hashes, prepared)
    _assert_safe_logical_locations(source_locations)
    manifest: dict[str, Any] = {
        "artifact_type": "corrected-development-release-v1",
        "schema_version": "1.0.0",
        "release_id": release_id,
        "status": "TARGET_BLIND_READY",
        "scope": "corrected_development_only_no_oos_no_legacy_reconciliation",
        "development_sessions": list(prepared.development_sessions),
        "source_hashes": {key: source_hashes[key] for key in REQUIRED_SOURCE_HASH_KEYS},
        "output": {
            "panel_sha256": output_hashes["panel_sha256"],
            "common_complete_sha256": output_hashes["common_complete_sha256"],
            "panel_row_count": output_hashes["panel_row_count"],
            "common_complete_row_count": output_hashes["common_complete_row_count"],
        },
        "b2_exclusions": {
            "excluded_origin_count": prepared.b2_excluded_origin_count,
            "encoding": "ALL_NINE_B2_FEATURES_NULL_WITH_ELIGIBILITY_FLAG_AND_REASON",
            "zero_activity_rule": "ELIGIBLE_WINDOW_NO_ACTIVITY_AND_NO_DELAY_INCIDENT_ONLY",
        },
        "gates": {
            "safe_to_evaluate_corrected_development": "NO",
            "safe_to_reconcile_existing_results": "NO",
            "safe_to_open_or_evaluate_oos": "NO",
            "holdout_overlap_count": 0,
            "future_predictor_count": 0,
            "duplicate_origin_count": 0,
        },
        "no_target_or_metric_payload_read_during_predictor_build": True,
        "model_fit_performed": False,
    }
    manifest["release_sha256"] = _canonical_sha256(manifest)
    return manifest


def validate_corrected_development_release(release: Mapping[str, Any], schema_path: Path) -> None:
    """Validate one release manifest against its schema and canonical self-hash.

    Parameters
    ----------
    release:
        JSON-compatible corrected-development manifest.
    schema_path:
        Local Draft 2020-12 contract path.

    Raises
    ------
    ValueError
        If the schema cannot be read, the manifest violates it, or the
        self-hash differs from its canonical content.
    """
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise ValueError("schema must be an object")
        _DRAFT202012_VALIDATOR.check_schema(schema)
        errors = list(_DRAFT202012_VALIDATOR(schema).iter_errors(dict(release)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("CORRECTED_DEVELOPMENT_RELEASE_SCHEMA_UNREADABLE") from exc
    if errors:
        raise ValueError("CORRECTED_DEVELOPMENT_RELEASE_SCHEMA_VIOLATION")
    release_hash = release.get("release_sha256")
    unsigned = dict(release)
    unsigned.pop("release_sha256", None)
    if not isinstance(release_hash, str) or _canonical_sha256(unsigned) != release_hash:
        raise ValueError("CORRECTED_DEVELOPMENT_RELEASE_SELF_HASH_MISMATCH")


def assert_safe_corrected_development_paths(paths: Mapping[str, Path]) -> None:
    """Reject personal, cloud-synced or non-D: release paths before any I/O.

    Parameters
    ----------
    paths:
        Named paths proposed for corrected-release inputs or outputs.

    Raises
    ------
    ValueError
        If a path is personal, cloud-synced or a data output escapes
        ``D:/MDS650``.
    """
    for role, path in paths.items():
        normalised = path.as_posix().casefold()
        if role != "artifact_root" and ("/users/" in normalised or "/onedrive/" in normalised):
            raise ValueError(f"CORRECTED_DEVELOPMENT_UNSAFE_PATH:{role}")
        if role in {
            "output_root",
            "predictor_panel",
            "corrected_panel",
            "corrected_common",
        } and not normalised.startswith("d:/mds650/"):
            raise ValueError(f"CORRECTED_DEVELOPMENT_UNSAFE_PATH:{role}")


def _validated_development_sessions(
    development_sessions: Sequence[str], holdout_sessions: Sequence[str]
) -> list[str]:
    development = list(development_sessions)
    holdout = list(holdout_sessions)
    if len(development) != 80 or development != sorted(set(development)):
        raise ValueError("CORRECTED_DEVELOPMENT_SESSION_IDENTITY_INVALID")
    if len(holdout) != 10 or holdout != sorted(set(holdout)):
        raise ValueError("CORRECTED_DEVELOPMENT_HOLDOUT_IDENTITY_INVALID")
    if set(development) & set(holdout):
        raise ValueError("CORRECTED_DEVELOPMENT_HOLDOUT_OVERLAP")
    return development


def _assert_predictor_columns(panel: pl.DataFrame) -> None:
    missing = _REQUIRED_PANEL_COLUMNS - set(panel.columns)
    if missing:
        raise ValueError("CORRECTED_DEVELOPMENT_REQUIRED_COLUMN_MISSING")
    for column in panel.columns:
        tokens = (token for token in re.split(r"[^a-z0-9]+", column.casefold()) if token)
        if any(token in _FORBIDDEN_COLUMN_TOKENS for token in tokens):
            raise ValueError("CORRECTED_DEVELOPMENT_FORBIDDEN_COLUMN")


def _assert_unique_origins(panel: pl.DataFrame) -> None:
    origins = panel.get_column("origin_id")
    if origins.null_count() or origins.n_unique() != panel.height:
        raise ValueError("CORRECTED_DEVELOPMENT_DUPLICATE_ORIGIN")


def _assert_predictor_timing(panel: pl.DataFrame) -> None:
    future_b0 = panel.filter(
        pl.col("b0v2_max_predictor_available_at_utc") > pl.col("forecast_origin_utc")
    )
    future_b1 = panel.filter(pl.col("max_sip_timestamp_ns") > pl.col("forecast_origin_ns"))
    future_b2_cutoff = panel.filter(pl.col("b2v2_cutoff_utc") > pl.col("forecast_origin_utc"))
    future_b2_created = panel.filter(
        pl.col("b2v2_max_created_at_utc").is_not_null()
        & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
    )
    if any(frame.height for frame in (future_b0, future_b1, future_b2_cutoff, future_b2_created)):
        raise ValueError("CORRECTED_DEVELOPMENT_FUTURE_PREDICTOR")


def _assert_b2_encoding(panel: pl.DataFrame) -> None:
    if panel.get_column("b2v2_availability_eligible").null_count():
        raise ValueError("CORRECTED_DEVELOPMENT_B2_ELIGIBILITY_NULL")
    excluded = panel.filter(~pl.col("b2v2_availability_eligible"))
    if excluded.is_empty():
        return
    for feature in FROZEN_B2_FEATURES:
        if excluded.get_column(feature).null_count() != excluded.height:
            raise ValueError("CORRECTED_DEVELOPMENT_B2_EXCLUDED_FEATURE_NOT_NULL")
    invalid_metadata = excluded.filter(
        pl.col("b2v2_availability_status").is_null()
        | pl.col("b2v2_predictor_missing_reason").is_null()
        | (pl.col("b2v2_predictor_missing_reason").str.len_chars() == 0)
    )
    if invalid_metadata.height:
        raise ValueError("CORRECTED_DEVELOPMENT_B2_EXCLUSION_REASON_INVALID")


def _assert_common_rows_have_complete_b2(common: pl.DataFrame) -> None:
    if common.is_empty():
        return
    if common.filter(~pl.col("b2v2_availability_eligible")).height:
        raise ValueError("CORRECTED_DEVELOPMENT_COMMON_INCLUDES_B2_EXCLUSION")
    for feature in FROZEN_B2_FEATURES:
        if common.get_column(feature).null_count():
            raise ValueError("CORRECTED_DEVELOPMENT_COMMON_B2_MISSING")


def _assert_release_id(release_id: str) -> None:
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{7,127}", release_id) is None:
        raise ValueError("CORRECTED_DEVELOPMENT_RELEASE_ID_INVALID")


def _assert_source_hashes(source_hashes: Mapping[str, str]) -> None:
    if set(source_hashes) != set(REQUIRED_SOURCE_HASH_KEYS):
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_HASH_KEYS_INVALID")
    if any(
        _SHA256_PATTERN.fullmatch(source_hashes[key]) is None for key in REQUIRED_SOURCE_HASH_KEYS
    ):
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_HASH_INVALID")


def _assert_output_hashes(
    output_hashes: Mapping[str, str | int], prepared: PreparedCorrectedDevelopmentPanel
) -> None:
    required = {
        "panel_sha256",
        "common_complete_sha256",
        "panel_row_count",
        "common_complete_row_count",
    }
    if set(output_hashes) != required:
        raise ValueError("CORRECTED_DEVELOPMENT_OUTPUT_HASH_KEYS_INVALID")
    for key in ("panel_sha256", "common_complete_sha256"):
        value = output_hashes[key]
        if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("CORRECTED_DEVELOPMENT_OUTPUT_HASH_INVALID")
    if (
        output_hashes["panel_row_count"] != prepared.panel.height
        or output_hashes["common_complete_row_count"] != prepared.common.height
    ):
        raise ValueError("CORRECTED_DEVELOPMENT_OUTPUT_ROW_COUNT_MISMATCH")


def _assert_safe_logical_locations(source_locations: Mapping[str, str]) -> None:
    required = {"predictor_panel", "corrected_panel", "corrected_common"}
    if set(source_locations) != required:
        raise ValueError("CORRECTED_DEVELOPMENT_LOCATION_KEYS_INVALID")
    for role, location in source_locations.items():
        normalised = location.replace("\\", "/").casefold()
        if not normalised.startswith("d:/mds650/") or "/users/" in normalised:
            raise ValueError(f"CORRECTED_DEVELOPMENT_UNSAFE_LOCATION:{role}")


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()
