"""Block 3 - Gate 2: build and compare candidate targets across horizons.

Builds, in discovery and validation only, the forward realized measures
``RV_h, BV_h, J_h, C_h, RQ_h, RS+_h, RS-_h`` for ``h`` in {5, 15, 30, 60, 120} on a common
origin grid, then ranks the candidate targets by

* their own measurement noise (Barndorff-Nielsen-Shephard relative standard error),
* their persistence, and
* how predictable they are from underlying history alone.

Nothing here touches option data or any sealed cohort.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.metrics import qlike_losses
from mds650.rp2.realized import (
    HORIZONS,
    backward_rv,
    forward_measures,
    log_returns,
    relative_measurement_noise,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block3_target"
SESSION_MINUTES = 390
MARKET_TZ = "America/New_York"
SESSION_OPEN_MINUTE = 9 * 60 + 30
MAX_HORIZON = max(HORIZONS)
ORIGIN_STEP = 5
VARIANCE_FLOOR = 1e-12

BAR_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("gate7_c6", "D", "data/fmp/gate7/underlying_1min_c6.parquet"),
    ("gate8_c4c", "D", "data/fmp/gate8_c4c/underlying_1min_c4c.parquet"),
    ("phase6_180d", "D", "phase6/data/fmp/underlying_1min_180d.parquet"),
    ("gate3_dev80", "V", "data/fmp/gate3/underlying_1min_dev80.parquet"),
)


def _normalise(frame: pl.DataFrame) -> pl.DataFrame:
    """Reduce either on-disk bar schema to ``asset, session_date, minute, close``."""

    timestamp = "bar_start_utc" if "bar_start_utc" in frame.columns else "bar_timestamp_raw_utc"
    # Session minutes are measured from the 09:30 New York open, not from a fixed UTC
    # hour: the UTC open shifts by an hour across daylight saving, which would otherwise
    # silently truncate every winter session.
    out = frame.select(
        pl.col("asset"),
        pl.col(timestamp).dt.convert_time_zone(MARKET_TZ).alias("bar_ny"),
        pl.col("close").cast(pl.Float64),
    ).with_columns(pl.col("bar_ny").dt.date().alias("session_date"))
    return out.with_columns(
        (
            pl.col("bar_ny").dt.hour().cast(pl.Int64) * 60
            + pl.col("bar_ny").dt.minute().cast(pl.Int64)
            - SESSION_OPEN_MINUTE
        ).alias("minute")
    ).filter(pl.col("minute").is_between(0, SESSION_MINUTES - 1))


def load_bars(data_root: Path) -> pl.DataFrame:
    """Concatenate every available one-minute bar store with its partition role."""

    frames: list[pl.DataFrame] = []
    for name, role, relative in BAR_SOURCES:
        path = data_root / relative
        if not path.is_file():
            continue
        frame = _normalise(pl.read_parquet(path))
        frames.append(frame.with_columns(source=pl.lit(name), role=pl.lit(role)))
    if not frames:
        raise SystemExit("RP2_BLOCK3_NO_BARS")
    return pl.concat(frames, how="vertical")


def _session_closes(minutes: npt.NDArray[np.int64], closes: npt.NDArray[np.float64]) -> tuple[
    npt.NDArray[np.float64], float
]:
    """Reindex one session onto the full minute grid, forward-filling absent minutes."""

    grid = np.full(SESSION_MINUTES, np.nan, dtype=np.float64)
    grid[minutes] = closes
    filled = np.isnan(grid)
    if filled[0]:
        first = int(np.argmin(filled))
        grid[:first] = grid[first]
    indices = np.where(~np.isnan(grid), np.arange(SESSION_MINUTES), 0)
    np.maximum.accumulate(indices, out=indices)
    return grid[indices], float(filled.mean())


def build_panel(
    bars: pl.DataFrame, *, max_fill_share: float
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Compute forward and backward realized measures on the common origin grid."""

    origins = np.arange(MAX_HORIZON, SESSION_MINUTES - MAX_HORIZON, ORIGIN_STEP, dtype=np.int64)
    rows: list[pl.DataFrame] = []
    counters = {"sessions_seen": 0, "sessions_dropped_fill": 0, "sessions_dropped_short": 0}
    previous_day_rv: dict[str, float] = {}
    ordered = bars.sort(["asset", "session_date", "minute"])
    for (asset, session_date, role, source), group in ordered.group_by(
        ["asset", "session_date", "role", "source"], maintain_order=True
    ):
        counters["sessions_seen"] += 1
        minutes = group["minute"].to_numpy().astype(np.int64)
        closes = group["close"].to_numpy().astype(np.float64)
        if minutes.size < 2 or closes.min() <= 0.0:
            counters["sessions_dropped_short"] += 1
            continue
        grid, fill_share = _session_closes(minutes, closes)
        if fill_share > max_fill_share or not np.isfinite(grid).all():
            counters["sessions_dropped_fill"] += 1
            continue
        returns = log_returns(grid)
        session_squared = np.cumsum(returns**2)
        record: dict[str, object] = {
            "asset": [str(asset)] * origins.size,
            "session_date": [str(session_date)] * origins.size,
            "role": [str(role)] * origins.size,
            "source": [str(source)] * origins.size,
            "origin_minute": origins,
            "rv_session_to_date": session_squared[origins - 1],
            "rv_prev_day": np.full(origins.size, previous_day_rv.get(str(asset), np.nan)),
        }
        for horizon in HORIZONS:
            measures = forward_measures(returns, origins, horizon)
            for name, values in measures.as_dict().items():
                record[f"{name}_{horizon}"] = values
            record[f"rv_back_{horizon}"] = backward_rv(returns, origins, horizon)
            record[f"noise_{horizon}"] = relative_measurement_noise(
                measures.rv, measures.quarticity, horizon
            )
        rows.append(pl.DataFrame(record))
        previous_day_rv[str(asset)] = float(session_squared[-1])
    if not rows:
        raise SystemExit("RP2_BLOCK3_EMPTY_PANEL")
    return pl.concat(rows, how="vertical"), counters


