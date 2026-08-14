"""Build the source-bound, target-blind B1v3 feature package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

import polars as pl
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from mds650.b1v3 import (
    B1V3_FEATURES,
    B1v3CoverageDecision,
    build_b1v3_features,
    summarize_b1v3_coverage,
)

_FORBIDDEN_PATH_TOKENS = (
    "rv30",
    "qlike",
    "prediction",
    "outcome",
    "result",
    "holdout",
)
_FORBIDDEN_SERIALIZED_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "c:\\users\\",
    "/users/",
)
_GIB = 1024**3


class _JsonSchemaValidator(Protocol):
    """Minimal runtime boundary for the untyped jsonschema package."""

    @classmethod
    def check_schema(cls, schema: Mapping[str, Any]) -> None: ...

    def __init__(self, schema: Mapping[str, Any]) -> None: ...

    def iter_errors(self, instance: object) -> Iterable[object]: ...


@dataclass(frozen=True, slots=True)
class BuildArtifacts:
    """Paths and hashes of one completed target-blind package."""

    features_path: Path
    coverage_path: Path
    manifest_path: Path
    features_sha256: str
    coverage_sha256: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class _SourceBinding:
    manifest_semantic_sha256: str
    manifest_file_sha256: str
    inventory_sha256: str


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize a mapping canonically for semantic hashing.

    Parameters
    ----------
    value:
        JSON-compatible mapping.

    Returns
    -------
    bytes
        UTF-8 compact JSON with sorted keys and no trailing newline.
    """
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Mapping[str, Any]) -> str:
    """Return the lower-case SHA-256 of canonical JSON."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it into memory.

    Parameters
    ----------
    path:
        Existing regular file.
    chunk_size:
        Positive read size.

    Returns
    -------
    str
        Lower-case SHA-256 hexadecimal digest.

    Raises
    ------
    ValueError
        If ``chunk_size`` is not positive.
    """
    if chunk_size <= 0:
        raise ValueError("B1V3_HASH_CHUNK_SIZE_INVALID")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _pretty_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _validate_json_schema(document: Mapping[str, Any], schema_path: Path) -> None:
    if not schema_path.is_file():
        raise ValueError("B1V3_MANIFEST_SCHEMA_MISSING")
    schema_value = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(schema_value, dict):
        raise ValueError("B1V3_MANIFEST_SCHEMA_INVALID")
    module = import_module("jsonschema")
    raw_validator = getattr(module, "Draft202012Validator", None)
    if raw_validator is None or not callable(raw_validator):
        raise ValueError("B1V3_JSONSCHEMA_RUNTIME_INVALID")
    validator_type = cast(type[_JsonSchemaValidator], raw_validator)
    validator_type.check_schema(schema_value)
    if any(validator_type(schema_value).iter_errors(document)):
        raise ValueError("B1V3_MANIFEST_SCHEMA_VALIDATION_FAILED")


def _load_source_binding(
    *,
    input_sha256: str,
    manifest_path: Path | None,
    schema_path: Path | None,
    inventory_path: Path | None,
) -> _SourceBinding | None:
    supplied = (manifest_path, schema_path, inventory_path)
    if all(value is None for value in supplied):
        return None
    if any(value is None for value in supplied):
        raise ValueError("B1V3_SOURCE_BINDING_ARGUMENTS_INCOMPLETE")
    assert manifest_path is not None
    assert schema_path is not None
    assert inventory_path is not None
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("B1V3_SOURCE_BINDING_MANIFEST_INVALID") from exc
    if not isinstance(document, dict):
        raise ValueError("B1V3_SOURCE_BINDING_MANIFEST_INVALID")
    _validate_json_schema(document, schema_path)
    stored_hash = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    attempts = document.get("attempts")
    raw_binding = document.get("raw_payload_binding")
    pit = document.get("pit_invariants")
    security = document.get("security")
    if (
        not isinstance(stored_hash, str)
        or stored_hash != canonical_sha256(unsigned)
        or document.get("status") != "PASS_TARGET_BLIND_B1Q_SOURCE_BOUND"
        or document.get("target_blind") is not True
        or document.get("outcome_read_count") != 0
        or document.get("safe_to_read_outcomes") is not False
        or not isinstance(attempts, dict)
        or attempts.get("sha256") != input_sha256
        or not isinstance(raw_binding, dict)
        or raw_binding.get("status") != "PRESENT_AND_VALIDATED"
        or not isinstance(pit, dict)
        or pit.get("future_selected_quote_rows") != 0
        or not isinstance(security, dict)
        or security.get("secret_values_emitted") is not False
        or security.get("personal_paths_emitted") is not False
    ):
        raise ValueError("B1V3_SOURCE_BINDING_GATE_INVALID")
    if (
        not inventory_path.is_file()
        or raw_binding.get("inventory_sha256") != sha256_file(inventory_path)
    ):
        raise ValueError("B1V3_SOURCE_BINDING_INVENTORY_HASH_INVALID")
    return _SourceBinding(
        manifest_semantic_sha256=stored_hash,
        manifest_file_sha256=sha256_file(manifest_path),
        inventory_sha256=sha256_file(inventory_path),
    )


