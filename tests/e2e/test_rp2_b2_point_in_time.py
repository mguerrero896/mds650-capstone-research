"""B2 needs two clocks and uses them for different things.

`executed_at` is when the trade happened at the exchange. `created_at` is when the provider
made it visible. Availability — what a forecaster could have seen — is the second. Economics
— spot, Greeks, time to expiry, interarrivals, intensity — is the first. Block 6 selected
windows on availability, correctly, and then also measured its economics on it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _source() -> str:
    return (REPO / "scripts" / "rp2_block6_flow_panel.py").read_text(encoding="utf-8")


def test_greeks_use_spot_at_executed_at() -> None:
    """A trade's Greeks are a property of the market when it printed, not when it arrived."""

    source = _source()
    assert "(executed - open_us)" in source, (
        "the spot minute is chosen on the availability clock, so a batched print is priced "
        "at the underlying level of whenever the provider got round to publishing it"
    )
    assert "(created - open_us)" not in source


def test_intensity_uses_exchange_execution_time() -> None:
    """Provider batching is not a burst of trading."""

    source = _source()
    assert "clocks.economic_seconds()" in source, (
        "the decay intensity is measured on the availability clock, so a provider flushing "
        "a backlog reads as an economic burst"
    )
    assert "(created - created[0])" not in source


def test_zero_dte_uses_fractional_time_until_expiry() -> None:
    """A contract expiring this afternoon has hours left, not a floored day."""

    source = _source()
    assert "tenor_days" not in source, "time to expiry is measured in exact years now"
    assert "time_to_expiry_years(" in source
    assert "expiry_close_us" in source, "expiry needs a timestamp, not a date"
    # The one-day floor is what made a contract with four hours left read as a full day,
    # and what collided 0DTE with 1DTE in the contract key.
    assert "expiry_day * 20_000_000" in source, "the contract key must be keyed on the expiry"
    from mds650.rp2.option_clock import SECONDS_PER_YEAR

    assert SECONDS_PER_YEAR == 365.25 * 24 * 3600


def test_the_zero_dte_features_exist() -> None:
    from mds650.rp2.panel import B2_FEATURES

    required = (
        "b2_5m_zero_dte_premium_share",
        "b2_5m_zero_dte_signed_premium",
        "b2_5m_zero_dte_trade_share",
        "b2_5m_mean_provider_latency_s",
        "b2_5m_late_arrival_share",
    )
    missing = [name for name in required if name not in B2_FEATURES]
    assert not missing, f"B2 features the gate requires are not registered: {missing}"


def test_a_mean_is_not_called_a_median() -> None:
    """`median_age_s` was the mean age. Either name it, or compute the median."""

    source = _source()
    assert "median_age_s" not in source or "np.median" in source, (
        "a feature named median must be one"
    )


def test_empty_window_is_distinct_from_provider_failure() -> None:
    """Three different facts that all used to arrive downstream as "no flow"."""

    source = _source()
    assert "provider_failure" in source, (
        "a session whose tape could not be read must be recorded as a failure, not as a "
        "window in which nobody traded"
    )
    assert "sparse_sessions" in source, (
        "a session that was read and held almost nothing is sparse, not a failure"
    )
    assert "empty_window_share_5m" in source, (
        "a window in which nobody traded is a fact about the market and must be counted"
    )


def test_an_unreadable_tape_is_reported_rather_than_fatal() -> None:
    """If a bad file aborts the run, the published failure count can only ever be zero."""

    block6 = _load("rp2_block6_flow_panel")
    assert block6._read_tape(["no/such/file.parquet"], "AAPL") is None


