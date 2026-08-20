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


def test_the_intensity_recursion_runs_in_execution_order() -> None:
    """A non-monotone time series makes an exponential decay amplify instead of decay."""

    source = _source()
    assert "clocks.execution_order" in source
    assert "intensity[order] = exponential_decay_intensity(" in source
    assert "intensity[hi - 1]" not in source, (
        "the last published row of a window is not necessarily its latest execution"
    )
