"""Target-blind forensic evidence for Unusual Whales B2 anomaly coding.

This module deliberately reads only Full Tape timestamp fields and canonical B2
feature/provenance fields. It never opens targets, outcomes, predictive metrics,
model artefacts, or provider network connections.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import jsonschema  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from mds650.provider_timing_v21 import (
    B2_FEATURE_COLUMNS,
    audit_uw_session_asset_incidents,
    canonical_sha256,
)

SCHEMA_VERSION: Final[str] = "uw-anomaly-evidence-v2.1"
AVAILABILITY_INDICATOR_COLUMNS: Final[frozenset[str]] = frozenset(
    {"source_available", "provider_available", "availability_status", "source_status"}
)
SESSION_WIDE_MEDIAN_DELAY_SECONDS: Final[float] = 3_600.0
SESSION_WIDE_CREATED_NEAR_CLOSE_SECONDS: Final[float] = 900.0


def build_uw_anomaly_evidence_v21(
    *,
    event_root: Path,
    matrix_root: Path,
    session_dates: Sequence[str],
    raw_assets: Sequence[str] | None = None,
    batch_size: int = 131_072,
) -> dict[str, Any]:
    """Build a deterministic, target-free Full Tape/B2 coding sidecar.

    Parameters
    ----------
    event_root:
        Root of existing partitions in the shape
        ``date=YYYY-MM-DD/asset=SYMBOL/events.parquet``.
    matrix_root:
        Root of canonical B2 variant directories containing
        ``date=YYYY-MM-DD.parquet`` files.
    session_dates:
        Existing ISO trading dates to audit. No dates are inferred from a target.
    raw_assets:
        Optional Full Tape assets. When omitted, existing partition names for the
        requested sessions determine the audited universe.
    batch_size:
        Bounded timestamp batch size for Full Tape reads.

    Returns
    -------
    dict[str, Any]
        A sanitised document with incident evidence, canonical-row coding counts,
        an availability gate, and a self-hash. It contains no source paths, trade
        identifiers, market values, targets, or model data.

    Raises
    ------
    FileNotFoundError
        If either required root is unavailable.
    ValueError
        If scope, schema, or date constraints are invalid.

    Notes
    -----
    ``created_at`` is retained only as an operational timing proxy. A delayed
    Full Tape field is an observed temporal condition, not evidence of a
    provider-internal cause or a proof that market activity was zero.
    """
    dates = _normalise_dates(session_dates)
    if not event_root.is_dir():
        raise FileNotFoundError("UW_ANOMALY_V21_EVENT_ROOT_MISSING")
    if not matrix_root.is_dir():
        raise FileNotFoundError("UW_ANOMALY_V21_MATRIX_ROOT_MISSING")
    if batch_size <= 0:
        raise ValueError("UW_ANOMALY_V21_BATCH_SIZE_MUST_BE_POSITIVE")
    assets = _normalise_assets(raw_assets, event_root=event_root, session_dates=dates)
    raw_rows = audit_uw_session_asset_incidents(
        event_root=event_root,
        session_dates=dates,
        assets=assets,
        batch_size=batch_size,
    )
    incidents = [
        _sanitise_incident(
            raw,
            metadata_fingerprint=_source_metadata_fingerprint(
                event_root=event_root,
                session_date=str(raw["session_date"]),
                asset=str(raw["asset"]),
            ),
        )
        for raw in raw_rows
    ]
    incidents.sort(key=lambda row: (str(row["session_date"]), str(row["asset"])))
    incident_by_key = {(str(row["session_date"]), str(row["asset"])): row for row in incidents}
    variants = tuple(sorted(path.name for path in matrix_root.iterdir() if path.is_dir()))
    if not variants:
        raise ValueError("UW_ANOMALY_V21_CANONICAL_VARIANTS_MISSING")
    canonical_rows: list[dict[str, Any]] = []
    for variant in variants:
        for session_date in dates:
            canonical_rows.extend(
                _audit_variant_session(
                    matrix_root=matrix_root,
                    variant=variant,
                    session_date=session_date,
                    assets=assets,
                    incidents=incident_by_key,
                )
            )
    canonical_rows.sort(
        key=lambda row: (
            str(row["canonical_variant"]),
            str(row["session_date"]),
            str(row["asset"]),
        )
    )
    reasons = _availability_gate_reasons(canonical_rows)
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "scope": "offline_existing_full_tape_timestamps_and_canonical_b2_only",
        "no_provider_http_requests_performed": True,
        "no_targets_or_predictive_metrics_read": True,
        "no_model_or_oos_artifacts_read": True,
        "session_dates": list(dates),
        "raw_assets": list(assets),
        "canonical_variants": list(variants),
        "source_incidents": incidents,
        "canonical_rows": canonical_rows,
        "activity_availability_gate": "FAIL" if reasons else "PASS",
        "activity_availability_gate_reasons": reasons,
    }
    document["artifact_sha256"] = _artifact_sha256(document)
    validate_uw_anomaly_evidence_v21(document)
    return document


def validate_uw_anomaly_evidence_v21(
    evidence: Mapping[str, Any], *, schema_path: Path | None = None
) -> None:
    """Validate an anomaly-evidence document and its self-hash.

    Parameters
    ----------
    evidence:
        Sanitised document returned by :func:`build_uw_anomaly_evidence_v21`.
    schema_path:
        Optional JSON Schema override for isolated tests. The repository schema
        is used by default.

    Raises
    ------
    ValueError
        If the schema, self-hash, or sanitisation boundary is violated.
    """
    actual = dict(evidence)
    expected_hash = _artifact_sha256(actual)
    if actual.get("artifact_sha256") != expected_hash:
        raise ValueError("UW_ANOMALY_V21_ARTIFACT_HASH_MISMATCH")
    serialized = _canonical_json(actual)
    if _contains_forbidden_output(serialized):
        raise ValueError("UW_ANOMALY_V21_FORBIDDEN_OUTPUT_CONTENT")
    path = schema_path if schema_path is not None else _default_schema_path()
    schema = json.loads(path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(actual), key=lambda error: list(error.absolute_path))
    if errors:
        raise ValueError(f"UW_ANOMALY_V21_SCHEMA_INVALID:{errors[0].message}")
    _validate_internal_row_hashes(actual)


def write_uw_anomaly_evidence_v21(*, output_path: Path, evidence: Mapping[str, Any]) -> str:
    """Validate and write deterministic sanitised anomaly evidence.

    Parameters
    ----------
    output_path:
        Destination JSON path. The caller controls the directory; no implicit
        path under a provider cache is created.
    evidence:
        Document produced by :func:`build_uw_anomaly_evidence_v21`.

    Returns
    -------
    str
        The validated SHA-256 self-hash.

    Raises
    ------
    ValueError
        If validation fails before any file is written.
    """
    validate_uw_anomaly_evidence_v21(evidence)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_canonical_json(evidence) + "\n", encoding="utf-8")
    return str(evidence["artifact_sha256"])


def _audit_variant_session(
    *,
    matrix_root: Path,
    variant: str,
    session_date: str,
    assets: Sequence[str],
    incidents: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Classify B2 coding for one variant/session without serialising origin IDs."""
    path = matrix_root / variant / f"date={session_date}.parquet"
    if not path.is_file():
        return [
            _absent_matrix_row(
                variant=variant,
                session_date=session_date,
                asset=asset,
                incident=incidents[(session_date, asset)],
                status="MISSING",
            )
            for asset in assets
        ]
    reader = pq.ParquetFile(path)
    required = {"asset", "session_date", "origin_id", *B2_FEATURE_COLUMNS}
    if not required.issubset(reader.schema_arrow.names):
        return [
            _absent_matrix_row(
                variant=variant,
                session_date=session_date,
                asset=asset,
                incident=incidents[(session_date, asset)],
                status="MISSING",
            )
            for asset in assets
        ]
    indicator_status = (
        "INDICATOR_PRESENT"
        if AVAILABILITY_INDICATOR_COLUMNS.intersection(reader.schema_arrow.names)
        else "INDICATOR_ABSENT"
    )
    rows_by_asset: dict[str, list[dict[str, Any]]] = {}
    table = pq.read_table(path, columns=["asset", "session_date", *B2_FEATURE_COLUMNS])
    for row in table.to_pylist():
        row_date = str(row["session_date"])
        if row_date != session_date:
            continue
        rows_by_asset.setdefault(str(row["asset"]), []).append(row)
    file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    output: list[dict[str, Any]] = []
    for asset in assets:
        incident = incidents[(session_date, asset)]
        rows = rows_by_asset.get(asset, [])
        if not rows:
            output.append(
                _absent_matrix_row(
                    variant=variant,
                    session_date=session_date,
                    asset=asset,
                    incident=incident,
                    status="EXCLUDED",
                    canonical_file_sha256=file_sha256,
                    indicator_status=indicator_status,
                )
            )
            continue
        coding = _coding_counts(rows)
        output.append(
            _present_matrix_row(
                variant=variant,
                session_date=session_date,
                asset=asset,
                incident=incident,
                canonical_file_sha256=file_sha256,
                indicator_status=indicator_status,
                coding=coding,
            )
        )
    return output


