"""Build target-blind B2 timing sidecars from already-downloaded Full Tape."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import build_phase5_common_panel as common_builder
import polars as pl
import run_phase4b

from mds650.stability import B2_DELAYS_SECONDS, b2_sensitivity_column
from mds650.study_design import B2_FEATURE_NAMES, canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PHASE5 = ROOT / "artifacts" / "phase5"
DEFAULT_PANEL = PHASE5 / "common_development_80d.parquet"
DEFAULT_QUALITY = PHASE5 / "development_panel_quality.json"
DEFAULT_EVENT_ROOT = Path("D:/MDS650/data/option_events")
DEFAULT_OUTPUT = Path("D:/MDS650/data/phase5_stability/development_stability_inputs_80d.parquet")
DEFAULT_MANIFEST = PHASE5 / "development_stability_input_manifest.json"
DEFAULT_DELAYS = (120, 300)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _event_files(
    event_root: Path,
    *,
    session_dates: Sequence[str],
    selected_assets: Sequence[str],
) -> list[tuple[Path, str, str | None]]:
    files: list[tuple[Path, str, str | None]] = []
    for day in sorted(session_dates):
        combined = event_root / f"date={day}" / "events.parquet"
        if combined.is_file():
            files.append((combined, day, None))
            continue
        for asset in sorted(selected_assets):
            path = event_root / f"date={day}" / f"asset={asset}" / "events.parquet"
            if not path.is_file():
                raise FileNotFoundError(f"PHASE5_STABILITY_EVENT_FILE_MISSING:{day}:{asset}")
            files.append((path, day, asset))
    return files


def _delay_frame(
    origins: pl.DataFrame,
    aggregates: Sequence[pl.DataFrame],
    *,
    delay_seconds: int,
) -> pl.DataFrame:
    if not aggregates:
        raise ValueError(f"PHASE5_STABILITY_AGGREGATION_EMPTY:{delay_seconds}")
    combined = pl.concat(aggregates, how="diagonal_relaxed")
    if combined["origin_id"].n_unique() != combined.height:
        raise ValueError(f"PHASE5_STABILITY_AGGREGATE_DUPLICATE:{delay_seconds}")
    grid = origins.select("origin_id", "forecast_origin_utc").with_columns(
        (pl.col("forecast_origin_utc") - pl.duration(seconds=delay_seconds)).alias("b2_window_end"),
        (
            pl.col("forecast_origin_utc")
            - pl.duration(seconds=delay_seconds)
            - pl.duration(minutes=5)
        ).alias("b2_window_start"),
    )
    result = grid.join(combined, on="origin_id", how="left")
    zero_fields = (
        "b2_option_trade_count_5m",
        "b2_unique_contract_count_5m",
        "b2_total_premium_5m",
        "b2_max_trade_premium_5m",
        "b2_call_premium_5m",
        "b2_put_premium_5m",
        "_ask_premium",
        "_bid_premium",
        "b2_repeated_contract_premium",
        "b2_strike_concentration",
        "b2_expiry_concentration",
    )
    result = result.with_columns(
        [pl.col(column).fill_null(0) for column in zero_fields]
    ).with_columns(
        pl.when(pl.col("b2_total_premium_5m") > 0)
        .then(pl.col("_ask_premium") / pl.col("b2_total_premium_5m"))
        .otherwise(0.0)
        .alias("b2_ask_side_premium_share"),
        pl.when(pl.col("b2_total_premium_5m") > 0)
        .then(pl.col("_bid_premium") / pl.col("b2_total_premium_5m"))
        .otherwise(0.0)
        .alias("b2_bid_side_premium_share"),
        (pl.col("b2_option_trade_count_5m") > 0).alias("b2_option_activity_present"),
        pl.lit("operational_availability_proxy").alias("b2_availability_semantics"),
    )
    compact = common_builder._compact_prefixed_b2(result)
    names = {
        "b2_window_start": f"b2_window_start__{delay_seconds}s",
        "b2_window_end": f"b2_window_end__{delay_seconds}s",
        "b2_max_operational_time": f"b2_max_operational_time__{delay_seconds}s",
        "b2_option_activity_present": f"b2_option_activity_present__{delay_seconds}s",
        **{feature: b2_sensitivity_column(feature, delay_seconds) for feature in B2_FEATURE_NAMES},
    }
    return compact.select("origin_id", *names).rename(names)


def build_stability_inputs(
    panel: pl.DataFrame,
    *,
    event_root: Path,
    selected_assets: Sequence[str],
    delays_seconds: Sequence[int] = DEFAULT_DELAYS,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Build one target-free timing-sensitivity row per selected origin.

    Parameters
    ----------
    panel:
        Canonical panel supplying origin keys, spot and immutable provenance.
    event_root:
        Persistent local root containing already-filtered Full Tape Parquet.
    selected_assets:
        Quality-only frozen universe.
    delays_seconds:
        Registered non-primary B2 cutoffs.

    Returns
    -------
    tuple[polars.DataFrame, dict[str, Any]]
        Compact sidecar and sanitized build evidence.

    Raises
    ------
    ValueError
        If origins, delays or aggregate contracts are invalid.
    FileNotFoundError
        If a required immutable event partition is absent.
    """
    delays = tuple(int(value) for value in delays_seconds)
    if (
        not selected_assets
        or not delays
        or len(delays) != len(set(delays))
        or any(value not in B2_DELAYS_SECONDS or value == 60 for value in delays)
    ):
        raise ValueError("PHASE5_STABILITY_DELAYS_INVALID")
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "b0_spot",
        "b2_source_hash",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"PHASE5_STABILITY_PANEL_COLUMNS_MISSING:{','.join(missing)}")
    origins = (
        panel.filter(pl.col("asset").is_in(selected_assets))
        .select(
            "origin_id",
            "asset",
            "session_date",
            "forecast_origin_utc",
            "b0_spot",
        )
        .with_columns(pl.lit("PHASE5_STABILITY").alias("sample_role"))
    )
    if (
        origins.is_empty()
        or origins["origin_id"].n_unique() != origins.height
        or sorted(origins["asset"].unique().to_list()) != sorted(selected_assets)
    ):
        raise ValueError("PHASE5_STABILITY_ORIGIN_CONTRACT_INVALID")
    files = _event_files(
        event_root,
        session_dates=origins["session_date"].unique().to_list(),
        selected_assets=selected_assets,
    )
    parts: dict[int, list[pl.DataFrame]] = {delay: [] for delay in delays}
    source_files: list[dict[str, str | None]] = []
    for path, day, asset in files:
        digest = _sha256_file(path)
        source_files.append(
            {
                "session_date": day,
                "asset": asset,
                "file_name": path.name,
                "sha256": digest,
            }
        )
        for delay in delays:
            aggregate = run_phase4b._aggregate_one_file(
                path,
                "PHASE5_STABILITY",
                day,
                origins,
                delay,
                digest,
            )
            if aggregate is not None:
                parts[delay].append(aggregate)
    sidecar = origins.select("origin_id")
    for delay in delays:
        sidecar = sidecar.join(
            _delay_frame(origins, parts[delay], delay_seconds=delay),
            on="origin_id",
            how="inner",
        )
    if sidecar.height != origins.height or sidecar["origin_id"].n_unique() != sidecar.height:
        raise ValueError("PHASE5_STABILITY_SIDECAR_ORIGIN_MISMATCH")
    evidence = {
        "status": "PASS_TARGET_BLIND_STABILITY_INPUTS",
        "origin_count": sidecar.height,
        "session_count": origins["session_date"].n_unique(),
        "selected_assets": sorted(selected_assets),
        "delays_seconds": list(delays),
        "source_file_count": len(source_files),
        "source_files": source_files,
        "target_columns_read": [],
        "provider_requests": 0,
    }
    return sidecar.sort("origin_id"), evidence


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local Phase 5 timing-sensitivity inputs.")
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--quality", type=Path, default=DEFAULT_QUALITY)
    parser.add_argument("--event-root", type=Path, default=DEFAULT_EVENT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> None:
    """Build, hash and persist the development stability sidecar."""
    arguments = _arguments()
    quality = json.loads(arguments.quality.read_text(encoding="utf-8"))
    panel = pl.read_parquet(arguments.panel)
    sidecar, evidence = build_stability_inputs(
        panel,
        event_root=arguments.event_root,
        selected_assets=quality["selected_assets"],
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_parquet(arguments.output, compression="zstd")
    manifest: dict[str, Any] = {
        "schema_version": "phase5-stability-inputs-1.0",
        **evidence,
        "input_hashes": {
            "common_development_80d.parquet": _sha256_file(arguments.panel),
            "development_panel_quality.json": _sha256_file(arguments.quality),
        },
        "output": {
            "file_name": arguments.output.name,
            "sha256": _sha256_file(arguments.output),
        },
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    arguments.manifest.parent.mkdir(parents=True, exist_ok=True)
    arguments.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "origins": manifest["origin_count"],
                "sessions": manifest["session_count"],
                "manifest_sha256": manifest["manifest_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