def test_a_readable_tape_with_no_qualifying_prints_is_not_a_provider_failure(
    tmp_path: object,
) -> None:
    """Nobody traded is a fact about the market, not the provider being broken."""

    import polars as pl

    block6 = _load("rp2_block6_flow_panel")
    path = Path(str(tmp_path)) / "empty.parquet"
    pl.DataFrame(
        {name: pl.Series(name, [], dtype=pl.Utf8) for name in block6.TAPE_COLUMNS}
    ).with_columns(
        size=pl.lit(None, pl.Float64),
        strike=pl.lit(None, pl.Float64),
        implied_volatility=pl.lit(None, pl.Float64),
    ).write_parquet(path)

    tape = block6._read_tape([str(path)], "AAPL")
    assert tape is not None, "a readable file with nothing in it is not an I/O failure"
    assert tape.height == 0


def test_the_intensity_is_evaluated_at_each_cutoff_over_visible_rows() -> None:
    """Ageing on the exchange clock is only half of it; availability is the other half.

    Sorting the whole session by execution and running one recursion would let a trade the
    provider had not published yet raise the intensity of one it had — a point-in-time
    violation carrying an economically correct timestamp.
    """

    source = _source()
    assert "decay_intensity_at(" in source
    assert "exponential_decay_intensity" not in source
    assert "intensity[hi - 1]" not in source, (
        "the last published row of a window is not necessarily its latest execution"
    )
    assert "visible = np.searchsorted(created, cutoffs_us" in source, (
        "the visible prefix at each cutoff is what the recursion may see"
    )


def test_a_session_asset_with_no_tape_at_all_is_counted() -> None:
    """A skipped session-asset makes every coverage number describe only what was complete."""

    source = _source()
    assert "missing_tape_inventory" in source, (
        "a B0 session-asset with no inventory entry must be recorded, not skipped"
    )
    assert "missing_bar_grid" in source, "nor may a missing bar grid vanish"
    assert "session_assets_in_b0_panel" in source, (
        "the denominator has to be what the study asked for, not what it managed"
    )
    assert "session_assets_attempted" in source and "limit_sessions" in source, (
        "a limited run must publish both what it attempted and what the panel holds, or the "
        "artifact describes neither the sample nor the study"
    )
    limit = source.index("jobs = jobs[: args.limit_sessions]")
    counted = source.index("session_assets_in_panel = len(jobs)")
    assert counted < limit, "the panel-wide count must be taken before the run is truncated"


def test_an_empty_window_still_reports_the_intensity_it_has() -> None:
    """Nobody traded in the last five minutes; the tape before that still exists.

    Returning only trades and premium filled every other registered feature with null, and
    the fail-closed mask then removed the origin from every contrast — for the sake of a
    window in which nobody traded, which is a fact worth keeping.
    """

    import numpy as np

    block6 = _load("rp2_block6_flow_panel")
    prefixes = {name: np.zeros(3, dtype=np.float64) for name in block6.CHANNEL_NAMES}
    record = block6._window_record(
        2,
        2,
        "5m",
        window_seconds=300,
        cutoff_us=1_800_000_000_000_000,
        prefixes=prefixes,
        keys=np.zeros(2, dtype=np.int64),
        strike=np.zeros(2),
        expiry_day=np.zeros(2, dtype=np.int64),
        premium=np.zeros(2),
        seconds=np.zeros(2),
        intensity_now=12.5,
        intensity_before=4.0,
    )
    assert record["b2_5m_trades"] == 0.0
    assert record["b2_5m_decay_intensity_last"] == 12.5
    assert record["b2_5m_decay_intensity_innovation"] == 8.5
    # A mean over nothing is unmeasured. A NaN here would be honest and would also remove
    # the origin from every contrast, so the window says so explicitly instead.
    assert record["b2_5m_is_empty_window"] == 1.0
    assert record["b2_5m_rate_per_second"] == 0.0
    assert record["b2_5m_observed_span_s"] == 0.0
    assert record["b2_5m_mean_provider_latency_s"] == 0.0
    assert record["b2_5m_mean_age_s"] == 0.0

    # Every registered five-minute feature, not merely the ones the record happened to
    # return: a key that is absent becomes a null in the panel and the fail-closed mask
    # removes the origin, which is the same failure by a quieter route.
    from mds650.rp2.panel import B2_FEATURES

    registered = {name for name in B2_FEATURES if name.startswith("b2_5m_")}
    missing = sorted(registered - set(record))
    assert not missing, f"registered features an empty window does not emit: {missing}"
    assert all(np.isfinite(record[name]) for name in registered), (
        "an empty window must not put a non-finite value into a registered feature"
    )