def _sanitise_incident(
    raw: Mapping[str, Any], *, metadata_fingerprint: str | None
) -> dict[str, Any]:
    """Remove path-free raw audit noise and derive a conservative temporal state."""
    source_status = _source_status(raw)
    temporal_state = _source_temporal_state(raw, source_status=source_status)
    row: dict[str, Any] = {
        "session_date": str(raw["session_date"]),
        "asset": str(raw["asset"]),
        "source_partition_ref": (f"date={raw['session_date']}/asset={raw['asset']}/events.parquet"),
        "source_status": source_status,
        "source_temporal_state": temporal_state,
        "provider_cause_status": "UNRESOLVED_OBSERVED_TIMING_ONLY",
        "source_row_count": int(raw["source_row_count"]),
        "timestamp_schema": raw["timestamp_schema"],
        "timestamp_unit": raw["timestamp_unit"],
        "valid_timestamp_pair_count": int(raw["valid_timestamp_pair_count"]),
        "negative_lag_count": int(raw["negative_lag_count"]),
        "lag_seconds_min": raw["lag_seconds_min"],
        "lag_seconds_p50": raw["lag_seconds_p50"],
        "lag_seconds_p95": raw["lag_seconds_p95"],
        "lag_seconds_p99": raw["lag_seconds_p99"],
        "lag_seconds_max": raw["lag_seconds_max"],
        "lag_over_300_seconds_count": int(raw["lag_over_300_seconds_count"]),
        "min_created_at_utc": raw["min_created_at_utc"],
        "regular_session_close_utc": raw["regular_session_close_utc"],
        "source_metadata_sha256": metadata_fingerprint,
    }
    row["source_incident_sha256"] = canonical_sha256(row)
    return row


