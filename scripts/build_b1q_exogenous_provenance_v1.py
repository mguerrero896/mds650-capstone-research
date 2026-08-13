"""Capture and bind target-free B1Q rate/dividend provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

import httpx
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mds650.b1q_exogenous_provenance_v1 import (  # noqa: E402
    augment_b1q_exogenous_provenance,
    parse_treasury_yield_curve_xml,
)

ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
MINIMUM_FREE_BYTES = 80 * 1024**3
SCHEMA = ROOT / "specs/001-pit-options-rv30/contracts/b1q-exogenous-provenance-v1.schema.json"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse bounded acquisition and output paths."""
    default_root = Path(os.environ.get("MDS650_BULK_ROOT", "D:/MDS650"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=default_root)
    parser.add_argument("--execute", action="store_true", help="Fetch only missing raw inputs")
    parser.add_argument(
        "--artifact",
        type=Path,
        default=ROOT / "artifacts/provider_timing_v21/b1q_exogenous_provenance_v1_20260813.json",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build immutable raw evidence, augmented B1Q, and sanitized manifest."""
    args = parse_args(argv)
    data_root = args.data_root.resolve()
    if data_root.drive.casefold() != "d:":
        raise RuntimeError("B1Q_EXOGENOUS_DATA_ROOT_NOT_D")
    if shutil.disk_usage(data_root).free < MINIMUM_FREE_BYTES:
        raise RuntimeError("B1Q_EXOGENOUS_MINIMUM_FREE_SPACE_NOT_MET")
    try:
        args.artifact.resolve().relative_to((ROOT / "artifacts").resolve())
    except ValueError as exc:
        raise RuntimeError("B1Q_EXOGENOUS_ARTIFACT_PATH_UNSAFE") from exc

    raw_root = data_root / "phase6/raw/fmp_exogenous_v1"
    capture_manifest_path = raw_root / "capture_manifest.json"
    raw_root.mkdir(parents=True, exist_ok=True)
    captures = _capture_sources(raw_root, execute=args.execute)
    _write_or_verify_json(capture_manifest_path, {"schema_version": "1.0", "captures": captures})

    matrix_path = data_root / "phase6/data/b1q/b1_origin_matrix_20d.parquet"
    attempts_path = data_root / "phase6/data/b1q/b1_iv_attempts_20d.parquet"
    output_path = data_root / "phase6/data/b1q/b1_origin_matrix_20d_exogenous_pit_v1.parquet"
    matrix = pl.read_parquet(matrix_path)
    spots = (
        pl.scan_parquet(attempts_path)
        .select("asset", "session_date", "forecast_origin_utc", "spot")
        .sort(["asset", "session_date", "forecast_origin_utc"])
        .group_by(["asset", "session_date"], maintain_order=True)
        .agg(pl.col("spot").first())
        .collect()
    )
    treasury_payloads = {
        year: (raw_root / f"treasury_{year}.xml").read_bytes() for year in ("2025", "2026")
    }
    rates: dict[str, float] = {}
    for payload in treasury_payloads.values():
        overlap = set(rates) & set(parse_treasury_yield_curve_xml(payload))
        if overlap:
            raise RuntimeError("B1Q_TREASURY_DATE_OVERLAP")
        rates.update(parse_treasury_yield_curve_xml(payload))
    dividends = {asset: _read_json_list(raw_root / f"dividends_{asset}.json") for asset in ASSETS}
    capture_by_role = {str(item["role"]): item for item in captures}
    augmented = augment_b1q_exogenous_provenance(
        matrix,
        spots,
        treasury_rates=rates,
        dividends_by_asset=dividends,
        treasury_payload_sha256_by_year={
            year: str(capture_by_role[f"TREASURY_{year}"]["sha256"]) for year in ("2025", "2026")
        },
        dividend_payload_sha256_by_asset={
            asset: str(capture_by_role[f"DIVIDENDS_{asset}"]["sha256"]) for asset in ASSETS
        },
    )
    if not matrix.equals(augmented.select(matrix.columns)):
        raise RuntimeError("B1Q_ORIGINAL_COLUMNS_CHANGED")
    output_sha256 = _write_or_verify_parquet(output_path, augmented)

    daily = augmented.select("asset", "session_date", "dividend_assumption").unique()
    artifact: dict[str, Any] = {
        "schema_version": "b1q-exogenous-provenance-v1.0",
        "status": "PASS_EXACT_VALUE_PARITY_UNDER_REGISTERED_AVAILABILITY_RULES",
        "scope": "target_blind_exogenous_input_provenance_only",
        "source_b1q_sha256": _sha256_file(matrix_path),
        "augmented_b1q_sha256": output_sha256,
        "row_count": augmented.height,
        "asset_count": augmented["asset"].n_unique(),
        "session_count": augmented["session_date"].n_unique(),
        "rate_observation_count": augmented["rate_source_date"].n_unique(),
        "asset_day_count": daily.height,
        "positive_dividend_asset_day_count": daily.filter(
            pl.col("dividend_assumption") == "PRE_ORIGIN_TRAILING_DECLARATIONS"
        ).height,
        "q_zero_asset_day_count": daily.filter(
            pl.col("dividend_assumption") == "NO_PRE_ORIGIN_DIVIDEND_Q_ZERO"
        ).height,
        "value_mismatch_count": 0,
        "future_availability_count": 0,
        "availability_rules": {
            "treasury": "US_TREASURY_18_ET_PLUS_FMP_MAX_CYCLE",
            "dividend_positive": "DECLARATION_DATE_END_PLUS_FMP_MAX_CYCLE",
            "dividend_zero": "NO_PRIOR_DECLARATION_THROUGH_PRIOR_DAY_PLUS_FMP_MAX_CYCLE",
            "claim_boundary": (
                "RECONSTRUCTED_PIT_FROM_DOCUMENTED_SOURCE_DATES_NOT_HISTORICAL_CLIENT_RECEIPT"
            ),
        },
        "official_sources": {
            "treasury_methodology": "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/treasury-yield-curve-methodology",
            "treasury_xml": "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed",
            "fmp_dividends": "https://site.financialmodelingprep.com/developer/docs/historical-stock-dividends-api/",
            "fmp_cycle_times": "https://site.financialmodelingprep.com/developer/docs/cycle-times-stable",
        },
        "captures": captures,
        "safe_to_build_corrected_target_blind_panel": True,
        "safe_to_reconcile_existing_results": "NO_SEPARATE_GATE_REQUIRED",
        "safe_to_open_or_evaluate_oos": "NO",
        "target_or_metric_payload_read": False,
        "model_fit_performed": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    artifact["semantic_self_hash"] = _semantic_hash(artifact)
    _validate_schema(artifact)
    _write_or_verify_json(args.artifact, artifact)
    print(f"B1Q_EXOGENOUS_PROVENANCE={artifact['status']}")
    print(f"AUGMENTED_B1Q_SHA256={output_sha256}")
    print("SAFE_TO_RECONCILE_EXISTING_RESULTS=NO_SEPARATE_GATE_REQUIRED")
    return 0


def _capture_sources(raw_root: Path, *, execute: bool) -> list[dict[str, object]]:
    """Fetch only missing official/FMP sources and return sanitized identities."""
    requests: list[tuple[str, Path, str, Mapping[str, str], Mapping[str, str]]] = []
    for year in ("2025", "2026"):
        requests.append(
            (
                f"TREASURY_{year}",
                raw_root / f"treasury_{year}.xml",
                "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
                {"data": "daily_treasury_yield_curve", "field_tdr_date_value": year},
                {},
            )
        )
    fmp_key = os.environ.get("FMP_API_KEY", "")
    if any(not path.exists() for _, path, _, _, _ in requests) or any(
        not (raw_root / f"dividends_{asset}.json").exists() for asset in ASSETS
    ):
        if not execute:
            raise RuntimeError("B1Q_EXOGENOUS_RAW_INPUT_MISSING_EXECUTE_REQUIRED")
        if not fmp_key.strip():
            raise RuntimeError("B1Q_EXOGENOUS_FMP_KEY_MISSING")
    for asset in ASSETS:
        requests.append(
            (
                f"DIVIDENDS_{asset}",
                raw_root / f"dividends_{asset}.json",
                "https://financialmodelingprep.com/stable/dividends",
                {"symbol": asset},
                {"apikey": fmp_key},
            )
        )

    captures: list[dict[str, object]] = []
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for role, path, url, params, headers in requests:
            if not path.exists():
                response = client.get(url, params=params, headers=headers)
                if response.status_code != 200:
                    raise RuntimeError(f"B1Q_EXOGENOUS_HTTP_{response.status_code}:{role}")
                if role.startswith("TREASURY_"):
                    parse_treasury_yield_curve_xml(response.content)
                else:
                    body = response.json()
                    if not isinstance(body, list) or not all(
                        isinstance(item, dict) for item in body
                    ):
                        raise RuntimeError(f"B1Q_EXOGENOUS_SCHEMA_INVALID:{role}")
                _write_once(path, response.content)
                captured_at = (
                    datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                )
            else:
                captured_at = _existing_capture_time(raw_root, role)
            captures.append(
                {
                    "role": role,
                    "logical_name": path.name,
                    "sha256": _sha256_file(path),
                    "bytes": path.stat().st_size,
                    "captured_at_utc": captured_at,
                }
            )
    return captures


def _existing_capture_time(raw_root: Path, role: str) -> str:
    """Recover the immutable first-capture time during an idempotent replay."""
    manifest = raw_root / "capture_manifest.json"
    if not manifest.exists():
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    for item in document.get("captures", []):
        if item.get("role") == role:
            return str(item["captured_at_utc"])
    raise RuntimeError("B1Q_EXOGENOUS_CAPTURE_MANIFEST_INCOMPLETE")


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    """Read one raw list payload without exposing its local path."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeError("B1Q_EXOGENOUS_DIVIDEND_PAYLOAD_INVALID")
    return value


def _write_once(path: Path, payload: bytes) -> None:
    """Create an immutable file without replacing conflicting evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    temporary.write_bytes(payload)
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise RuntimeError("B1Q_EXOGENOUS_RAW_OUTPUT_CONFLICT") from None
    finally:
        temporary.unlink(missing_ok=True)


def _write_or_verify_json(path: Path, document: Mapping[str, object]) -> None:
    """Write deterministic JSON once or accept a byte-identical replay."""
    payload = (json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode()
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError("B1Q_EXOGENOUS_JSON_OUTPUT_CONFLICT")
        return
    _write_once(path, payload)


def _write_or_verify_parquet(path: Path, frame: pl.DataFrame) -> str:
    """Write a deterministic Parquet candidate and retain only exact identity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    frame.write_parquet(temporary, compression="zstd")
    try:
        candidate_hash = _sha256_file(temporary)
        if path.exists():
            if _sha256_file(path) != candidate_hash:
                raise RuntimeError("B1Q_EXOGENOUS_PARQUET_OUTPUT_CONFLICT")
        else:
            os.link(temporary, path)
        return candidate_hash
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    """Return one streaming file digest."""
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _semantic_hash(document: Mapping[str, object]) -> str:
    """Return canonical semantic SHA-256 excluding the hash field itself."""
    unsigned = {key: value for key, value in document.items() if key != "semantic_self_hash"}
    payload = json.dumps(
        unsigned, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_schema(document: Mapping[str, object]) -> None:
    """Validate the artifact against its local Draft 2020-12 schema."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = import_module("jsonschema").Draft202012Validator
    validator.check_schema(schema)
    errors = list(validator(schema).iter_errors(document))
    if errors:
        raise RuntimeError("B1Q_EXOGENOUS_ARTIFACT_SCHEMA_INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
