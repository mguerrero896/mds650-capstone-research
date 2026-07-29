"""Build the canonical 80-session Phase 5 development panel."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

import polars as pl

from mds650.phase5_features import add_compact_b2_features
from mds650.phase5_panel import build_common_panel, target_sha256
from mds650.study_design import B2_FEATURE_NAMES, canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
RAW_B2_MAP = {
    "b2_option_trade_count_5m": "option_trade_count_5m",
    "b2_unique_contract_count_5m": "unique_contract_count_5m",
    "b2_total_premium_5m": "total_premium_5m",
    "b2_max_trade_premium_5m": "max_trade_premium_5m",
    "b2_call_premium_5m": "call_premium_5m",
    "b2_put_premium_5m": "put_premium_5m",
    "b2_ask_side_premium_share": "ask_side_premium_share",
    "b2_bid_side_premium_share": "bid_side_premium_share",
    "b2_repeated_contract_premium": "repeated_contract_premium",
    "b2_strike_concentration": "strike_concentration",
    "b2_expiry_concentration": "expiry_concentration",
}


@dataclass(frozen=True)
class PanelBuildConfig:
    """Canonical local inputs for the Phase 5 development-only build."""

    session_manifest: Path = ROOT / "artifacts/phase5/study_sessions_90.json"
    reused_manifest: Path = ROOT / "artifacts/phase5/reused_25_session_manifest.json"
    retained_matrix: Path = ROOT / "artifacts/phase4b/origin_matrix_25d.parquet"
    full_tape_manifest: Path = Path("D:/MDS650/manifests/full_tape/batch_manifest.json")
    event_root: Path = Path("D:/MDS650/data/option_events")
    new_fmp_root: Path = Path("D:/MDS650/data/fmp/phase5_missing_55")
    new_b1_root: Path = Path("D:/MDS650/data/b1q/phase5_missing_55")
    output_root: Path = ROOT / "artifacts/phase5"


DEFAULT_CONFIG = PanelBuildConfig()


def _verified_manifest(payload: Mapping[str, Any], error: str) -> dict[str, Any]:
    manifest = dict(payload)
    digest = manifest.pop("manifest_sha256", None)
    if digest != canonical_sha256(manifest):
        raise ValueError(error)
    return dict(payload)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"PHASE5_JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_b1_attempt_ledger(
    path: Path,
    summary: Mapping[str, Any],
) -> dict[str, int]:
    """Validate the complete B1Q attempt ledger without loading it eagerly."""
    scan = pl.scan_parquet(path)
    required = {
        "session_date",
        "forecast_origin_ns",
        "rate_source_date",
        "sip_timestamp",
        "source_request_hash",
    }
    missing = sorted(required - set(scan.collect_schema().names()))
    if missing:
        raise ValueError(f"PHASE5_B1_ATTEMPT_COLUMNS_MISSING:{','.join(missing)}")
    stats = scan.select(
        pl.len().alias("rows"),
        (pl.col("rate_source_date") > pl.col("session_date"))
        .sum()
        .alias("future_rate_rows"),
        (
            pl.col("sip_timestamp").is_not_null()
            & (pl.col("sip_timestamp") > pl.col("forecast_origin_ns"))
        )
        .sum()
        .alias("future_quote_rows"),
        (
            pl.col("source_request_hash").is_null()
            | (pl.col("source_request_hash") == "")
        )
        .sum()
        .alias("missing_request_hash_rows"),
    ).collect().row(0, named=True)
    expected_rows = summary.get("iv_attempt_rows")
    if (
        not isinstance(expected_rows, int)
        or stats["rows"] != expected_rows
        or stats["future_rate_rows"]
        or stats["future_quote_rows"]
        or stats["missing_request_hash_rows"]
    ):
        raise ValueError("PHASE5_B1_ATTEMPT_LEDGER_INVALID")
    return {key: int(value) for key, value in stats.items()}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def reconcile_development_sources(
    session_manifest: Mapping[str, Any],
    reused_manifest: Mapping[str, Any],
    acquired_sessions: Sequence[str],
) -> dict[str, Any]:
    """Verify the exact 25 reused plus 55 newly acquired development dates.

    Parameters
    ----------
    session_manifest:
        Frozen 80-development/10-holdout manifest.
    reused_manifest:
        Hash-verified retained-session manifest.
    acquired_sessions:
        Newly acquired Full Tape session dates.

    Returns
    -------
    dict[str, Any]
        Sanitized reconciliation suitable for the development source manifest.

    Raises
    ------
    ValueError
        If a manifest hash, status, count, partition, or holdout boundary fails.
    """
    sessions = _verified_manifest(
        session_manifest,
        "PHASE5_SESSION_MANIFEST_HASH_MISMATCH",
    )
    reused = _verified_manifest(
        reused_manifest,
        "PHASE5_REUSED_MANIFEST_HASH_MISMATCH",
    )
    development = list(sessions.get("development", ()))
    holdout = set(sessions.get("holdout", ()))
    retained = list(reused.get("sessions", ()))
    acquired = list(acquired_sessions)
    expected_acquired = sorted(set(development) - set(retained))
    valid = (
        sessions.get("development_count") == 80
        and sessions.get("holdout_count") == 10
        and reused.get("status") == "PASS"
        and reused.get("session_count") == 25
        and len(retained) == len(set(retained)) == 25
        and acquired == sorted(set(acquired))
        and acquired == expected_acquired
        and len(acquired) == 55
        and not (set(retained) & set(acquired))
        and set(retained) | set(acquired) == set(development)
        and not ((set(retained) | set(acquired)) & holdout)
    )
    if not valid:
        raise ValueError("PHASE5_DEVELOPMENT_SOURCE_MISMATCH")
    return {
        "status": "PASS",
        "development_sessions": development,
        "development_session_count": len(development),
        "reused_sessions": retained,
        "reused_session_count": len(retained),
        "acquired_sessions": acquired,
        "acquired_session_count": len(acquired),
        "holdout_overlap": sorted((set(retained) | set(acquired)) & holdout),
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def _new_origins_and_b0(
    origins_source: pl.DataFrame,
    bars: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    phase4b = import_module("run_phase4b")
    origins = phase4b._canonicalize_origins(origins_source, "DEVELOPMENT_NEW_55")
    origin_ids = set(origins["origin_id"].to_list())
    targets = phase4b._target_lookup(origins, bars)
    target_frame = pl.DataFrame(
        [value for key, value in targets.items() if key in origin_ids],
        strict=False,
    )
    origins = origins.join(target_frame, on="origin_id", how="left")
    plus1, plus2 = phase4b.build_b0_variants(origins, bars)
    plus2_columns = [
        "origin_id",
        *[column for column in plus2.columns if column.startswith("b0_plus2_")],
    ]
    b0 = plus1.join(plus2.select(plus2_columns), on="origin_id", how="left")
    return origins, b0


def _standardize_b1(
    frame: pl.DataFrame,
    origins: pl.DataFrame,
    *,
    retained: bool,
) -> pl.DataFrame:
    if retained:
        aliases = {
            "b1q_b1a_complete": "b1a_complete",
        }
        source = frame.rename(
            {key: value for key, value in aliases.items() if key in frame.columns}
        )
    else:
        mapping = origins.select(
            pl.col("source_origin_id"),
            pl.col("origin_id").alias("_canonical_origin_id"),
        )
        source = (
            frame.rename({"origin_id": "source_origin_id"})
            .join(mapping, on="source_origin_id", how="inner")
            .drop("source_origin_id")
            .rename({"_canonical_origin_id": "origin_id"})
        )
    aliases = {
        "valid_expiry_bucket_count": "b1q_valid_expiry_bucket_count",
        "median_quote_age": "b1q_median_quote_age",
        "median_relative_spread": "b1q_median_relative_spread",
        "iv_inversion_success_rate": "b1q_iv_inversion_success_rate",
        "first_failure_code": "b1q_missing_reason",
    }
    source = source.rename(
        {
            key: value
            for key, value in aliases.items()
            if key in source.columns and value not in source.columns
        }
    )
    required = {
        "origin_id",
        "b1q_atm_iv",
        "b1a_complete",
        "b1q_pit_evidence_valid",
        "b1q_quote_not_after_origin",
    }
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"PHASE5_B1_COLUMNS_MISSING:{','.join(missing)}")
    if source.height != origins.height or source["origin_id"].n_unique() != source.height:
        raise ValueError("PHASE5_B1_ORIGIN_COVERAGE_INVALID")
    optional = (
        "b1q_max_sip_timestamp_ns",
        "b1q_valid_expiry_bucket_count",
        "b1q_median_quote_age",
        "b1q_median_relative_spread",
        "b1q_iv_inversion_success_rate",
        "b1q_missing_reason",
    )
    return source.select(
        [
            "origin_id",
            "b1q_atm_iv",
            "b1a_complete",
            "b1q_pit_evidence_valid",
            "b1q_quote_not_after_origin",
            *[column for column in optional if column in source.columns],
        ]
    )


def _compact_prefixed_b2(frame: pl.DataFrame) -> pl.DataFrame:
    required = {
        "origin_id",
        "b2_window_start",
        "b2_window_end",
        "b2_max_operational_time",
        *RAW_B2_MAP,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"PHASE5_B2_COLUMNS_MISSING:{','.join(missing)}")
    optional = [
        column
        for column in (
            "b2_source_hash",
            "b2_option_activity_present",
            "b2_availability_semantics",
        )
        if column in frame.columns
    ]
    selected = frame.select(
        [
            "origin_id",
            "b2_window_start",
            "b2_window_end",
            "b2_max_operational_time",
            *optional,
            *RAW_B2_MAP,
        ]
    ).rename(RAW_B2_MAP)
    return add_compact_b2_features(selected)


def _new_b2(
    origins: pl.DataFrame,
    b0: pl.DataFrame,
    event_root: Path,
    session_hashes: Mapping[str, str],
) -> pl.DataFrame:
    phase4b = import_module("run_phase4b")
    origin_key = origins.join(
        b0.select(["origin_id", "b0_spot"]),
        on="origin_id",
        how="left",
    )
    aggregates: list[pl.DataFrame] = []
    for day in sorted(session_hashes):
        source_hash = session_hashes[day]
        if len(source_hash) != 64:
            raise ValueError(f"PHASE5_FULL_TAPE_HASH_INVALID:{day}")
        for asset in ASSETS:
            path = event_root / f"date={day}" / f"asset={asset}" / "events.parquet"
            if not path.is_file():
                raise FileNotFoundError(f"PHASE5_EVENT_PARTITION_MISSING:{day}:{asset}")
            aggregate = phase4b._aggregate_one_file(
                path,
                "DEVELOPMENT_NEW_55",
                day,
                origin_key,
                60,
                source_hash,
            )
            if aggregate is not None:
                aggregates.append(aggregate)
    if not aggregates:
        raise ValueError("PHASE5_B2_AGGREGATION_EMPTY")
    aggregate_frame = pl.concat(aggregates, how="diagonal_relaxed")
    if aggregate_frame["origin_id"].n_unique() != aggregate_frame.height:
        raise ValueError("PHASE5_B2_AGGREGATE_DUPLICATE_ORIGIN")

    grid = origins.select(
        ["origin_id", "session_date", "forecast_origin_utc"]
    ).join(
        pl.DataFrame(
            {
                "session_date": list(session_hashes),
                "_session_source_hash": list(session_hashes.values()),
            }
        ),
        on="session_date",
        how="left",
    ).with_columns(
        (pl.col("forecast_origin_utc") - pl.duration(seconds=60)).alias(
            "b2_window_end"
        ),
        (
            pl.col("forecast_origin_utc")
            - pl.duration(seconds=60)
            - pl.duration(minutes=5)
        ).alias("b2_window_start"),
    )
    result = grid.join(aggregate_frame, on="origin_id", how="left")
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
        (pl.col("b2_option_trade_count_5m") > 0).alias(
            "b2_option_activity_present"
        ),
        pl.lit("operational_availability_proxy").alias(
            "b2_availability_semantics"
        ),
        pl.coalesce("b2_source_hash", "_session_source_hash").alias(
            "b2_source_hash"
        ),
    ).drop(
        "_session_source_hash"
    )
    return _compact_prefixed_b2(result)


def _retained_components(
    retained: pl.DataFrame,
    holdout: frozenset[str],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    origins = retained.select(
        [
            "origin_id",
            "asset",
            "session_date",
            "forecast_origin_utc",
            "sample_role",
            "rv30",
            "target_future_close_count",
            "target_price_count",
            "target_validity",
        ]
    )
    b0_columns = [
        "origin_id",
        *[
            column
            for column in retained.columns
            if column.startswith("b0_") and column not in {"b0_complete"}
        ],
    ]
    b0 = retained.select(b0_columns)
    b1 = _standardize_b1(retained, origins, retained=True)
    b2 = _compact_prefixed_b2(retained)
    all_rows, common = build_common_panel(
        origins,
        b0,
        b1,
        b2,
        excluded_dates=holdout,
    )
    return (
        all_rows.with_columns(pl.lit("REUSED_25").alias("source_cohort")),
        common.with_columns(pl.lit("REUSED_25").alias("source_cohort")),
    )


def _new_components(
    origins_source: pl.DataFrame,
    bars: pl.DataFrame,
    b1_source: pl.DataFrame,
    event_root: Path,
    session_hashes: Mapping[str, str],
    holdout: frozenset[str],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    origins, b0 = _new_origins_and_b0(origins_source, bars)
    b1 = _standardize_b1(b1_source, origins, retained=False)
    b2 = _new_b2(origins, b0, event_root, session_hashes)
    all_rows, common = build_common_panel(
        origins,
        b0,
        b1,
        b2,
        excluded_dates=holdout,
    )
    return (
        all_rows.with_columns(pl.lit("ACQUIRED_55").alias("source_cohort")),
        common.with_columns(pl.lit("ACQUIRED_55").alias("source_cohort")),
    )


def select_quality_assets(
    frame: pl.DataFrame,
    *,
    required_sessions: int = 80,
) -> dict[str, Any]:
    """Freeze four to six assets using source quality and PIT coverage only.

    Parameters
    ----------
    frame:
        All nominal development origins before complete-case filtering.
    required_sessions:
        Exact session count each candidate must cover.

    Returns
    -------
    dict[str, Any]
        Target-blind coverage diagnostics and selected asset identifiers.

    Raises
    ------
    ValueError
        If required columns are missing or fewer than four candidates pass.
    """
    required = {
        "asset",
        "session_date",
        "b0_session_minute",
        "b0_spot",
        "b0_available_at_utc",
        "forecast_origin_utc",
        "b1q_atm_iv",
        "b1a_complete",
        "b1q_pit_evidence_valid",
        "b1q_quote_not_after_origin",
        *B2_FEATURE_NAMES,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"PHASE5_QUALITY_COLUMNS_MISSING:{','.join(missing)}")
    assessed = frame.with_columns(
        pl.when(pl.col("b0_session_minute") < 130)
        .then(pl.lit("first"))
        .when(pl.col("b0_session_minute") < 260)
        .then(pl.lit("middle"))
        .otherwise(pl.lit("last"))
        .alias("session_tercile"),
        (
            pl.col("b0_spot").cast(pl.Float64).is_finite()
            & (pl.col("b0_spot") > 0)
            & pl.col("b0_available_at_utc").is_not_null()
            & (pl.col("b0_available_at_utc") <= pl.col("forecast_origin_utc"))
        )
        .fill_null(False)
        .alias("_b0_source_valid"),
        (
            pl.col("b1a_complete").fill_null(False)
            & pl.col("b1q_atm_iv").cast(pl.Float64).is_finite()
            & (pl.col("b1q_atm_iv") > 0)
            & pl.col("b1q_pit_evidence_valid").fill_null(False)
            & pl.col("b1q_quote_not_after_origin").fill_null(False)
        )
        .fill_null(False)
        .alias("_b1_source_valid"),
        pl.all_horizontal(
            [
                pl.col(name).cast(pl.Float64).is_finite().fill_null(False)
                for name in B2_FEATURE_NAMES
            ]
        ).alias("_b2_source_valid"),
    )
    by_segment = (
        assessed.group_by(["asset", "session_tercile"])
        .agg(
            pl.len().alias("origins"),
            pl.col("_b1_source_valid").mean().alias("b1a_coverage"),
        )
        .sort(["asset", "session_tercile"])
    )
    by_asset = (
        assessed.group_by("asset")
        .agg(
            pl.len().alias("origins"),
            pl.col("session_date").n_unique().alias("sessions"),
            pl.col("_b0_source_valid").mean().alias("b0_source_coverage"),
            pl.col("_b1_source_valid").mean().alias("b1a_coverage"),
            pl.col("_b2_source_valid").mean().alias("b2_source_coverage"),
        )
        .join(
            by_segment.group_by("asset").agg(
                pl.col("b1a_coverage").min().alias("minimum_tercile_b1a_coverage")
            ),
            on="asset",
            how="left",
        )
        .with_columns(
            (
                (pl.col("sessions") == required_sessions)
                & (pl.col("b0_source_coverage") == 1.0)
                & (pl.col("b2_source_coverage") == 1.0)
                & (pl.col("b1a_coverage") >= 0.50)
                & (pl.col("minimum_tercile_b1a_coverage") >= 0.40)
            ).alias("quality_pass")
        )
    )
    ranked = by_asset.filter(pl.col("quality_pass")).sort(
        ["b1a_coverage", "minimum_tercile_b1a_coverage", "asset"],
        descending=[True, True, False],
    )
    if ranked.height < 4:
        raise ValueError("PHASE5_FEWER_THAN_FOUR_QUALITY_ASSETS")
    selected = sorted(ranked.head(6)["asset"].to_list())
    return {
        "status": "PASS",
        "selection_uses_predictive_outcomes": False,
        "criteria": {
            "required_sessions": required_sessions,
            "b0_source_coverage": 1.0,
            "b2_source_coverage": 1.0,
            "minimum_asset_b1a_coverage": 0.50,
            "minimum_session_tercile_b1a_coverage": 0.40,
            "retained_count_min": 4,
            "retained_count_max": 6,
        },
        "selected_assets": selected,
        "ranking": ranked.to_dicts(),
        "by_asset": by_asset.sort("asset").to_dicts(),
        "by_session_tercile": by_segment.to_dicts(),
    }


def main(config: PanelBuildConfig = DEFAULT_CONFIG) -> None:
    """Build, validate and persist the development-only common panel."""
    sessions = _read_json(config.session_manifest)
    reused = _read_json(config.reused_manifest)
    full_tape = _read_json(config.full_tape_manifest)
    if (
        full_tape.get("status") != "PASS"
        or full_tape.get("session_count") != 55
        or full_tape.get("secret_values_emitted") is not False
        or full_tape.get("personal_paths_emitted") is not False
    ):
        raise ValueError("PHASE5_FULL_TAPE_ACQUISITION_INCOMPLETE")
    full_tape_rows = full_tape.get("sessions")
    if not isinstance(full_tape_rows, list) or not all(
        isinstance(row, dict) and row.get("status") == "PASS"
        for row in full_tape_rows
    ):
        raise ValueError("PHASE5_FULL_TAPE_SESSION_FAILURE")
    acquired = sorted(str(row["session_date"]) for row in full_tape_rows)
    source_hashes = {
        str(row["session_date"]): str(row["sha256"]) for row in full_tape_rows
    }
    reconciliation = reconcile_development_sources(sessions, reused, acquired)
    holdout = frozenset(str(day) for day in sessions["holdout"])

    retained = pl.read_parquet(config.retained_matrix)
    retained_dates = sorted(retained["session_date"].unique().to_list())
    if retained_dates != sorted(reused["sessions"]) or retained.height != 14_200:
        raise ValueError("PHASE5_RETAINED_MATRIX_SESSION_MISMATCH")

    origins_path = config.new_fmp_root / "b2_calibration_origins.parquet"
    bars_path = config.new_fmp_root / "underlying_1min_20d.parquet"
    fmp_manifest_path = config.new_fmp_root / "fmp_20d_manifest.json"
    b1_path = config.new_b1_root / "b1_origin_matrix_20d.parquet"
    b1_attempts_path = config.new_b1_root / "b1_iv_attempts_20d.parquet"
    b1_summary_path = config.new_b1_root / "b1_coverage_20d.json"
    fmp_manifest = _read_json(fmp_manifest_path)
    if (
        fmp_manifest.get("status") != "PASS"
        or fmp_manifest.get("secret_values_emitted") is not False
    ):
        raise ValueError("PHASE5_FMP_SOURCE_INVALID")
    b1_summary = _read_json(b1_summary_path)
    if (
        b1_summary.get("status") != "PASS_B1Q_20_SESSION_RECOMPUTATION"
        or b1_summary.get("secret_values_emitted") is not False
        or any(b1_summary.get("pit_invariants", {}).values())
        or not all(b1_summary.get("nested_invariants", {}).values())
    ):
        raise ValueError("PHASE5_B1Q_SOURCE_INVALID")
    b1_attempt_ledger = _validate_b1_attempt_ledger(
        b1_attempts_path,
        b1_summary,
    )

    new_origins_source = pl.read_parquet(origins_path)
    if (
        new_origins_source.height != 31_240
        or sorted(new_origins_source["session_date"].unique().to_list()) != acquired
    ):
        raise ValueError("PHASE5_FMP_ORIGIN_GRID_INVALID")
    bars = pl.read_parquet(bars_path)
    b1_source = pl.read_parquet(b1_path)

    retained_all, retained_common = _retained_components(retained, holdout)
    new_all, new_common = _new_components(
        new_origins_source,
        bars,
        b1_source,
        config.event_root,
        source_hashes,
        holdout,
    )
    all_rows = pl.concat(
        [retained_all, new_all],
        how="diagonal_relaxed",
    ).sort("origin_id")
    common = pl.concat(
        [retained_common, new_common],
        how="diagonal_relaxed",
    ).sort("origin_id")
    if (
        all_rows.height != 45_440
        or all_rows["origin_id"].n_unique() != all_rows.height
        or all_rows["session_date"].n_unique() != 80
        or set(all_rows["session_date"].to_list()) & holdout
        or any(
            row["len"] != 5_680
            for row in all_rows.group_by("asset").len().to_dicts()
        )
    ):
        raise ValueError("PHASE5_DEVELOPMENT_PANEL_SHAPE_INVALID")

    quality = select_quality_assets(all_rows)
    quality.update(
        {
            "nominal_origins": all_rows.height,
            "common_complete_origins": common.height,
            "target_sha256_all": target_sha256(all_rows),
            "target_sha256_common": target_sha256(common),
            "future_b0_rows": all_rows.filter(
                pl.col("b0_available_at_utc") > pl.col("forecast_origin_utc")
            ).height,
            "future_b2_rows": all_rows.filter(
                pl.col("b2_max_operational_time").is_not_null()
                & (
                    pl.col("b2_max_operational_time")
                    > pl.col("b2_window_end")
                )
            ).height,
            "duplicate_origins": all_rows.height
            - all_rows["origin_id"].n_unique(),
            "holdout_overlap": sorted(
                set(all_rows["session_date"].to_list()) & holdout
            ),
        }
    )
    if quality["future_b0_rows"] or quality["future_b2_rows"]:
        raise ValueError("PHASE5_DEVELOPMENT_PANEL_PIT_FAILURE")

    config.output_root.mkdir(parents=True, exist_ok=True)
    all_path = config.output_root / "development_all_origins_80d.parquet"
    common_path = config.output_root / "common_development_80d.parquet"
    all_rows.write_parquet(all_path, compression="zstd")
    common.write_parquet(common_path, compression="zstd")
    _write_json(
        config.output_root / "development_panel_quality.json",
        quality,
    )

    source_manifest: dict[str, Any] = {
        **reconciliation,
        "schema_version": "phase5-development-sources-1.0",
        "input_hashes": {
            "study_sessions_90.json": _sha256_file(config.session_manifest),
            "reused_25_session_manifest.json": _sha256_file(
                config.reused_manifest
            ),
            "origin_matrix_25d.parquet": _sha256_file(config.retained_matrix),
            "full_tape_batch_manifest.json": _sha256_file(
                config.full_tape_manifest
            ),
            "fmp_origins_55d.parquet": _sha256_file(origins_path),
            "fmp_bars_55d.parquet": _sha256_file(bars_path),
            "b1q_origins_55d.parquet": _sha256_file(b1_path),
            "b1q_iv_attempts_55d.parquet": _sha256_file(b1_attempts_path),
        },
        "outputs": {
            "development_all_origins_80d.parquet": _sha256_file(all_path),
            "common_development_80d.parquet": _sha256_file(common_path),
        },
        "nominal_origin_count": all_rows.height,
        "common_origin_count": common.height,
        "target_sha256_all": quality["target_sha256_all"],
        "target_sha256_common": quality["target_sha256_common"],
        "b1_attempt_ledger": b1_attempt_ledger,
        "selected_assets": quality["selected_assets"],
        "holdout_reads": 0,
    }
    source_manifest["manifest_sha256"] = canonical_sha256(source_manifest)
    _write_json(
        config.output_root / "development_source_manifest_80d.json",
        source_manifest,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "nominal_origins": all_rows.height,
                "common_origins": common.height,
                "selected_assets": quality["selected_assets"],
                "holdout_reads": 0,
                "secret_values_emitted": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