def _source_metadata_fingerprint(*, event_root: Path, session_date: str, asset: str) -> str | None:
    """Hash only Parquet structural metadata, not trade contents or file paths."""
    path = event_root / f"date={session_date}" / f"asset={asset}" / "events.parquet"
    if not path.is_file():
        return None
    reader = pq.ParquetFile(path)
    metadata = reader.metadata
    binding = {
        "file_size_bytes": path.stat().st_size,
        "row_count": int(metadata.num_rows) if metadata is not None else 0,
        "row_group_count": int(metadata.num_row_groups) if metadata is not None else 0,
        "timestamp_schema": {
            name: str(reader.schema_arrow.field(name).type)
            for name in ("executed_at", "created_at")
            if name in reader.schema_arrow.names
        },
    }
    return canonical_sha256(binding)


def _source_status(raw: Mapping[str, Any]) -> str:
    """Map existing target-free incident states to the forensic source enum."""
    raw_status = str(raw["raw_source_status"])
    if raw_status == "PRESENT_NONEMPTY":
        return "SOURCE_AVAILABLE"
    if raw_status == "MISSING":
        return "SOURCE_UNAVAILABLE"
    if raw_status == "SOURCE_EMPTY":
        return "SOURCE_EMPTY"
    return "SOURCE_INVALID"


def _source_temporal_state(raw: Mapping[str, Any], *, source_status: str) -> str:
    """Describe observed timing without asserting an undocumented provider cause."""
    if source_status != "SOURCE_AVAILABLE":
        return source_status
    p50 = raw["lag_seconds_p50"]
    min_created = raw["min_created_at_utc"]
    close = raw["regular_session_close_utc"]
    seconds_to_close = _seconds_between(min_created, close)
    if (
        isinstance(p50, (int, float))
        and float(p50) >= SESSION_WIDE_MEDIAN_DELAY_SECONDS
        and seconds_to_close is not None
        and 0.0 <= seconds_to_close <= SESSION_WIDE_CREATED_NEAR_CLOSE_SECONDS
    ):
        return "SESSION_WIDE_CREATED_AT_DELAY_OBSERVED"
    if int(raw["lag_over_300_seconds_count"]) > 0:
        return "LONG_CREATED_AT_DELAY_TAIL_OBSERVED"
    return "SOURCE_AVAILABLE_NO_DELAY_TAIL_OBSERVED"