def _fit_predict(
    design: npt.NDArray[np.float64],
    response: npt.NDArray[np.float64],
    train: npt.NDArray[np.bool_],
) -> npt.NDArray[np.float64]:
    coefficients, *_ = np.linalg.lstsq(design[train], response[train], rcond=None)
    return design @ coefficients


def evaluate_target(
    panel: pl.DataFrame, column: str, horizon: int, *, train_share: float, role: str = "D"
) -> dict[str, float]:
    """Persistence and out-of-sample predictability of one candidate target in one role."""

    discovery = panel.filter(pl.col("role") == role)
    target = discovery[column].to_numpy().astype(np.float64)
    positive = target > 0.0
    sessions = discovery["session_date"].to_numpy()
    unique_sessions = np.unique(sessions)
    split = unique_sessions[int(len(unique_sessions) * train_share)]
    train = (sessions < split) & positive
    test = (sessions >= split) & positive
    if train.sum() < 100 or test.sum() < 100:
        return {"status": float("nan")}

    response = np.log(np.maximum(target, VARIANCE_FLOOR))
    regressors = [
        np.log(np.maximum(discovery[f"rv_back_{horizon}"].to_numpy(), VARIANCE_FLOOR)),
        np.log(np.maximum(discovery["rv_session_to_date"].to_numpy(), VARIANCE_FLOOR)),
        np.log(np.maximum(discovery["rv_prev_day"].to_numpy(), VARIANCE_FLOOR)),
    ]
    design = np.column_stack([np.ones(target.size), *regressors])
    usable = np.isfinite(design).all(axis=1) & np.isfinite(response)
    train &= usable
    test &= usable
    fitted = _fit_predict(design, np.where(usable, response, 0.0), train)

    residual = response[test] - fitted[test]
    total = response[test] - response[train].mean()
    r2 = 1.0 - float(residual @ residual) / float(total @ total)
    smearing = float(np.exp(0.5 * np.var(response[train] - fitted[train])))
    forecast = np.exp(fitted[test]) * smearing
    qlike = float(np.mean(qlike_losses(target[test], forecast)))

    lagged = np.corrcoef(response[test][:-1], response[test][1:])[0, 1]
    return {
        "train_rows": float(train.sum()),
        "test_rows": float(test.sum()),
        "positive_share": float(positive.mean()),
        "oos_log_r2": r2,
        "oos_qlike": qlike,
        "autocorr_lag1_log": float(lagged),
        "median_relative_noise": float(
            np.median(discovery[f"noise_{horizon}"].to_numpy()[positive])
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-fill-share", type=float, default=0.05)
    parser.add_argument("--train-share", type=float, default=0.6)
    args = parser.parse_args(argv)

    bars = load_bars(args.data_root)
    panel, counters = build_panel(bars, max_fill_share=args.max_fill_share)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(args.output_dir / "target_panel.parquet")

    candidates = ("rv", "jump", "continuous", "rs_up", "rs_down", "bv")
    comparison: dict[str, dict[str, dict[str, float]]] = {}
    validation: dict[str, dict[str, dict[str, float]]] = {}
    for horizon in HORIZONS:
        for name in candidates:
            comparison.setdefault(name, {})[str(horizon)] = evaluate_target(
                panel, f"{name}_{horizon}", horizon, train_share=args.train_share
            )
            validation.setdefault(name, {})[str(horizon)] = evaluate_target(
                panel, f"{name}_{horizon}", horizon, train_share=args.train_share, role="V"
            )

    document: dict[str, object] = {
        "block": 3,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "horizons": list(HORIZONS),
        "origin_grid": {
            "first_minute": int(MAX_HORIZON),
            "last_minute": int(SESSION_MINUTES - MAX_HORIZON - 1),
            "step_minutes": ORIGIN_STEP,
            "origins_per_session_asset": int(
                len(range(MAX_HORIZON, SESSION_MINUTES - MAX_HORIZON, ORIGIN_STEP))
            ),
        },
        "session_counters": dict(counters),
        "panel_rows": panel.height,
        "panel_sessions": int(panel["session_date"].n_unique()),
        "panel_assets": sorted(panel["asset"].unique().to_list()),
        "rows_by_role": {
            str(role): int(count)
            for role, count in zip(
                panel["role"].value_counts()["role"].to_list(),
                panel["role"].value_counts()["count"].to_list(),
                strict=True,
            )
        },
        "comparison": comparison,
        "validation_comparison": validation,
    }
    document["comparison_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (args.output_dir / "comparison.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    skip = {"comparison", "validation_comparison"}
    print(json.dumps({k: v for k, v in document.items() if k not in skip}, indent=2))
    for name, block in comparison.items():
        for label, stats in block.items():
            r2 = stats.get("oos_log_r2", float("nan"))
            noise = stats.get("median_relative_noise", float("nan"))
            v_r2 = validation[name][label].get("oos_log_r2", float("nan"))
            print(
                f"{name:<11} h={label:<4} D_oos_log_r2={r2:7.4f}  "
                f"V_oos_log_r2={v_r2:7.4f}  rel_noise={noise:7.4f}"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
