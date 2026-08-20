"""A registered feature must reach the panel, and a panel column must be registered.

This is the fourth instance of one defect shape in this programme, and the most expensive:
machinery that is correct and unreachable.

`SPY_rv_30`, `SPY_ret_30`, `QQQ_rv_30` and `QQQ_ret_30` were built into the B0 panel from
the beginning and were never added to `B0_FEATURES`. Every block from 7 onward therefore ran
a baseline that could not see the market at all — and a B2 increment measured against a
market-blind baseline credits option flow with whatever the whole market was doing at the
time. Nothing failed, nothing warned; the columns simply sat there.

The reverse direction matters too. A feature registered but absent from the panel is not a
silent loss — `assert_required_columns` fails closed on it — but it fails at run time, deep
in a rebuild, rather than here.

Both checks skip when the panel is absent, so the hermetic runner (which has no licensed
derived data) stays green while the local tier-2 run does the real work.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
import pytest

from mds650.rp2.feature_registry import feature_map, registry
from mds650.rp2.panel import B0_FEATURES, B1_FEATURES, B2_FEATURES

REPO = Path(__file__).resolve().parents[2]

PANELS: tuple[tuple[str, Path, dict[str, str]], ...] = (
    ("B0", REPO / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet", B0_FEATURES),
    ("B1", REPO / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet", B1_FEATURES),
    ("B2", REPO / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet", B2_FEATURES),
)

#: Columns a panel carries for identification, joining or as a target.
KEY_AND_TARGET_COLUMNS: frozenset[str] = frozenset(
    {"asset", "session_date", "origin_minute", "role", "source", "rv30", "jump30"}
)

#: Columns built on purpose and deliberately kept out of every information set. Naming them
#: here is the point: an unregistered column should be a decision on the record, not a
#: column nobody noticed. Four market-control columns sat outside the registry for the whole
#: programme precisely because there was no list to be absent from.
DECLARED_DIAGNOSTICS: frozenset[str] = frozenset(
    {
        # Seasonality bucket index, consumed by the Block 4 ladder rather than modelled.
        "minute_bucket",
        # Realized-measure intermediates that feed B0 features but are not features.
        "rv_back_30",
        "rq_back_30",
        "rs_up_back_30",
        "rs_down_back_30",
        "jump_back_30",
        "dollar_volume_30",
        # Surface quality and no-arbitrage diagnostics. Reported with every estimate so a
        # reader can tell a measurement from a truncation; never fitted, because a model
        # that learns "trust this origin" from a coverage flag is learning the sampler.
        "b1_contracts",
        "b1_calendar_violations",
        "b1_spans_call_wing",
        "b1_spans_put_wing",
        # B1-rich. Emitted, reported and hashed, deliberately outside the primary set: a
        # feature that fits on 60% of origins would remove 40% of the evaluation rows from
        # every contrast carrying it, and an arbitrage or curvature diagnostic is there to
        # describe the surface, not to be fitted. Formalised as a registry in gate 6.
        "b1_iv_14d",
        "b1_iv_90d",
        "b1_term_convexity",
        "b1_smile_slope",
        "b1_smile_curvature",
        "b1_smile_residual",
        "b1_butterfly_25",
        "b1_mfiv",
        "b1_strikes",
        "b1_expiries",
        "b1_pcp_residual",
        "b1_forward_expiries_fitted",
        "b1_min_log_moneyness",
        "b1_max_log_moneyness",
        "b1_zero_dte_contracts",
        "b1_butterfly_violations",
        "b1_implied_rate",
        "b1_implied_dividend_yield",
        # Quote age is a property of the tape, not of the market being forecast.
        "b2_5m_mean_age_s",
        "b2_30m_mean_age_s",
    }
)


@pytest.mark.parametrize(("name", "path", "features"), PANELS, ids=[row[0] for row in PANELS])
def test_every_registered_feature_exists_in_its_panel(
    name: str, path: Path, features: dict[str, str]
) -> None:
    if not path.is_file():
        pytest.skip(f"{name} panel not built here; licensed derived data is local only")
    columns = set(pl.read_parquet_schema(path))
    missing = sorted(set(features) - columns)
    assert not missing, f"{name} registers features the panel does not carry: {missing}"


def test_the_market_controls_are_registered_and_not_merely_present() -> None:
    """The specific regression: four columns in the panel, none of them a feature.

    Pinned by name because the failure was invisible — the panel had them, the ladder's own
    `b0_market` variant used them, and the information set every later block reads did not.
    """

    for column in ("SPY_rv_30", "SPY_ret_30", "QQQ_rv_30", "QQQ_ret_30"):
        assert column in B0_FEATURES, f"{column} is built and never used"


def test_no_panel_column_is_a_feature_nobody_registered() -> None:
    """The same defect in the other direction, across every panel that exists locally."""

    unregistered: list[str] = []
    for name, path, _ in PANELS:
        if not path.is_file():
            continue
        columns = set(pl.read_parquet_schema(path))
        prefix = {"B1": "b1_", "B2": "b2_"}.get(name)
        # Registered means in the frozen registry, core *or* rich. A rich feature is out of
        # every primary contrast and is still a feature somebody chose to build.
        registered = set(feature_map(*[s for s in registry() if s.startswith(name)]))
        candidates = {
            column
            for column in columns - KEY_AND_TARGET_COLUMNS - DECLARED_DIAGNOSTICS
            if prefix is None or column.startswith(prefix)
        }
        for column in sorted(candidates - registered):
            unregistered.append(f"{name}:{column}")
    assert not unregistered, (
        "panel columns that are neither a registered feature nor a declared diagnostic — "
        f"register them, declare them, or stop building them: {unregistered}"
    )


def _design_callers() -> dict[str, str]:
    """Every script that assembles an information set, discovered rather than listed.

    A hand-kept list is a list that goes stale: two extension scripts built designs and
    emitted artifacts for the whole programme without appearing on any such list.
    """

    found = {}
    for path in sorted((REPO / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "build_design(" in text and "def build_design" not in text:
            found[str(path.relative_to(REPO)).replace("\\", "/")] = text
    return found


#: Panel helpers whose entire purpose is to stop a run. A helper that is written, tested and
#: never called protects nothing; this programme has shipped that exact shape four times.
FAIL_CLOSED_HELPERS: tuple[str, ...] = (
    "assert_required_columns",
    "assert_unique_origin_key",
    "assert_one_to_one_join",
    "common_usable_rows",
    "describe_information_set",
    "mask_sha256",
)


def _production_sources() -> dict[str, str]:
    files = sorted((REPO / "src").rglob("*.py")) + sorted((REPO / "scripts").glob("*.py"))
    return {str(path.relative_to(REPO)): path.read_text(encoding="utf-8") for path in files}


def test_every_fail_closed_panel_helper_has_a_production_caller() -> None:
    """The recurring defect: machinery that is correct, tested and unreachable."""

    sources = _production_sources()
    uncalled = []
    for helper in FAIL_CLOSED_HELPERS:
        call = re.compile(rf"(?<!def ){re.escape(helper)}\(")
        callers = [name for name, text in sources.items() if call.search(text)]
        if not callers:
            uncalled.append(helper)
    assert not uncalled, (
        f"panel helpers with no production caller — they guard nothing: {uncalled}"
    )


def test_every_design_caller_records_the_information_set_it_resolved() -> None:
    """A run may not be called B0+B1+B2 without saying what that resolved to."""

    callers = _design_callers()
    assert len(callers) >= 9, f"discovery found only {sorted(callers)}"
    missing = sorted(
        name for name, text in callers.items() if "describe_information_set(" not in text
    )
    assert not missing, f"scripts that build a design without recording it: {missing}"


def test_no_design_caller_intersects_the_evaluation_mask_by_hand() -> None:
    """One definition of the nested-comparison mask, so they cannot drift apart."""

    hand_rolled = sorted(
        name for name, text in _design_callers().items() if "keep &= usable_rows(" in text
    )
    assert not hand_rolled, (
        f"scripts building the common mask themselves instead of common_usable_rows: "
        f"{hand_rolled}"
    )


#: A result dict is a small literal, so the provenance key is within a few lines of the
#: status that opens it.
_EARLY_RETURN_WINDOW = 8


def test_every_early_return_carries_the_provenance() -> None:
    """The artifacts most in need of diagnostics are the ones that stopped early.

    Any exit that is not MEASURED leaves exactly the artifact a reader would want to audit,
    and it must still say which information sets were resolved and on which rows. Pinning
    only INSUFFICIENT_ROWS missed the two sparse-leg exits of Block 11b.
    """

    status = re.compile(r'"status": "(?!MEASURED")([A-Z_]+)"')
    bare = []
    for name, text in _design_callers().items():
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = status.search(line)
            if not match:
                continue
            window = "\n".join(lines[index : index + _EARLY_RETURN_WINDOW])
            if '"information_sets"' not in window:
                bare.append(f"{name}:{index + 1}:{match.group(1)}")
    assert not bare, f"early returns that omit the resolved information sets: {bare}"