def _present_matrix_row(
    *,
    variant: str,
    session_date: str,
    asset: str,
    incident: Mapping[str, Any],
    canonical_file_sha256: str,
    indicator_status: str,
    coding: Mapping[str, int],
) -> dict[str, Any]:
    """Render an aggregated present matrix row without exposing origin identifiers."""
    zero_count = int(coding["ZERO"])
    missing_count = int(coding["MISSING"])
    nonzero_count = int(coding["NONZERO"])
    value_coding = _aggregate_value_coding(
        zero_count=zero_count,
        missing_count=missing_count,
        nonzero_count=nonzero_count,
    )
    row: dict[str, Any] = {
        "canonical_variant": variant,
        "session_date": session_date,
        "asset": asset,
        "canonical_matrix_ref": f"{variant}/date={session_date}.parquet",
        "row_presence_status": "PRESENT",
        "canonical_value_coding": value_coding,
        "availability_indicator_status": indicator_status,
        "canonical_file_sha256": canonical_file_sha256,
        "observed_origin_count": zero_count + missing_count + nonzero_count,
        "canonical_row_coding_counts": {
            "ZERO": zero_count,
            "MISSING": missing_count,
            "EXCLUDED": 0,
            "NONZERO": nonzero_count,
        },
        "source_status": str(incident["source_status"]),
        "source_temporal_state": str(incident["source_temporal_state"]),
    }
    row["zero_interpretation"] = _zero_interpretation(row)
    row["zero_can_mean_no_activity"] = False
    row["canonical_row_sha256"] = canonical_sha256(row)
    return row


def _absent_matrix_row(
    *,
    variant: str,
    session_date: str,
    asset: str,
    incident: Mapping[str, Any],
    status: str,
    canonical_file_sha256: str | None = None,
    indicator_status: str = "INDICATOR_ABSENT",
) -> dict[str, Any]:
    """Render an explicit missing or excluded canonical state, never a zero."""
    row: dict[str, Any] = {
        "canonical_variant": variant,
        "session_date": session_date,
        "asset": asset,
        "canonical_matrix_ref": f"{variant}/date={session_date}.parquet",
        "row_presence_status": status,
        "canonical_value_coding": status,
        "availability_indicator_status": indicator_status,
        "canonical_file_sha256": canonical_file_sha256,
        "observed_origin_count": 0,
        "canonical_row_coding_counts": {
            "ZERO": 0,
            "MISSING": 0,
            "EXCLUDED": 1 if status == "EXCLUDED" else 0,
            "NONZERO": 0,
        },
        "source_status": str(incident["source_status"]),
        "source_temporal_state": str(incident["source_temporal_state"]),
        "zero_interpretation": "NOT_APPLICABLE",
        "zero_can_mean_no_activity": False,
    }
    row["canonical_row_sha256"] = canonical_sha256(row)
    return row


