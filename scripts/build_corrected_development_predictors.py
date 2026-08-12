"""Coverage-first construction guard for corrected development predictors.

The first stage intentionally reads only target-free source identities.  It
stops before B0/B1Q/B2 materialization whenever the exact source ledger is
blocked, so no RV30, result, metric, model, or holdout payload is touched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from mds650.corrected_development_sources import (
    build_exact_development_origins,
    build_source_coverage_ledger,
    prepare_b1q_source,
    validate_source_coverage_ledger,
)
from mds650.study_design import build_study_sessions, canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path("D:/MDS650")
DEFAULT_FMP_PATHS = (
    DATA_ROOT / "data/fmp/phase5_missing_55/underlying_1min_20d.parquet",
    DATA_ROOT / "data/fmp/underlying_1min_calibration_20d.parquet",
    DATA_ROOT / "data/fmp/underlying_1min_pilot_5d.parquet",
)
DEFAULT_B1Q_PATH = DATA_ROOT / "data/b1q/phase5_missing_55/b1_origin_matrix_20d.parquet"
DEFAULT_UW_BATCH_MANIFEST = DATA_ROOT / "manifests/full_tape/batch_manifest.json"
DEFAULT_UW_REUSED_MANIFEST = ROOT / "artifacts/phase5/reused_25_session_manifest.json"
DEFAULT_SOURCE_MANIFEST = ROOT / "artifacts/phase5/development_source_manifest_80d.json"
DEFAULT_SCHEMA = (
    ROOT
    / "specs/001-pit-options-rv30/contracts/corrected-development-source-coverage-v1.schema.json"
)
DEFAULT_OUTPUT_PATH = ROOT / "artifacts/corrected_development_v1/source_coverage_ledger.json"
FROZEN_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse target-free local source and coverage-artifact paths.

    Parameters
    ----------
    argv:
        Optional command-line token sequence for testable parsing.

    Returns
    -------
    argparse.Namespace
        Parsed local source paths and an optional no-write preflight flag.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--fmp-path", type=Path, action="append", dest="fmp_paths")
    parser.add_argument("--b1q-path", type=Path, default=DEFAULT_B1Q_PATH)
    parser.add_argument("--uw-batch-manifest", type=Path, default=DEFAULT_UW_BATCH_MANIFEST)
    parser.add_argument("--uw-reused-manifest", type=Path, default=DEFAULT_UW_REUSED_MANIFEST)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    if args.fmp_paths is None:
        args.fmp_paths = list(DEFAULT_FMP_PATHS)
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Write the exact source-coverage artifact and stop on a source block.

    The command never reads target, metric, forecast, result, model, or
    holdout data.  If coverage passes, it still stops before panel construction
    because that subsequent operation has its own tested contract.
    """
    args = parse_args(argv)
    development_sessions, assets, retained_sessions = _frozen_development_contract(
        args.source_manifest
    )
    _assert_safe_paths(args)
    b2_asset_dates = _full_tape_asset_dates(
        session_dates=development_sessions,
        assets=assets,
        data_root=args.data_root,
        batch_manifest_path=args.uw_batch_manifest,
        reused_manifest_path=args.uw_reused_manifest,
    )
    ledger = build_target_free_source_coverage(
        session_dates=development_sessions,
        assets=assets,
        fmp_paths=tuple(args.fmp_paths),
        b1q_path=args.b1q_path,
        b2_asset_dates=b2_asset_dates,
        retained_sessions=retained_sessions,
        source_hashes=_source_hashes(args),
        schema_path=args.schema,
    )
    if args.check_only:
        print(f"CORRECTED_DEVELOPMENT_SOURCE_COVERAGE={ledger['status']}")
        print("TARGET_BINDING_PERMITTED=NO")
        return 0
    write_source_coverage_artifact(ledger, args.output_path)
    print(f"CORRECTED_DEVELOPMENT_SOURCE_COVERAGE={ledger['status']}")
    print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO")
    print("SAFE_TO_OPEN_OR_EVALUATE_OOS=NO")
    print("TARGET_BINDING_PERMITTED=NO")
    return 0


