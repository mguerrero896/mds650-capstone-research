"""B1 must describe the option market at the forecast origin, not half an hour earlier.

RP2-v2 ended B1's snapshot 1 920 seconds before the origin so that no tape row could feed
both B1 and B2. The contrast is conditional, so that disjointness was never required, and
it cost B1 the only thing it is for.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_the_b1_window_ends_at_the_availability_cutoff() -> None:
    """Not 1 800 seconds earlier, which is what the disjointness rule bought."""

    block5 = _load("rp2_block5_surface_panel")
    from mds650.rp2.b1_snapshot import CUTOFF_SECONDS, MAX_QUOTE_AGE_SECONDS

    assert block5.CUTOFF_SECONDS == CUTOFF_SECONDS
    assert block5.MAX_QUOTE_AGE_SECONDS == MAX_QUOTE_AGE_SECONDS
    assert not hasattr(block5, "SNAPSHOT_END_SECONDS"), (
        "the lagged snapshot end is what made B1 a stale state"
    )
    assert not hasattr(block5, "assert_disjoint_from_flow_window"), (
        "B1 and B2 may overlap: the contrast between them is conditional, not disjoint"
    )


def test_block5_reads_the_snapshot_through_the_shared_rule() -> None:
    """One definition of the point-in-time window, not one per block."""

    source = (REPO / "scripts" / "rp2_block5_surface_panel.py").read_text(encoding="utf-8")
    assert "latest_quote_per_contract(" in source
    assert "snapshot_window(" in source
    assert "FLOW_WINDOW_SECONDS" not in source, (
        "B1's window may no longer be defined in terms of B2's"
    )


def test_the_core_surface_features_are_emitted() -> None:
    """B1-core is ten high-coverage features; two of them did not exist before."""

    from mds650.rp2.panel import B1_FEATURES

    core = (
        "b1_iv_7d",
        "b1_iv_30d",
        "b1_iv_60d",
        "b1_term_slope",
        "b1_smile_level",
        "b1_risk_reversal_25",
        "b1_median_relative_spread",
        "b1_median_quote_age_s",
        "b1_surface_coverage",
        "b1_iv_minus_trailing_rv_30d",
    )
    missing = [name for name in core if name not in B1_FEATURES]
    assert not missing, f"B1-core features not registered: {missing}"


def test_a_failed_implied_rate_does_not_discard_the_origin() -> None:
    """A diagnostic that would not fit is a missing diagnostic, not a missing row."""

    source = (REPO / "scripts" / "rp2_block5_surface_panel.py").read_text(encoding="utf-8")
    spec = (REPO / "docs" / "rp2_v3" / "B1_CONTEMPORANEOUS_SPEC.md").read_text(encoding="utf-8")
    assert "A row is never discarded because implied rate" in spec
    assert "b1_implied_rate" in source


def test_the_sensitivity_bound_is_reachable_and_is_not_the_primary() -> None:
    """A pre-registered sensitivity nobody can run is not a sensitivity.

    The 60-minute bound is a documented alternative, so it must be a value the block
    accepts, and the frozen primary panel must not be built with it.
    """

    block5 = _load("rp2_block5_surface_panel")
    from mds650.rp2.b1_snapshot import MAX_QUOTE_AGE_SECONDS, SENSITIVITY_MAX_AGE_SECONDS

    assert SENSITIVITY_MAX_AGE_SECONDS == 2 * MAX_QUOTE_AGE_SECONDS
    primary = block5.snapshot_window(0)
    sensitivity = block5.snapshot_window(0, max_quote_age_seconds=SENSITIVITY_MAX_AGE_SECONDS)
    assert sensitivity.oldest_us < primary.oldest_us
    assert sensitivity.cutoff_us == primary.cutoff_us, "the cutoff is not a sensitivity knob"

    source = (REPO / "scripts" / "rp2_block5_surface_panel.py").read_text(encoding="utf-8")
    assert "--max-quote-age-seconds" in source, "the bound must be reachable from the CLI"
    assert "SENSITIVITY_MAX_AGE_SECONDS" in source, "and its value must be on the record"


def test_the_measurement_audit_reads_the_same_window_as_the_panel() -> None:
    """An audit of a different window measures a different surface.

    Block 5b estimates the trade-sampling bias by rebuilding the surface from an independent
    quote feed. In RP2-v2 it defined its own cutoff and lookback, so the surface it audited
    was not the surface the panel carried.
    """

    source = (REPO / "scripts" / "rp2_block5b_independent_surface.py").read_text(
        encoding="utf-8"
    )
    assert "from mds650.rp2.b1_snapshot import" in source
    assert "latest_quote_per_contract(" in source
    assert "LOOKBACK_SECONDS = " not in source, "the audit may not define its own window"
    assert "CUTOFF_SECONDS = 120" not in source, "nor its own cutoff"


def test_a_sensitivity_run_cannot_replace_the_primary_panel(tmp_path: object) -> None:
    """Every downstream block reads one path. A forgotten flag must not repoint it."""

    block5 = _load("rp2_block5_surface_panel")
    from mds650.rp2.b1_snapshot import SENSITIVITY_MAX_AGE_SECONDS

    with pytest.raises(SystemExit, match="RP2_B1_SENSITIVITY_NEEDS_ITS_OWN_OUTPUT_DIR"):
        block5.main(["--max-quote-age-seconds", str(SENSITIVITY_MAX_AGE_SECONDS)])


def test_the_independent_side_obeys_the_same_staleness_bound() -> None:
    """A paired comparison of a 30-minute quote against a two-day-old one measures staleness.

    The traded side is bounded by the snapshot window. The listed side asked the provider
    only for the last quote at or before the cutoff, so an untraded strike could contribute
    an arbitrarily old one and the reported difference would mix staleness into the
    trade-sampling bias it is meant to isolate.
    """

    source = (REPO / "scripts" / "rp2_block5b_independent_surface.py").read_text(
        encoding="utf-8"
    )
    assert "MAX_QUOTE_AGE_SECONDS" in source
    assert 'counters["quotes_stale"]' in source, (
        "quotes rejected for age must be counted, not silently dropped"
    )
    assert "provider_timestamp_ns" in source, "the bound needs the quote's own timestamp"