def _validate_target_blind_input_path(path: Path) -> None:
    name = path.name.lower()
    if any(token in name for token in _FORBIDDEN_PATH_TOKENS):
        raise ValueError("B1V3_FORBIDDEN_INPUT_PATH")
    if not path.is_file() or path.suffix.lower() != ".parquet":
        raise ValueError("B1V3_INPUT_NOT_PARQUET")


def _validate_serialized_hygiene(payload: bytes) -> None:
    rendered = payload.decode("utf-8").lower()
    if any(token in rendered for token in _FORBIDDEN_SERIALIZED_TOKENS):
        raise ValueError("B1V3_SERIALIZED_HYGIENE_FAILURE")


def _validate_disk_gate(input_path: Path, *, minimum_free_gib: float) -> int:
    if minimum_free_gib < 0:
        raise ValueError("B1V3_DISK_GATE_INVALID")
    free_bytes = shutil.disk_usage(input_path.resolve().anchor).free
    if free_bytes < minimum_free_gib * _GIB:
        raise ValueError("B1V3_DISK_GATE_FAILED")
    return free_bytes


def _iter_contiguous_asset_days(
    input_path: Path,
    *,
    batch_size: int,
) -> Iterable[tuple[tuple[str, str], pl.DataFrame]]:
    if batch_size <= 0:
        raise ValueError("B1V3_BATCH_SIZE_INVALID")
    reader = pq.ParquetFile(input_path)
    completed: set[tuple[str, str]] = set()
    active_key: tuple[str, str] | None = None
    active_rows: list[dict[str, Any]] = []
    for batch in reader.iter_batches(batch_size=batch_size):
        for row in batch.to_pylist():
            key = (str(row.get("asset", "")), str(row.get("session_date", "")))
            if not all(key):
                raise ValueError("B1V3_SOURCE_ASSET_DAY_INVALID")
            if active_key is None:
                active_key = key
            if key != active_key:
                completed.add(active_key)
                yield active_key, pl.DataFrame(active_rows, infer_schema_length=None, strict=False)
                if key in completed:
                    raise ValueError("B1V3_SOURCE_ORDER_NOT_CONTIGUOUS")
                active_key = key
                active_rows = []
            active_rows.append(row)
    if active_key is not None:
        if active_key in completed:
            raise ValueError("B1V3_SOURCE_ORDER_NOT_CONTIGUOUS")
        yield active_key, pl.DataFrame(active_rows, infer_schema_length=None, strict=False)


def _build_streaming_features(
    input_path: Path,
    *,
    quote_cutoff_seconds: int,
    batch_size: int,
) -> tuple[pl.DataFrame, int]:
    feature_parts: list[pl.DataFrame] = []
    input_rows = 0
    for _key, attempts in _iter_contiguous_asset_days(input_path, batch_size=batch_size):
        input_rows += attempts.height
        feature_parts.append(
            build_b1v3_features(attempts, quote_cutoff_seconds=quote_cutoff_seconds)
        )
    if not feature_parts:
        raise ValueError("B1V3_EMPTY_INPUT")
    frame = pl.concat(feature_parts, how="vertical_relaxed").sort(
        ["asset", "session_date", "forecast_origin_ns", "origin_id"]
    )
    if frame["origin_id"].n_unique() != frame.height:
        raise ValueError("B1V3_DUPLICATE_ORIGIN")
    return frame, input_rows


def _metric_dict(decision: B1v3CoverageDecision) -> dict[str, Any]:
    return {
        "status": decision.status,
        "b1v3a": asdict(decision.b1v3a),
        "b1v3b": asdict(decision.b1v3b),
        "b1v3c": asdict(decision.b1v3c),
    }