def _frozen_development_contract(
    path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return the exact approved development sessions, assets, and retained dates."""
    document = _read_json_object(path, "CORRECTED_DEVELOPMENT_SOURCE_MANIFEST_INVALID")
    recorded_hash = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    if not isinstance(recorded_hash, str) or canonical_sha256(unsigned) != recorded_hash:
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_MANIFEST_SELF_HASH_MISMATCH")
    development = _string_tuple(document.get("development_sessions"))
    acquired = _string_tuple(document.get("acquired_sessions"))
    retained = _string_tuple(document.get("reused_sessions"))
    assets = _string_tuple(document.get("selected_assets"))
    expected = build_study_sessions(
        "XNYS",
        development_end=date(2026, 7, 17),
        development_count=80,
        holdout_count=10,
    )
    if (
        document.get("status") != "PASS"
        or development != tuple(expected["development"])
        or assets != FROZEN_ASSETS
        or document.get("development_session_count") != 80
        or document.get("holdout_overlap") != []
        or document.get("holdout_reads") != 0
        or len(acquired) != 55
        or len(retained) != 25
        or set(acquired) | set(retained) != set(development)
        or set(acquired) & set(retained)
    ):
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_MANIFEST_IDENTITY_INVALID")
    return development, assets, retained


def _string_tuple(value: object) -> tuple[str, ...]:
    """Require one ordered non-empty string sequence from a compact manifest."""
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_MANIFEST_IDENTITY_INVALID")
    return tuple(value)


def _assert_safe_paths(args: argparse.Namespace) -> None:
    """Reject paths outside frozen local source and repository artifact roots."""
    d_paths = (*args.fmp_paths, args.b1q_path, args.uw_batch_manifest, args.data_root)
    if any(path.drive.casefold() != "d:" for path in d_paths):
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_PATH_UNSAFE")
    for path in (args.source_manifest, args.uw_reused_manifest, args.schema, args.output_path):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError as exc:
            raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_PATH_UNSAFE") from exc
    try:
        args.output_path.resolve().relative_to((ROOT / "artifacts").resolve())
    except ValueError as exc:
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_PATH_UNSAFE") from exc
    if "holdout" in args.output_path.as_posix().casefold():
        raise ValueError("CORRECTED_DEVELOPMENT_SOURCE_PATH_UNSAFE")


def _source_hashes(args: argparse.Namespace) -> dict[str, str]:
    """Hash compact source evidence and small target-free parquet inputs."""
    hashes = {
        "development_source_manifest": _sha256_file(args.source_manifest),
        "b1q_source": _sha256_file(args.b1q_path),
        "b2_full_tape_batch_manifest": _sha256_file(args.uw_batch_manifest),
        "b2_full_tape_reused_manifest": _sha256_file(args.uw_reused_manifest),
    }
    for index, path in enumerate(args.fmp_paths, start=1):
        hashes[f"fmp_source_{index}"] = _sha256_file(path)
    return hashes


def _sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest without exposing source contents."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_target_free_source_coverage(
    *,
    session_dates: Sequence[str],
    assets: Sequence[str],
    fmp_paths: Sequence[Path],
    b1q_path: Path,
    b2_asset_dates: pl.DataFrame,
    retained_sessions: Sequence[str],
    source_hashes: Mapping[str, str],
    schema_path: Path,
) -> dict[str, Any]:
    """Build and validate a predictor-only exact-source coverage ledger.

    Parameters
    ----------
    session_dates:
        Ordered frozen development session dates.
    assets:
        Selected outcome assets for the exact development grid.
    fmp_paths:
        Target-free one-minute FMP source files.  Only their asset-date
        identity columns are read in this stage.
    b1q_path:
        Target-free B1Q source-state Parquet path.
    b2_asset_dates:
        Asset-date identities backed by verified Unusual Whales Full Tape raw
        files.  No trade rows are read here.
    retained_sessions:
        Frozen retained sessions whose B1Q state must never be carried forward.
    source_hashes:
        SHA-256 identities for the named local source evidence.
    schema_path:
        Local schema for the source coverage ledger.

    Returns
    -------
    dict[str, object]
        A schema-validated source coverage ledger.  A blocked ledger is a
        valid outcome and must stop before predictor or target construction.

    Raises
    ------
    ValueError
        If no FMP source is supplied or the target-free ledger violates its
        explicit schema or self-hash contract.
    """
    if not fmp_paths:
        raise ValueError("CORRECTED_DEVELOPMENT_FMP_SOURCE_MISSING")
    origins = build_exact_development_origins(session_dates, assets=assets)
    b0_asset_dates = pl.concat(
        [
            pl.scan_parquet(path)
            .select("asset", "session_date")
            .filter(
                pl.col("asset").is_in(assets) & pl.col("session_date").is_in(session_dates)
            )
            .unique()
            .collect()
            for path in fmp_paths
        ]
    ).unique()
    b1q_source = (
        pl.scan_parquet(b1q_path)
        .filter(pl.col("asset").is_in(assets) & pl.col("session_date").is_in(session_dates))
        .collect()
    )
    retained_asset_dates = frozenset(
        (asset, session_date) for asset in assets for session_date in retained_sessions
    )
    prepared_b1q = prepare_b1q_source(
        origins,
        b1q_source,
        retained_cache_asset_dates=retained_asset_dates,
    )
    ledger = build_source_coverage_ledger(
        origins,
        b0_asset_dates=b0_asset_dates,
        b2_asset_dates=b2_asset_dates,
        b1q_source=prepared_b1q,
        source_hashes=source_hashes,
    )
    validate_source_coverage_ledger(ledger, schema_path)
    return ledger


def write_source_coverage_artifact(ledger: Mapping[str, Any], output_path: Path) -> None:
    """Write one immutable, canonical source-coverage artifact.

    Parameters
    ----------
    ledger:
        Schema-validated source coverage document to serialize canonically.
    output_path:
        Local artifact path.  Existing output is retained only when its bytes
        match exactly.

    Raises
    ------
    FileExistsError
        If an existing artifact differs from the deterministic replay.
    """
    rendered = json.dumps(dict(ledger), ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.part")
    try:
        temporary.write_text(rendered, encoding="utf-8")
        if output_path.exists():
            if output_path.read_bytes() != temporary.read_bytes():
                raise FileExistsError("CORRECTED_DEVELOPMENT_SOURCE_COVERAGE_OUTPUT_CONFLICT")
            return
        try:
            os.link(temporary, output_path)
        except FileExistsError:
            if output_path.read_bytes() != temporary.read_bytes():
                raise FileExistsError(
                    "CORRECTED_DEVELOPMENT_SOURCE_COVERAGE_OUTPUT_CONFLICT"
                ) from None
    finally:
        temporary.unlink(missing_ok=True)


def _full_tape_asset_dates(
    *,
    session_dates: Sequence[str],
    assets: Sequence[str],
    data_root: Path,
    batch_manifest_path: Path,
    reused_manifest_path: Path,
) -> pl.DataFrame:
    """Expand verified local Full Tape ZIPs to target-free asset-date identities.

    Full Tape is market-wide, so one manifest-verified ZIP supports each
    selected asset for that session.  The function checks only compact manifest
    fields and file size; it deliberately does not open or parse trade rows.
    """
    batch = _read_json_object(batch_manifest_path, "CORRECTED_DEVELOPMENT_UW_BATCH_MANIFEST")
    reused = _read_json_object(reused_manifest_path, "CORRECTED_DEVELOPMENT_UW_REUSED_MANIFEST")
    verified_sessions: set[str] = set()
    for record in batch.get("sessions", []):
        if _full_tape_record_is_verified(
            record,
            data_root,
            path_key="raw_path",
            status_key="status",
        ):
            verified_sessions.add(str(record["session_date"]))
    for record in reused.get("entries", []):
        if _full_tape_record_is_verified(
            record,
            data_root,
            path_key="destination",
            status_key="destination_verified",
        ):
            verified_sessions.add(str(record["session_date"]))
    return pl.DataFrame(
        [
            {"asset": asset, "session_date": session_date}
            for session_date in session_dates
            if session_date in verified_sessions
            for asset in assets
        ],
        schema={"asset": pl.String, "session_date": pl.String},
    )


def _full_tape_record_is_verified(
    record: object,
    data_root: Path,
    *,
    path_key: str,
    status_key: str,
) -> bool:
    """Return whether one compact Full Tape record binds a non-empty local ZIP."""
    if not isinstance(record, Mapping):
        return False
    session_date = record.get("session_date")
    relative_path = record.get(path_key)
    byte_count = record.get("bytes")
    digest = record.get("sha256")
    status = record.get(status_key)
    if (
        not isinstance(session_date, str)
        or not isinstance(relative_path, str)
        or not isinstance(byte_count, int)
        or byte_count <= 0
        or not isinstance(digest, str)
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
        or status not in {"PASS", True}
    ):
        return False
    candidate = (data_root / relative_path).resolve()
    try:
        candidate.relative_to(data_root.resolve())
    except ValueError:
        return False
    return candidate.is_file() and candidate.stat().st_size == byte_count


def _read_json_object(path: Path, error_code: str) -> dict[str, Any]:
    """Read one compact JSON object without exposing filesystem values in errors."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(payload, dict):
        raise ValueError(error_code)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
