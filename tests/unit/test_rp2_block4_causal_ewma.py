"""Block 4's EWMA challenger must be a forecast, not a transform of the answer.

The producer fed `ewma_variance(np.sqrt(rv30))` — the EWMA of the square root of the very
target it was being scored against. That is not a causal baseline built from observed
returns; it is the answer, smoothed. A B1 or B2 increment measured on top of it is measured
against a benchmark that already knew the outcome.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import polars as pl

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_block4_ewma_never_receives_rv30_target_as_input() -> None:
    """The specific regression, pinned by name so it cannot come back quietly."""

    source = (REPO / "scripts" / "rp2_block4_b0_panel.py").read_text(encoding="utf-8")
    assert "ewma_variance(np.sqrt" not in source, (
        "the EWMA challenger is being built from the target it is scored against"
    )
    assert "def causal_ewma_forecasts(" in source, (
        "the challenger must be built from one-minute returns, like the GARCH one is"
    )


def _trading_sessions(count: int) -> list[date]:
    """Real XNYS sessions, so the grid builder sees the calendar it expects."""

    from mds650.rp2.bars import session_length_minutes

    out, day = [], date(2026, 1, 5)
    while len(out) < count:
        if session_length_minutes(day) > 0:
            out.append(day)
        day += timedelta(days=1)
    return out


def _bars(sessions: int = 12) -> pl.DataFrame:
    from mds650.rp2.bars import session_length_minutes

    rng = np.random.default_rng(650)
    rows = []
    for asset, scale in (("AAPL", 1e-4), ("MSFT", 1e-3)):
        for session in _trading_sessions(sessions):
            minutes = session_length_minutes(session)
            steps = rng.normal(0.0, scale, minutes)
            close = 100.0 * np.exp(np.cumsum(steps))
            rows.append(
                pl.DataFrame(
                    {
                        "asset": [asset] * minutes,
                        "session_date": [session] * minutes,
                        "minute": np.arange(minutes, dtype=np.int64),
                        "close": close,
                        "high": close * 1.001,
                        "low": close * 0.999,
                        "volume": np.full(minutes, 1000.0),
                        "role": ["D"] * minutes,
                        "source": ["synthetic"] * minutes,
                    }
                )
            )
    return pl.concat(rows, how="vertical")


def test_the_ewma_challenger_ignores_the_target_column_entirely() -> None:
    """Randomise rv30 and the forecast must not move by one bit."""

    block4 = _load("rp2_block4_b0_panel")
    bars = _bars()
    panel, _ = block4.build_b0_panel(bars, max_fill_share=0.05)

    rng = np.random.default_rng(1)
    scrambled = panel.with_columns(rv30=pl.Series(rng.lognormal(-9.0, 1.0, panel.height)))

    left = block4.causal_ewma_forecasts(bars, panel, role="D")
    right = block4.causal_ewma_forecasts(bars, scrambled, role="D")
    assert np.array_equal(left, right, equal_nan=True)
    assert np.isfinite(left).any(), "the challenger produced no forecast at all"


def test_the_ewma_challenger_carries_state_across_sessions_per_asset() -> None:
    """One name's volatility may not seed another's, and a session break may not reset."""

    block4 = _load("rp2_block4_b0_panel")
    bars = _bars()
    panel, _ = block4.build_b0_panel(bars, max_fill_share=0.05)
    forecasts = block4.causal_ewma_forecasts(bars, panel, role="D")

    frame = panel.filter(pl.col("role") == "D").sort(
        ["session_date", "asset", "origin_minute"]
    )
    assets = frame["asset"].to_numpy()
    finite = np.isfinite(forecasts)
    # The second session of each asset already has a state, so it forecasts from its
    # first origin rather than warming up again.
    first_session = str(np.unique(frame["session_date"].to_numpy())[0])
    later = frame["session_date"].to_numpy() != first_session
    assert finite[later].all(), "a session break reset the recursion"

    # A quiet name and a loud one must not converge on one level.
    quiet = float(np.nanmedian(forecasts[(assets == "AAPL") & finite]))
    loud = float(np.nanmedian(forecasts[(assets == "MSFT") & finite]))
    assert loud > 3.0 * quiet, "the two assets share one state"