def _coverage_rows(frame: pl.DataFrame, dimension: str) -> list[dict[str, Any]]:
    rows = (
        frame.group_by(dimension)
        .agg(
            pl.len().alias("origin_count"),
            pl.col("b1v3a_complete").mean().alias("b1v3a_coverage"),
            pl.col("b1v3b_complete").mean().alias("b1v3b_coverage"),
            pl.col("b1v3c_complete").mean().alias("b1v3c_coverage"),
        )
        .sort(dimension)
        .to_dicts()
    )
    return [dict(row) for row in rows]


def _coverage_document(
    *,
    run_id: str,
    frame: pl.DataFrame,
    decision: B1v3CoverageDecision,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "technical_status": decision.status,
        "scientific_result_status": "NOT_EVALUATED_TARGET_BLIND",
        "row_count": frame.height,
        "nested_invariants": {
            "row_level": True,
            "global": True,
            "by_asset": True,
            "by_date": True,
            "by_session_tercile": True,
            "by_quote_cutoff": True,
        },
        "summary": _metric_dict(decision),
        "by_asset": _coverage_rows(frame, "asset"),
        "by_date": _coverage_rows(frame, "session_date"),
        "by_session_tercile": _coverage_rows(frame, "session_tercile"),
    }
    document["coverage_sha256"] = canonical_sha256(document)
    return document


def _origin_identity_sha256(frame: pl.DataFrame) -> str:
    digest = hashlib.sha256()
    for origin_id in frame["origin_id"].to_list():
        digest.update(str(origin_id).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _assert_output_contract(frame: pl.DataFrame, *, quote_cutoff_seconds: int) -> None:
    if frame.is_empty() or frame["origin_id"].n_unique() != frame.height:
        raise ValueError("B1V3_OUTPUT_IDENTITY_INVALID")
    if not set(B1V3_FEATURES).issubset(frame.columns):
        raise ValueError("B1V3_OUTPUT_FEATURES_MISSING")
    lowered = {column.lower() for column in frame.columns}
    for token in _FORBIDDEN_PATH_TOKENS:
        if any(token in column for column in lowered):
            raise ValueError("B1V3_OUTPUT_NOT_TARGET_BLIND")
    cutoff = pl.col("forecast_origin_ns") - quote_cutoff_seconds * 1_000_000_000
    if frame.filter(
        pl.col("max_sip_timestamp_ns").is_not_null() & (pl.col("max_sip_timestamp_ns") > cutoff)
    ).height:
        raise ValueError("B1V3_OUTPUT_FUTURE_QUOTE")
    if frame.filter(pl.col("b1v3c_complete") & ~pl.col("b1v3b_complete")).height:
        raise ValueError("B1V3_OUTPUT_NESTING_INVALID")
    if frame.filter(pl.col("b1v3b_complete") & ~pl.col("b1v3a_complete")).height:
        raise ValueError("B1V3_OUTPUT_NESTING_INVALID")


def _candidate_conflicts(destination: Path, candidate: Path) -> bool:
    return destination.exists() and sha256_file(destination) != sha256_file(candidate)


def _promote_candidates(candidates: Mapping[Path, Path]) -> None:
    for destination, candidate in candidates.items():
        if _candidate_conflicts(destination, candidate):
            raise ValueError(f"B1V3_OUTPUT_CONFLICT:{destination.name}")
    for destination, candidate in candidates.items():
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, destination)


