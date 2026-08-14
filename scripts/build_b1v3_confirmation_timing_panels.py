"""Build and seal the five source-bound target-blind B1v3 timing panels."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mds650.b1v3_confirmation import (  # noqa: E402
    canonical_sha256,
    sha256_file,
    validate_confirmation_plan_schema,
)
from mds650.b1v3_timing_panel import (  # noqa: E402
    REGISTERED_TIMING_VARIANTS,
    build_registered_timing_panels,
)

_FORBIDDEN = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)
_ORIGIN_COLUMNS = (
    "origin_id",
    "asset",
    "session_date",
    "forecast_origin_utc",
    "forecast_origin_ny",
    "forecast_origin_ns",
    "role",
    "session_minute",
    "session_tercile",
    "session_segment",
)


def _read_manifest(path: Path, schema: Path, *, code: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(document, dict):
        raise ValueError(code)
    validate_confirmation_plan_schema(document, schema)
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(stored, str) or stored != canonical_sha256(unsigned):
        raise ValueError(f"{code}_HASH")
    return document


def _write_parquet_if_identical(frame: pl.DataFrame, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".b1v3-timing-panel-", dir=destination.parent) as name:
        candidate = Path(name) / destination.name
        frame.write_parquet(candidate, compression="zstd", statistics=True)
        candidate_hash = sha256_file(candidate)
        if destination.exists():
            if sha256_file(destination) != candidate_hash:
                raise ValueError(f"B1V3_TIMING_PANEL_OUTPUT_CONFLICT:{destination.name}")
            return candidate_hash
        os.replace(candidate, destination)
    return candidate_hash


def _write_json_if_identical(path: Path, document: Mapping[str, Any]) -> str:
    payload = (
        json.dumps(document, ensure_ascii=True, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if any(token in payload.lower() for token in _FORBIDDEN):
        raise ValueError("B1V3_TIMING_PANEL_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"B1V3_TIMING_PANEL_OUTPUT_CONFLICT:{path.name}")
        return sha256_file(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256_file(path)


def _nested(mapping: object, *keys: str) -> object:
    value = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _validate_file_binding(
    document: Mapping[str, Any],
    keys: tuple[str, ...],
    path: Path,
    *,
    code: str,
) -> None:
    record = _nested(document, *keys)
    if not isinstance(record, dict) or record.get("sha256") != sha256_file(path):
        raise ValueError(code)


def build_timing_panel_package(
    *,
    common_panel_path: Path,
    common_manifest_path: Path,
    common_manifest_schema_path: Path,
    timing_predictor_manifest_path: Path,
    timing_predictor_manifest_schema_path: Path,
    b2_manifest_path: Path,
    b2_manifest_schema_path: Path,
    fmp_b0_path: Path,
    fmp_b1_path: Path,
    massive_60_b1_path: Path,
    massive_300_b1_path: Path,
    uw_120_b2_path: Path,
    uw_300_b2_path: Path,
    output_root: Path,
    manifest_path: Path,
    manifest_schema_path: Path,
) -> dict[str, Any]:
    """Assemble and seal five registered target-blind common timing panels."""
    common_manifest = _read_manifest(
        common_manifest_path,
        common_manifest_schema_path,
        code="B1V3_TIMING_COMMON_MANIFEST_INVALID",
    )
    timing_manifest = _read_manifest(
        timing_predictor_manifest_path,
        timing_predictor_manifest_schema_path,
        code="B1V3_TIMING_PREDICTOR_MANIFEST_INVALID",
    )
    b2_manifest = _read_manifest(
        b2_manifest_path,
        b2_manifest_schema_path,
        code="B1V3_TIMING_B2_MANIFEST_INVALID",
    )
    if (
        common_manifest.get("status") != "PASS_TARGET_BLIND_COMMON_PREDICTOR_PANEL"
        or timing_manifest.get("status") != "PASS_TARGET_BLIND_TIMING_PREDICTORS"
        or b2_manifest.get("status") != "PASS_TARGET_BLIND_B2_PREDICTORS"
        or any(
            document.get("target_blind") is not True
            or document.get("outcome_read_count") != 0
            or document.get("safe_to_read_outcomes") is not False
            for document in (common_manifest, timing_manifest, b2_manifest)
        )
    ):
        raise ValueError("B1V3_TIMING_PANEL_SOURCE_GATE_INVALID")
    _validate_file_binding(
        common_manifest,
        ("output",),
        common_panel_path,
        code="B1V3_TIMING_COMMON_PANEL_HASH_INVALID",
    )
    _validate_file_binding(
        timing_manifest,
        ("variants", "FMP_DELAY_2_MINUTES", "b0"),
        fmp_b0_path,
        code="B1V3_TIMING_FMP_B0_HASH_INVALID",
    )
    for variant, path in (
        ("FMP_DELAY_2_MINUTES", fmp_b1_path),
        ("MASSIVE_CUTOFF_60_SECONDS", massive_60_b1_path),
        ("MASSIVE_CUTOFF_300_SECONDS", massive_300_b1_path),
    ):
        _validate_file_binding(
            timing_manifest,
            ("variants", variant, "technical_build", "features"),
            path,
            code=f"B1V3_TIMING_{variant}_HASH_INVALID",
        )
    for variant, path in (
        ("latency_5m_120s", uw_120_b2_path),
        ("latency_5m_300s", uw_300_b2_path),
    ):
        _validate_file_binding(
            b2_manifest,
            ("variants", variant),
            path,
            code=f"B1V3_TIMING_{variant}_HASH_INVALID",
        )

    primary = pl.read_parquet(common_panel_path)
    missing_origin = set(_ORIGIN_COLUMNS) - set(primary.columns)
    if missing_origin:
        raise ValueError("B1V3_TIMING_PRIMARY_PANEL_SCHEMA_INVALID")
    origins = primary.select(*_ORIGIN_COLUMNS)
    panels = build_registered_timing_panels(
        origins=origins,
        primary_b0=primary,
        primary_b1=primary,
        primary_b2=primary,
        overrides={
            "FMP_DELAY_2_MINUTES": (
                pl.read_parquet(fmp_b0_path),
                pl.read_parquet(fmp_b1_path),
                None,
            ),
            "MASSIVE_CUTOFF_60_SECONDS": (
                None,
                pl.read_parquet(massive_60_b1_path),
                None,
            ),
            "MASSIVE_CUTOFF_300_SECONDS": (
                None,
                pl.read_parquet(massive_300_b1_path),
                None,
            ),
            "UW_CREATED_AT_120_SECONDS": (
                None,
                None,
                pl.read_parquet(uw_120_b2_path),
            ),
            "UW_CREATED_AT_300_SECONDS": (
                None,
                None,
                pl.read_parquet(uw_300_b2_path),
            ),
        },
    )
    variant_records: dict[str, Any] = {}
    for variant in REGISTERED_TIMING_VARIANTS:
        panel = panels[variant]
        destination = output_root / f"{variant}.parquet"
        file_hash = _write_parquet_if_identical(panel, destination)
        variant_records[variant] = {
            "logical_path": (f"MDS650_B1V3_DATA_ROOT/predictors/timing/common/{variant}.parquet"),
            "sha256": file_hash,
            "bytes": destination.stat().st_size,
            "origin_count": panel.height,
            "b0_complete_count": int(panel["b0_information_set_complete"].sum()),
            "b1v3a_complete_count": int(panel["b1v3a_information_set_complete"].sum()),
            "b2_complete_count": int(panel["b2_information_set_complete"].sum()),
        }
    scope = common_manifest.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("B1V3_TIMING_COMMON_SCOPE_INVALID")
    document: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_TARGET_BLIND_TIMING_COMMON_PANELS",
        "target_blind": True,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "source_bindings": {
            "common_manifest_sha256": str(common_manifest["manifest_sha256"]),
            "common_panel_sha256": sha256_file(common_panel_path),
            "timing_predictor_manifest_sha256": str(timing_manifest["manifest_sha256"]),
            "b2_manifest_sha256": str(b2_manifest["manifest_sha256"]),
            "origin_identity_sha256": str(scope["origin_identity_sha256"]),
            "builder_code_sha256": sha256_file(Path(__file__)),
        },
        "variants": variant_records,
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    validate_confirmation_plan_schema(document, manifest_schema_path)
    _write_json_if_identical(manifest_path, document)
    return document


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    contracts = ROOT / "specs" / "001-pit-options-rv30" / "contracts"
    predictors = Path("D:/MDS650/b1v3_confirmation/predictors")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--common-panel", type=Path, default=predictors / "common_predictor_panel.parquet"
    )
    parser.add_argument(
        "--common-manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/common_predictor_manifest.json",
    )
    parser.add_argument(
        "--common-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-common-predictor-v1.schema.json",
    )
    parser.add_argument(
        "--timing-predictor-manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/timing_predictor_manifest.json",
    )
    parser.add_argument(
        "--timing-predictor-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-timing-predictors-v1.schema.json",
    )
    parser.add_argument(
        "--b2-manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/b2_predictor_manifest.json",
    )
    parser.add_argument(
        "--b2-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-b2-predictors-v1.schema.json",
    )
    timing = predictors / "timing"
    parser.add_argument("--fmp-b0", type=Path, default=timing / "fmp_delay_2/b0.parquet")
    parser.add_argument(
        "--fmp-b1",
        type=Path,
        default=timing / "fmp_delay_2/features/b1v3_features.parquet",
    )
    parser.add_argument(
        "--massive-60-b1",
        type=Path,
        default=timing / "massive/cutoff_60/features/b1v3_features.parquet",
    )
    parser.add_argument(
        "--massive-300-b1",
        type=Path,
        default=timing / "massive/cutoff_300/features/b1v3_features.parquet",
    )
    parser.add_argument(
        "--uw-120-b2",
        type=Path,
        default=predictors / "b2_latency_5m_120s_target_blind.parquet",
    )
    parser.add_argument(
        "--uw-300-b2",
        type=Path,
        default=predictors / "b2_latency_5m_300s_target_blind.parquet",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=timing / "common",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts/b1v3_confirmation_panel/timing_panel_manifest.json",
    )
    parser.add_argument(
        "--manifest-schema",
        type=Path,
        default=contracts / "b1v3-confirmation-timing-panels-v1.schema.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the timing panels and print only sanitized identities."""
    args = _arguments(argv)
    document = build_timing_panel_package(
        common_panel_path=args.common_panel,
        common_manifest_path=args.common_manifest,
        common_manifest_schema_path=args.common_schema,
        timing_predictor_manifest_path=args.timing_predictor_manifest,
        timing_predictor_manifest_schema_path=args.timing_predictor_schema,
        b2_manifest_path=args.b2_manifest,
        b2_manifest_schema_path=args.b2_schema,
        fmp_b0_path=args.fmp_b0,
        fmp_b1_path=args.fmp_b1,
        massive_60_b1_path=args.massive_60_b1,
        massive_300_b1_path=args.massive_300_b1,
        uw_120_b2_path=args.uw_120_b2,
        uw_300_b2_path=args.uw_300_b2,
        output_root=args.output_root,
        manifest_path=args.manifest,
        manifest_schema_path=args.manifest_schema,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "manifest_sha256": document["manifest_sha256"],
                "outcome_read_count": document["outcome_read_count"],
                "safe_to_read_outcomes": document["safe_to_read_outcomes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