def test_a_single_print_window_is_flow_not_silence() -> None:
    """One trade has a zero observed span, and a rate divided by that span is nonsense."""

    import numpy as np

    block6 = _load("rp2_block6_flow_panel")
    prefixes = {name: np.zeros(3, dtype=np.float64) for name in block6.CHANNEL_NAMES}
    for name in ("trades", "premium", "size"):
        prefixes[name] = np.array([0.0, 0.0, 1.0])
    record = block6._window_record(
        1,
        2,
        "5m",
        window_seconds=300,
        cutoff_us=1_800_000_000_000_000,
        prefixes=prefixes,
        keys=np.zeros(2, dtype=np.int64),
        strike=np.ones(2),
        expiry_day=np.zeros(2, dtype=np.int64),
        premium=np.ones(2),
        seconds=np.zeros(2),
        intensity_now=1.0,
        intensity_before=0.0,
    )
    assert record["b2_5m_trades"] == 1.0
    assert record["b2_5m_is_empty_window"] == 0.0
    assert record["b2_5m_observed_span_s"] == 0.0
    assert record["b2_5m_rate_per_second"] > 0.0, (
        "positive flow reported as a rate of zero contradicts is_empty_window"
    )
    assert record["b2_5m_rate_per_second"] == 1.0 / 300


def test_a_missing_required_column_stops_the_rebuild(tmp_path: object) -> None:
    """A schema regression is not an acquisition gap and must not be counted as one."""

    import polars as pl
    import pytest as _pytest

    block6 = _load("rp2_block6_flow_panel")
    path = Path(str(tmp_path)) / "no_executed_at.parquet"
    pl.DataFrame({"underlying_symbol": ["AAPL"]}).write_parquet(path)
    with _pytest.raises(pl.exceptions.ColumnNotFoundError):
        block6._read_tape([str(path)], "AAPL")


def test_out_of_session_executions_are_removed_before_pricing() -> None:
    """Clamping a pre-open print to the open prices it at a level it never traded at."""

    from datetime import date, datetime, timedelta

    import numpy as np
    import polars as pl

    block6 = _load("rp2_block6_flow_panel")
    session = "2026-06-15"
    open_at = datetime.combine(date.fromisoformat(session), datetime.min.time()).replace(
        tzinfo=block6.NY
    ) + timedelta(minutes=block6.SESSION_OPEN_MINUTE)
    naive_open = open_at.astimezone(block6.UTC).replace(tzinfo=None)

    executions = [
        naive_open - timedelta(minutes=45),   # pre-open
        naive_open + timedelta(minutes=10),   # inside
        naive_open + timedelta(minutes=400),  # after the close
        naive_open + timedelta(minutes=4),    # inside, but the previous bar is unobserved
        naive_open + timedelta(seconds=20),   # the opening minute: no completed bar yet
    ]
    tape = pl.DataFrame({"executed_at": executions})
    closes = np.full(390, 100.0)
    closes[3] = np.nan

    kept = block6._in_session(tape, session, closes)
    assert kept.height == 1, "only prints a completed bar can mark survive"
    assert kept["executed_at"][0] == executions[1]

    source = _source()
    assert "np.clip(" not in source.split("minute_of_trade")[1][:200], (
        "a clamp would price an out-of-session execution at the open or the close"
    )
    assert "closes[minute_of_trade - 1]" in source, (
        "bars are labelled by their start, so closes[m] is a price from the trade's future"
    )