def build_target_blind_package(
    *,
    input_path: Path,
    design_path: Path,
    output_root: Path,
    manifest_schema_path: Path,
    source_binding_manifest_path: Path | None = None,
    source_binding_schema_path: Path | None = None,
    source_inventory_path: Path | None = None,
    quote_cutoff_seconds: int = 0,
    minimum_free_gib: float = 80.0,
    batch_size: int = 65_536,
) -> BuildArtifacts:
    """Build and atomically promote a deterministic target-blind B1v3 package.

    Parameters
    ----------
    input_path:
        Approved target-free IV-attempt Parquet.
    design_path:
        Owner-approved B1v3 design document.
    output_root:
        New package directory; conflicting files are never overwritten.
    manifest_schema_path:
        Draft 2020-12 JSON Schema for the manifest.
    source_binding_manifest_path, source_binding_schema_path,
    source_inventory_path:
        Optional all-or-none B1Q raw-payload binding. When present, the input
        hash, self-hashed source manifest, schema, and immutable inventory must
        agree before the legacy provenance blocker can be removed.
    quote_cutoff_seconds:
        Registered quote cutoff: 0, 60 or 300 seconds. Shifted variants require
        matching reselection identity in the input table.
    minimum_free_gib:
        Required free space on the source volume before any output is created.
    batch_size:
        Maximum Arrow rows decoded per source batch.

    Returns
    -------
    BuildArtifacts
        Final paths and hashes.

    Raises
    ------
    ValueError
        On a target-blind, timing, provenance, schema, disk, ordering or
        idempotence violation.
    """
    _validate_target_blind_input_path(input_path)
    if not design_path.is_file():
        raise ValueError("B1V3_DESIGN_MISSING")
    _validate_disk_gate(input_path, minimum_free_gib=minimum_free_gib)
    source_hash = sha256_file(input_path)
    design_hash = sha256_file(design_path)
    source_binding = _load_source_binding(
        input_sha256=source_hash,
        manifest_path=source_binding_manifest_path,
        schema_path=source_binding_schema_path,
        inventory_path=source_inventory_path,
    )
    if source_binding is None:
        run_id = (
            f"b1v3-target-blind-{source_hash[:12]}-{design_hash[:12]}-"
            f"c{quote_cutoff_seconds}"
        )
    else:
        run_id = (
            f"b1v3-source-bound-{source_hash[:12]}-{design_hash[:12]}-"
            f"{source_binding.manifest_semantic_sha256[:12]}-c{quote_cutoff_seconds}"
        )
    frame, input_rows = _build_streaming_features(
        input_path,
        quote_cutoff_seconds=quote_cutoff_seconds,
        batch_size=batch_size,
    )
    _assert_output_contract(frame, quote_cutoff_seconds=quote_cutoff_seconds)
    decision = summarize_b1v3_coverage(frame)
    coverage = _coverage_document(run_id=run_id, frame=frame, decision=decision)

    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".b1v3-build-", dir=output_root.parent) as temp_name:
        temp_root = Path(temp_name)
        temp_features = temp_root / "b1v3_features.parquet"
        temp_coverage = temp_root / "b1v3_coverage.json"
        temp_manifest = temp_root / "b1v3_manifest.json"
        frame.write_parquet(
            temp_features,
            compression="zstd",
            compression_level=9,
            statistics=True,
        )
        coverage_bytes = _pretty_json_bytes(coverage)
        _validate_serialized_hygiene(coverage_bytes)
        temp_coverage.write_bytes(coverage_bytes)
        features_hash = sha256_file(temp_features)
        coverage_hash = sha256_file(temp_coverage)

        assets = sorted(str(value) for value in frame["asset"].unique().to_list())
        sessions = sorted(str(value) for value in frame["session_date"].unique().to_list())
        asset_day_count = frame.select(pl.struct("asset", "session_date").n_unique()).item()
        provenance: dict[str, Any]
        if source_binding is None:
            provenance = {
                "quote_request_hashes": "PRESENT_AND_VALIDATED",
                "rate_source_dates": "PRE_ORIGIN_VALIDATED",
                "dividend_assumptions": "ALLOWLIST_VALIDATED",
                "exogenous_raw_payload_binding": "UNRESOLVED",
                "evaluation_blocker": "EXOGENOUS_RAW_PAYLOAD_BINDING_NOT_PRESENT",
            }
        else:
            provenance = {
                "quote_request_hashes": "PRESENT_AND_VALIDATED",
                "rate_source_dates": "PRE_ORIGIN_VALIDATED",
                "dividend_assumptions": "ALLOWLIST_VALIDATED",
                "exogenous_raw_payload_binding": "PRESENT_AND_VALIDATED",
                "source_binding_manifest_sha256": (
                    source_binding.manifest_semantic_sha256
                ),
                "source_binding_manifest_file_sha256": (
                    source_binding.manifest_file_sha256
                ),
                "source_inventory_sha256": source_binding.inventory_sha256,
                "evaluation_blocker": None,
            }
        manifest: dict[str, Any] = {
            "schema_version": "2.0" if source_binding is not None else "1.0",
            "run_id": run_id,
            "status": (
                "PASS_TARGET_BLIND_SOURCE_BOUND_TECHNICAL_BUILD"
                if source_binding is not None
                else "PASS_TARGET_BLIND_TECHNICAL_BUILD"
            ),
            "target_blind": True,
            "safe_to_evaluate_scientifically": False,
            "source": {
                "logical_name": "target_free_iv_attempts",
                "filename": input_path.name,
                "sha256": source_hash,
                "bytes": input_path.stat().st_size,
                "row_count": input_rows,
                "origin_count": frame.height,
                "asset_day_count": int(asset_day_count),
                "assets": assets,
                "first_session_date": sessions[0],
                "last_session_date": sessions[-1],
            },
            "design": {
                "logical_name": "approved_b1v3_design",
                "filename": design_path.name,
                "sha256": design_hash,
            },
            "configuration": {
                "quote_cutoff_seconds": quote_cutoff_seconds,
                "maximum_quote_age_seconds": 60,
                "maximum_relative_spread": 0.25,
                "lag_minutes": [5, 30],
                "timezone": "America/New_York",
                "runtime_python": ".".join(map(str, sys.version_info[:3])),
            },
            "feature_contract": {
                "feature_count": len(B1V3_FEATURES),
                "features": list(B1V3_FEATURES),
                "nested_flags": [
                    "b1v3a_complete",
                    "b1v3b_complete",
                    "b1v3c_complete",
                ],
            },
            "provenance": provenance,
            "coverage": {
                "filename": temp_coverage.name,
                "sha256": coverage_hash,
                "technical_status": decision.status,
            },
            "output": {
                "filename": temp_features.name,
                "sha256": features_hash,
                "bytes": temp_features.stat().st_size,
                "row_count": frame.height,
                "origin_count": frame["origin_id"].n_unique(),
                "origin_identity_sha256": _origin_identity_sha256(frame),
                "columns": frame.columns,
            },
        }
        manifest["manifest_sha256"] = canonical_sha256(manifest)
        _validate_json_schema(manifest, manifest_schema_path)
        manifest_bytes = _pretty_json_bytes(manifest)
        _validate_serialized_hygiene(manifest_bytes)
        temp_manifest.write_bytes(manifest_bytes)
        manifest_file_hash = sha256_file(temp_manifest)

        features_path = output_root / temp_features.name
        coverage_path = output_root / temp_coverage.name
        manifest_path = output_root / temp_manifest.name
        _promote_candidates(
            {
                features_path: temp_features,
                coverage_path: temp_coverage,
                manifest_path: temp_manifest,
            }
        )
    return BuildArtifacts(
        features_path=features_path,
        coverage_path=coverage_path,
        manifest_path=manifest_path,
        features_sha256=features_hash,
        coverage_sha256=coverage_hash,
        manifest_sha256=manifest_file_hash,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--design",
        type=Path,
        default=Path("docs/superpowers/specs/2026-08-14-b1v3-target-blind-replication-design.md"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-binding-manifest", type=Path)
    parser.add_argument("--source-binding-schema", type=Path)
    parser.add_argument("--source-inventory", type=Path)
    parser.add_argument(
        "--manifest-schema",
        type=Path,
        default=Path("specs/001-pit-options-rv30/contracts/b1v3-target-blind-manifest.schema.json"),
    )
    parser.add_argument("--quote-cutoff-seconds", type=int, choices=(0, 60, 300), default=0)
    parser.add_argument("--minimum-free-gib", type=float, default=80.0)
    parser.add_argument("--batch-size", type=int, default=65_536)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and print only sanitized package identities."""
    args = _parse_args(argv)
    result = build_target_blind_package(
        input_path=args.input,
        design_path=args.design,
        output_root=args.output_root,
        manifest_schema_path=args.manifest_schema,
        source_binding_manifest_path=args.source_binding_manifest,
        source_binding_schema_path=args.source_binding_schema,
        source_inventory_path=args.source_inventory,
        quote_cutoff_seconds=args.quote_cutoff_seconds,
        minimum_free_gib=args.minimum_free_gib,
        batch_size=args.batch_size,
    )
    print(
        json.dumps(
            {
                "status": "PASS_TARGET_BLIND_TECHNICAL_BUILD",
                "features_sha256": result.features_sha256,
                "coverage_sha256": result.coverage_sha256,
                "manifest_file_sha256": result.manifest_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
