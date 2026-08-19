"""Block 4 - Gate 3: build a B0 that is genuinely hard to beat, and prove it.

Constructs the full underlying-only information set at every forecast origin - HAR and
HARQ components, semivariances, a jump proxy, range-based liquidity, volume and dollar
volume, SPY/QQQ market controls, intraday seasonality, day of week and open/close
proximity - then compares it against the five challengers the program names: persistence,
intraday mean, EWMA, simple HAR and an intraday GARCH(1,1).

Discovery and validation only.  No option data, no sealed cohort.
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
from mds650.rp2.bars import FULL_SESSION_MINUTES, build_session_grid, load_bar_sources
from mds650.rp2.baseline import (
    EWMA_LAMBDA,
    VARIANCE_FLOOR,
    causal_ewma_horizon_variance,
    fit_garch11,
    mincer_zarnowitz,
    seasonality_index,
    smearing_factor,
)
from mds650.rp2.realized import backward_rv, forward_measures, log_returns

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block4_b0"
TARGET_HORIZON = 30
FIRST_ORIGIN = 30
LAST_ORIGIN = FULL_SESSION_MINUTES - TARGET_HORIZON
ORIGIN_STEP = 5
MARKET_ASSETS = ("SPY", "QQQ")
TARGET_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
WEEK_SESSIONS = 5
SEASONALITY_BUCKETS = FULL_SESSION_MINUTES // ORIGIN_STEP + 1

type FloatArray = npt.NDArray[np.float64]


def _log(values: FloatArray) -> FloatArray:
    return np.log(np.maximum(values, VARIANCE_FLOOR))


def _parkinson(
    high: FloatArray, low: FloatArray, origins: npt.NDArray[np.int64], window: int
) -> FloatArray:
    ratio = np.log(np.maximum(high, VARIANCE_FLOOR) / np.maximum(low, VARIANCE_FLOOR)) ** 2
    prefix = np.concatenate([[0.0], np.cumsum(ratio)])
    window_sum = prefix[origins + 1] - prefix[origins + 1 - window]
    return np.asarray(window_sum / (4.0 * np.log(2.0) * window), dtype=np.float64)


def _window_sum(values: FloatArray, origins: npt.NDArray[np.int64], window: int) -> FloatArray:
    prefix = np.concatenate([[0.0], np.cumsum(values)])
    return np.asarray(prefix[origins + 1] - prefix[origins + 1 - window], dtype=np.float64)


def session_origins(minutes: int) -> npt.NDArray[np.int64]:
    """Five-minute origins that fit inside a session of ``minutes`` minutes.

    Every origin must leave a full forecast horizon before the close, so a 210-minute
    early close yields origins up to 175 rather than the full-session 355. Sizing them
    from a module-level constant instead indexes past the end of a short session's grid.
    """

    last = minutes - TARGET_HORIZON
    if last <= FIRST_ORIGIN:
        return np.empty(0, dtype=np.int64)
    return np.arange(FIRST_ORIGIN, last, ORIGIN_STEP, dtype=np.int64)


def first_valid_minute(valid: npt.NDArray[np.bool_]) -> int:
    """First minute with an observation at or before it, or the grid length if none.

    The grid marks unobserved opening minutes invalid rather than carrying a later price
    backwards into them, so their close is NaN. NaN fails every comparison, which is why a
    `close.min() <= 0` guard cannot see them: without this the whole session aborts on a
    single absent opening bar.
    """

    present = np.flatnonzero(valid)
    return int(present[0]) if present.size else int(valid.size)


def build_market_controls(bars: pl.DataFrame) -> pl.DataFrame:
    """Session-level SPY/QQQ return and realized variance at every origin minute."""

    rows: list[pl.DataFrame] = []
    market = bars.filter(pl.col("asset").is_in(MARKET_ASSETS))
    for (asset, session_date), group in market.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        grid = build_session_grid(group, session=session_date)
        if grid.fill_share > 0.05:
            continue
        usable = first_valid_minute(grid.valid)
        origins = session_origins(grid.minutes)
        origins = origins[origins >= usable + TARGET_HORIZON]
        close = grid.close[usable:]
        if origins.size == 0 or not np.isfinite(close).all() or close.min() <= 0.0:
            continue
        returns = log_returns(close)
        prefix = np.concatenate([[0.0], np.cumsum(returns)])
        local = origins - usable
        rows.append(
            pl.DataFrame(
                {
                    "session_date": [str(session_date)] * origins.size,
                    "origin_minute": origins,
                    f"{asset!s}_rv_30": backward_rv(returns, local, TARGET_HORIZON),
                    f"{asset!s}_ret_30": prefix[local] - prefix[local - TARGET_HORIZON],
                }
            )
        )
    if not rows:
        return pl.DataFrame({"session_date": [], "origin_minute": []})
    merged: pl.DataFrame | None = None
    for asset in MARKET_ASSETS:
        subset = [frame for frame in rows if f"{asset}_rv_30" in frame.columns]
        if not subset:
            continue
        stacked = pl.concat(subset, how="vertical")
        merged = (
            stacked
            if merged is None
            else merged.join(
                stacked, on=["session_date", "origin_minute"], how="full", coalesce=True
            )
        )
    return merged if merged is not None else pl.DataFrame()


def build_b0_panel(
    bars: pl.DataFrame, *, max_fill_share: float
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Target-blind underlying feature panel at every five-minute origin."""

    counters = {"session_assets_seen": 0, "dropped_fill": 0, "dropped_short_session": 0}
    history: dict[str, list[float]] = {}
    rows: list[pl.DataFrame] = []
    ordered = bars.filter(pl.col("asset").is_in(TARGET_ASSETS)).sort(
        ["asset", "session_date", "minute"]
    )
    for (asset, session_date, role, source), group in ordered.group_by(
        ["asset", "session_date", "role", "source"], maintain_order=True
    ):
        counters["session_assets_seen"] += 1
        grid = build_session_grid(group, session=session_date)
        if grid.fill_share > max_fill_share:
            counters["dropped_fill"] += 1
            continue
        usable = first_valid_minute(grid.valid)
        origins = session_origins(grid.minutes)
        # Every window reaches a full horizon back from its origin, so an origin closer to
        # the first observed minute than that horizon would read the fill, not the market.
        origins = origins[origins >= usable + TARGET_HORIZON]
        close = grid.close[usable:]
        if origins.size == 0:
            counters["dropped_short_session"] += 1
            continue
        if not np.isfinite(close).all() or close.min() <= 0.0:
            counters["dropped_fill"] += 1
            continue
        local = origins - usable
        returns = log_returns(close)
        cumulative_return = np.concatenate([[0.0], np.cumsum(returns)])
        session_squared = np.cumsum(returns**2)
        past = history.setdefault(str(asset), [])
        prev_day = past[-1] if past else float("nan")
        week = float(np.mean(past[-WEEK_SESSIONS:])) if len(past) >= WEEK_SESSIONS else float("nan")

        forward = forward_measures(returns, local, TARGET_HORIZON)
        back30 = forward_measures(returns - 0.0, local - TARGET_HORIZON, TARGET_HORIZON)
        record: dict[str, object] = {
            "asset": [str(asset)] * origins.size,
            "session_date": [str(session_date)] * origins.size,
            "role": [str(role)] * origins.size,
            "source": [str(source)] * origins.size,
            "origin_minute": origins,
            "rv30": forward.rv,
            "jump30": forward.jump,
            "rv_back_5": backward_rv(returns, local, 5),
            "rv_back_15": backward_rv(returns, local, 15),
            "rv_back_30": back30.rv,
            "rq_back_30": back30.quarticity,
            "rs_up_back_30": back30.semivariance_up,
            "rs_down_back_30": back30.semivariance_down,
            "jump_back_30": back30.jump,
            "rv_session_to_date": session_squared[local - 1],
            "rv_prev_day": np.full(origins.size, prev_day),
            "rv_week": np.full(origins.size, week),
            "ret_5": cumulative_return[local] - cumulative_return[local - 5],
            "ret_30": cumulative_return[local] - cumulative_return[local - TARGET_HORIZON],
            "parkinson_30": _parkinson(
                grid.high[usable:], grid.low[usable:], local, TARGET_HORIZON
            ),
            "volume_30": _window_sum(grid.volume[usable:], local - 1, TARGET_HORIZON),
            "dollar_volume_30": _window_sum(
                grid.volume[usable:] * close, local - 1, TARGET_HORIZON
            ),
            "minutes_since_open": origins.astype(np.float64),
            # Against the session's own close, not a fixed 390-minute one.
            "minutes_to_close": (grid.minutes - origins).astype(np.float64),
            "minute_bucket": (origins // ORIGIN_STEP).astype(np.int64),
        }
        rows.append(pl.DataFrame(record))
        past.append(float(session_squared[-1]))
    if not rows:
        raise SystemExit("RP2_BLOCK4_EMPTY_PANEL")
    panel = pl.concat(rows, how="vertical")
    panel = panel.with_columns(
        pl.col("session_date").str.to_date().dt.weekday().alias("day_of_week")
    )
    return panel, counters


def _design(panel: pl.DataFrame, columns: Sequence[str], extra: list[FloatArray]) -> FloatArray:
    blocks: list[FloatArray] = [np.ones(panel.height, dtype=np.float64)]
    for name in columns:
        blocks.append(np.asarray(panel[name].to_numpy(), dtype=np.float64))
    blocks.extend(extra)
    return np.column_stack(blocks)


def _fit_evaluate(
    design: FloatArray,
    response: FloatArray,
    target: FloatArray,
    train: npt.NDArray[np.bool_],
    test: npt.NDArray[np.bool_],
) -> dict[str, float]:
    coefficients, *_ = np.linalg.lstsq(design[train], response[train], rcond=None)
    fitted = design @ coefficients
    factor = smearing_factor(response[train] - fitted[train])
    forecast = np.exp(fitted) * factor
    residual = response[test] - fitted[test]
    centred = response[test] - response[train].mean()
    calibration = mincer_zarnowitz(target[test], forecast[test])
    return {
        "qlike": float(np.mean(qlike_losses(target[test], forecast[test]))),
        "log_r2": 1.0 - float(residual @ residual) / float(centred @ centred),
        "calibration_intercept": calibration.intercept,
        "calibration_slope": calibration.slope,
        "calibration_r2": calibration.r_squared,
        "well_calibrated": float(calibration.well_calibrated),
    }


def _constant_forecast_metrics(
    target: FloatArray,
    forecast: FloatArray,
    test: npt.NDArray[np.bool_],
    response: FloatArray,
    train: npt.NDArray[np.bool_],
) -> dict[str, float]:
    safe = np.maximum(forecast, VARIANCE_FLOOR)
    calibration = mincer_zarnowitz(target[test], safe[test])
    residual = response[test] - np.log(safe[test])
    centred = response[test] - response[train].mean()
    return {
        "qlike": float(np.mean(qlike_losses(target[test], safe[test]))),
        "log_r2": 1.0 - float(residual @ residual) / float(centred @ centred),
        "calibration_intercept": calibration.intercept,
        "calibration_slope": calibration.slope,
        "calibration_r2": calibration.r_squared,
        "well_calibrated": float(calibration.well_calibrated),
    }


def evaluate_role(
    panel: pl.DataFrame,
    *,
    role: str,
    train_share: float,
    garch: dict[str, float],
    ewma: FloatArray,
) -> dict[str, dict[str, float]]:
    """Fit every challenger and B0 on the first ``train_share`` of one role's sessions."""

    frame = panel.filter(pl.col("role") == role).sort(["session_date", "asset", "origin_minute"])
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    sessions = frame["session_date"].to_numpy()
    unique = np.unique(sessions)
    split = unique[int(len(unique) * train_share)]
    response = _log(target)
    usable = np.isfinite(response) & (target > 0.0)
    for name in ("rv_back_30", "rv_prev_day", "rv_week", "rv_session_to_date"):
        usable &= np.isfinite(frame[name].to_numpy())
    train = (sessions < split) & usable
    test = (sessions >= split) & usable

    log_back30 = _log(np.asarray(frame["rv_back_30"].to_numpy(), dtype=np.float64))
    log_back5 = _log(np.asarray(frame["rv_back_5"].to_numpy(), dtype=np.float64))
    log_back15 = _log(np.asarray(frame["rv_back_15"].to_numpy(), dtype=np.float64))
    log_session = _log(np.asarray(frame["rv_session_to_date"].to_numpy(), dtype=np.float64))
    log_prev = _log(np.asarray(frame["rv_prev_day"].to_numpy(), dtype=np.float64))
    log_week = _log(np.asarray(frame["rv_week"].to_numpy(), dtype=np.float64))
    buckets = np.asarray(frame["minute_bucket"].to_numpy(), dtype=np.int64)

    results: dict[str, dict[str, float]] = {}

    # Challenger 1 - persistence: the last 30-minute realized variance, unscaled.
    results["persistence"] = _constant_forecast_metrics(
        target, np.asarray(frame["rv_back_30"].to_numpy(), dtype=np.float64), test, response, train
    )
    # Challenger 2 - intraday mean: training mean log variance by intraday bucket.
    season = seasonality_index(buckets, response, train, buckets=SEASONALITY_BUCKETS)
    intraday_mean = np.exp(response[train].mean() + season) * smearing_factor(
        response[train] - (response[train].mean() + season[train])
    )
    results["intraday_mean"] = _constant_forecast_metrics(
        target, intraday_mean, test, response, train
    )
    # Challenger 3 - causal EWMA of one-minute returns, scaled to the horizon. Built by
    # `causal_ewma_forecasts` from the bars, never from the target.
    ewma_scored = np.isfinite(ewma)
    results["ewma"] = _constant_forecast_metrics(
        target,
        np.where(ewma_scored, ewma, VARIANCE_FLOOR),
        test & ewma_scored,
        response,
        train & ewma_scored,
    )
    results["ewma"]["scored_rows"] = float(np.sum(test & ewma_scored))
    # Challenger 4 - simple HAR: three own-history lags.
    results["har_simple"] = _fit_evaluate(
        np.column_stack([np.ones(frame.height), log_back30, log_session, log_prev]),
        response,
        target,
        train,
        test,
    )
    # Challenger 5 - intraday GARCH(1,1) fitted on one-minute returns.
    results["garch11_intraday"] = dict(garch)

    # B0 - the full underlying information set.
    b0_columns = (
        "ret_5",
        "ret_30",
        "minutes_since_open",
        "minutes_to_close",
        "day_of_week",
    )
    extras: list[FloatArray] = [
        log_back5,
        log_back15,
        log_back30,
        log_session,
        log_prev,
        log_week,
        _log(np.asarray(frame["rq_back_30"].to_numpy(), dtype=np.float64)),
        np.sqrt(np.maximum(frame["rq_back_30"].to_numpy(), 0.0)) * log_back30,
        _log(np.asarray(frame["rs_up_back_30"].to_numpy(), dtype=np.float64)),
        _log(np.asarray(frame["rs_down_back_30"].to_numpy(), dtype=np.float64)),
        _log(np.asarray(frame["jump_back_30"].to_numpy(), dtype=np.float64)),
        _log(np.asarray(frame["parkinson_30"].to_numpy(), dtype=np.float64)),
        _log(np.asarray(frame["volume_30"].to_numpy(), dtype=np.float64)),
        _log(np.asarray(frame["dollar_volume_30"].to_numpy(), dtype=np.float64)),
        season,
    ]
    core_design = _design(frame, b0_columns, extras)
    core_finite = np.isfinite(core_design).all(axis=1)
    results["b0_core"] = _fit_evaluate(
        np.where(core_finite[:, None], core_design, 0.0),
        response,
        target,
        train & core_finite,
        test & core_finite,
    )

    # Market controls exist only where index-ETF bars were collected; the model that uses
    # them is fitted and scored on that subset alone rather than imputing the gap away.
    market_columns = [name for name in frame.columns if name.startswith(MARKET_ASSETS)]
    market_extras = list(extras)
    for name in market_columns:
        values = np.asarray(frame[name].to_numpy(), dtype=np.float64)
        market_extras.append(_log(values) if name.endswith("_rv_30") else values)
    market_design = _design(frame, b0_columns, market_extras)
    market_finite = np.isfinite(market_design).all(axis=1)
    if (train & market_finite).sum() >= 500 and (test & market_finite).sum() >= 500:
        results["b0_market"] = _fit_evaluate(
            np.where(market_finite[:, None], market_design, 0.0),
            response,
            target,
            train & market_finite,
            test & market_finite,
        )
        # Same rows, no market controls: the like-for-like comparison.
        results["b0_core_on_market_rows"] = _fit_evaluate(
            np.where(core_finite[:, None], core_design, 0.0),
            response,
            target,
            train & market_finite,
            test & market_finite,
        )
    results["_meta"] = {
        "train_rows": float(train.sum()),
        "test_rows": float(test.sum()),
        "sessions": float(len(unique)),
        "market_control_columns": float(len(market_columns)),
        "market_control_rows": float(market_finite.sum()),
    }
    return results


def causal_ewma_forecasts(
    bars: pl.DataFrame,
    panel: pl.DataFrame,
    *,
    role: str,
    max_fill_share: float,
    decay: float = EWMA_LAMBDA,
    horizon: int = TARGET_HORIZON,
) -> FloatArray:
    """EWMA horizon-variance forecast at every origin of one role, built from bars.

    One recursion per asset, carried across session breaks in calendar order, fed only by
    observed one-minute returns. The panel is read for its origin keys and for nothing
    else — in particular not for ``rv30``, which the previous challenger consumed.

    ``max_fill_share`` must be the threshold the panel itself was built with. A stricter one
    here drops sessions the panel kept, and the challenger is then scored on fewer rows than
    every other model in the same table.
    """

    frame = panel.filter(pl.col("role") == role).sort(["session_date", "asset", "origin_minute"])
    # Every role, in calendar order. Filtering to one role first would restart each asset's
    # recursion at the partition boundary, and Validation's first origins would lose the
    # state Discovery ended on — about 0.97**30 of it at a 30-minute origin. Discovery
    # precedes Validation, so this is past information; nothing later can reach back.
    subset = bars.filter(pl.col("asset").is_in(TARGET_ASSETS))
    series: dict[tuple[str, str], FloatArray] = {}
    offsets: dict[tuple[str, str], int] = {}
    carried: dict[str, float | None] = {}
    for (asset, session_date), group in subset.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        key = (str(asset), str(session_date))
        grid = build_session_grid(group, session=session_date)
        if grid.minutes == 0 or grid.fill_share > max_fill_share:
            continue
        usable = first_valid_minute(grid.valid)
        close = grid.close[usable:]
        if close.size < 2 or not np.isfinite(close).all() or close.min() <= 0.0:
            continue
        returns = log_returns(close)
        state = carried.get(str(asset))
        levels, state = causal_ewma_horizon_variance(
            returns,
            np.arange(returns.size + 1, dtype=np.int64),
            decay=decay,
            horizon=horizon,
            initial_state=state,
        )
        carried[str(asset)] = state
        series[key] = levels
        offsets[key] = usable

    sessions = frame["session_date"].to_numpy()
    assets = frame["asset"].to_numpy()
    origins = np.asarray(frame["origin_minute"].to_numpy(), dtype=np.int64)
    out = np.full(frame.height, np.nan, dtype=np.float64)
    for index in range(frame.height):
        key = (str(assets[index]), str(sessions[index]))
        if key not in series:
            continue
        levels = series[key]
        position = int(origins[index]) - offsets.get(key, 0)
        if 0 <= position < levels.size:
            out[index] = levels[position]
    return out


def fit_intraday_garch(
    bars: pl.DataFrame,
    panel: pl.DataFrame,
    *,
    role: str,
    train_share: float,
    max_fill_share: float,
) -> dict[str, float]:
    """Fit GARCH(1,1) on training one-minute returns and score it at the origins."""

    frame = panel.filter(pl.col("role") == role).sort(["session_date", "asset", "origin_minute"])
    sessions = frame["session_date"].to_numpy()
    unique = np.unique(sessions)
    split = unique[int(len(unique) * train_share)]
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    response = _log(target)

    subset = bars.filter((pl.col("role") == role) & pl.col("asset").is_in(TARGET_ASSETS))
    training_returns: list[FloatArray] = []
    forecasts: dict[tuple[str, str], FloatArray] = {}
    offsets: dict[tuple[str, str], int] = {}
    for (asset, session_date), group in subset.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        grid = build_session_grid(group, session=session_date)
        # Same discipline as the panel: a holiday has no grid, and unobserved opening
        # minutes are NaN rather than back-filled, so the series starts where the market
        # first printed. `offsets` records that start so the origin index can be rebased.
        if grid.minutes == 0 or grid.fill_share > max_fill_share:
            continue
        usable = first_valid_minute(grid.valid)
        close = grid.close[usable:]
        if close.size < 2 or not np.isfinite(close).all() or close.min() <= 0.0:
            continue
        returns = log_returns(close)
        if str(session_date) < str(split):
            training_returns.append(returns)
        forecasts[(str(asset), str(session_date))] = returns
        offsets[(str(asset), str(session_date))] = usable
    if not training_returns:
        return {"qlike": float("nan")}
    model = fit_garch11(np.concatenate(training_returns))

    origins = np.asarray(frame["origin_minute"].to_numpy(), dtype=np.int64)
    assets = frame["asset"].to_numpy()
    predicted = np.full(frame.height, np.nan, dtype=np.float64)
    cache: dict[tuple[str, str], FloatArray] = {}
    for index in range(frame.height):
        key = (str(assets[index]), str(sessions[index]))
        series = forecasts.get(key)
        if series is None:
            continue
        filtered = cache.get(key)
        if filtered is None:
            filtered = model.filter(series)
            cache[key] = filtered
        # Iterate the recursion forward TARGET_HORIZON steps from the origin, rebased
        # onto the observed slice.
        position = int(origins[index]) - offsets.get(key, 0)
        if not 0 <= position < filtered.size:
            continue
        state = float(filtered[position])
        unconditional = model.omega / max(1.0 - model.persistence, 1e-6)
        total = 0.0
        for _step in range(TARGET_HORIZON):
            total += state
            state = unconditional + model.persistence * (state - unconditional)
        predicted[index] = total
    scored = np.isfinite(predicted) & np.isfinite(response) & (target > 0.0)
    train = (sessions < split) & scored
    test = (sessions >= split) & scored
    metrics = _constant_forecast_metrics(
        target, np.nan_to_num(predicted, nan=VARIANCE_FLOOR), test, response, train
    )
    metrics.update(
        {
            "omega": model.omega,
            "alpha": model.alpha,
            "beta": model.beta,
            "persistence": model.persistence,
        }
    )
    return metrics


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-fill-share", type=float, default=0.05)
    parser.add_argument("--train-share", type=float, default=0.6)
    args = parser.parse_args(argv)

    bars = load_bar_sources(args.data_root)
    panel, counters = build_b0_panel(bars, max_fill_share=args.max_fill_share)
    controls = build_market_controls(bars)
    if controls.height:
        panel = panel.join(controls, on=["session_date", "origin_minute"], how="left")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    panel.write_parquet(args.output_dir / "b0_panel.parquet")

    results: dict[str, dict[str, dict[str, float]]] = {}
    for role in ("D", "V"):
        garch = fit_intraday_garch(
            bars,
            panel,
            role=role,
            train_share=args.train_share,
            max_fill_share=args.max_fill_share,
        )
        ewma = causal_ewma_forecasts(
            bars, panel, role=role, max_fill_share=args.max_fill_share
        )
        results[role] = evaluate_role(
            panel, role=role, train_share=args.train_share, garch=garch, ewma=ewma
        )

    document: dict[str, object] = {
        "block": 4,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "target": "rv30",
        "origin_grid": {"first": FIRST_ORIGIN, "last": LAST_ORIGIN, "step": ORIGIN_STEP},
        "session_counters": dict(counters),
        "panel_rows": panel.height,
        "panel_columns": len(panel.columns),
        "market_control_columns": [c for c in panel.columns if c.startswith(MARKET_ASSETS)],
        "results": results,
    }
    document["b0_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (args.output_dir / "ladder.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in document.items() if k != "results"}, indent=2))
    for role, block in results.items():
        print(f"--- role {role} ---")
        for model, stats in block.items():
            if model == "_meta":
                print(f"  meta {stats}")
                continue
            print(
                f"  {model:<18} QLIKE={stats.get('qlike', float('nan')):8.5f} "
                f"logR2={stats.get('log_r2', float('nan')):7.4f} "
                f"slope={stats.get('calibration_slope', float('nan')):6.3f} "
                f"cal={bool(stats.get('well_calibrated', 0.0))}"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