def _coding_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Classify every canonical origin by values, without retaining origin IDs."""
    output = {"ZERO": 0, "MISSING": 0, "NONZERO": 0}
    for row in rows:
        values = [row[column] for column in B2_FEATURE_COLUMNS]
        if any(value is None for value in values):
            output["MISSING"] += 1
        elif all(float(value) == 0.0 for value in values):
            output["ZERO"] += 1
        else:
            output["NONZERO"] += 1
    return output


def _aggregate_value_coding(*, zero_count: int, missing_count: int, nonzero_count: int) -> str:
    """Return one aggregate code while preserving the exact per-row counts."""
    active = sum(count > 0 for count in (zero_count, missing_count, nonzero_count))
    if active != 1:
        return "MIXED"
    if zero_count:
        return "ZERO"
    if missing_count:
        return "MISSING"
    return "NONZERO"


def _zero_interpretation(row: Mapping[str, Any]) -> str:
    """Apply the fail-closed interpretation boundary for numeric canonical zeros."""
    if str(row["row_presence_status"]) != "PRESENT":
        return "NOT_APPLICABLE"
    zero_count = int(dict(row["canonical_row_coding_counts"])["ZERO"])
    if zero_count == 0:
        return "NOT_APPLICABLE"
    if str(row["source_status"]) != "SOURCE_AVAILABLE":
        return "SOURCE_UNAVAILABLE"
    if str(row["source_temporal_state"]) == "SESSION_WIDE_CREATED_AT_DELAY_OBSERVED":
        return "CONFOUNDED_BY_DELAY"
    return "ZERO_NOT_PROVIDER_ACTIVITY_CONFIRMATION"


def _availability_gate_reasons(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return deterministic fail-closed reasons for possible zero confounding."""
    reasons: set[str] = set()
    for row in rows:
        presence = str(row["row_presence_status"])
        coding = str(row["canonical_value_coding"])
        interpretation = str(row["zero_interpretation"])
        if presence == "MISSING" or coding == "MISSING":
            reasons.add("CANONICAL_B2_MISSING")
        if presence == "PRESENT" and str(row["source_status"]) != "SOURCE_AVAILABLE":
            reasons.add("SOURCE_UNAVAILABLE_OR_INVALID")
        if interpretation == "CONFOUNDED_BY_DELAY":
            reasons.add("ZERO_CONFOUNDED_BY_OBSERVED_CREATED_AT_DELAY")
        if interpretation == "SOURCE_UNAVAILABLE":
            reasons.add("SOURCE_UNAVAILABLE_ZERO_REJECTED")
    return sorted(reasons)


def _normalise_dates(values: Sequence[str]) -> tuple[str, ...]:
    """Validate and sort an explicit source-only ISO date scope."""
    output = tuple(sorted(set(str(value) for value in values)))
    if not output or any(len(value) != 10 for value in output):
        raise ValueError("UW_ANOMALY_V21_SESSION_DATES_REQUIRED")
    return output


def _normalise_assets(
    values: Sequence[str] | None, *, event_root: Path, session_dates: Sequence[str]
) -> tuple[str, ...]:
    """Use explicit assets or only existing requested Full Tape partition names."""
    if values is not None:
        output = tuple(sorted(set(str(value) for value in values)))
    else:
        found: set[str] = set()
        for session_date in session_dates:
            found.update(
                path.name.removeprefix("asset=")
                for path in (event_root / f"date={session_date}").glob("asset=*")
                if path.is_dir()
            )
        output = tuple(sorted(found))
    if not output:
        raise ValueError("UW_ANOMALY_V21_RAW_ASSETS_REQUIRED")
    return output


def _seconds_between(start: Any, end: Any) -> float | None:
    """Return ``end - start`` seconds for compact UTC strings when both exist."""
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    from datetime import datetime

    left = datetime.fromisoformat(start.replace("Z", "+00:00"))
    right = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return (right - left).total_seconds()


def _artifact_sha256(value: Mapping[str, Any]) -> str:
    """Hash an evidence document excluding its self-referential digest field."""
    return canonical_sha256({key: item for key, item in value.items() if key != "artifact_sha256"})


def _validate_internal_row_hashes(evidence: Mapping[str, Any]) -> None:
    """Fail closed when a source or canonical-row traceability hash is altered."""
    for incident in evidence["source_incidents"]:
        row = dict(incident)
        observed = str(row.pop("source_incident_sha256"))
        if observed != canonical_sha256(row):
            raise ValueError("UW_ANOMALY_V21_SOURCE_INCIDENT_HASH_MISMATCH")
    for canonical_row in evidence["canonical_rows"]:
        row = dict(canonical_row)
        observed = str(row.pop("canonical_row_sha256"))
        if observed != canonical_sha256(row):
            raise ValueError("UW_ANOMALY_V21_CANONICAL_ROW_HASH_MISMATCH")


def _default_schema_path() -> Path:
    """Return the repository-owned JSON Schema without using a caller path."""
    return Path(__file__).resolve().parents[2] / "schemas" / "uw_anomaly_evidence_v21.schema.json"


def _canonical_json(value: Mapping[str, Any]) -> str:
    """Serialise deterministic UTF-8-safe compact JSON."""
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True, allow_nan=False)


def _contains_forbidden_output(serialized: str) -> bool:
    """Block absolute Windows paths, home directories, and accidental secret labels."""
    lowered = serialized.lower()
    markers = ("d:\\\\", "c:\\\\users\\\\", "api_key", "authorization", "bearer ")
    return any(marker in lowered for marker in markers)
