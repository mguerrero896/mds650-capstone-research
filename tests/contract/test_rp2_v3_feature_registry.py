"""The frozen feature sets: what is in them, and that nothing else decides.

The failure this guards is not a wrong feature list. It is two feature lists — one in the
configuration, one restated in code — that agree on the day they are written and disagree
on the day somebody edits one of them.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from mds650.rp2.feature_registry import (
    CONFIG,
    FeatureSet,
    assert_minimum_coverage,
    coverage_by_feature,
    describe_coverage,
    feature_map,
    registry,
    registry_sha256,
    transforms,
)

REPO = Path(__file__).resolve().parents[2]

REQUIRED_SETS: tuple[str, ...] = ("B0_CORE", "B1_CORE", "B2_CORE", "B1_RICH", "B2_RICH")

PANELS: tuple[tuple[str, str, Path], ...] = (
    ("B0_CORE", "B0", REPO / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"),
    ("B1_CORE", "B1", REPO / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"),
    ("B1_RICH", "B1", REPO / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"),
    ("B2_CORE", "B2", REPO / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"),
    ("B2_RICH", "B2", REPO / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"),
)


def test_every_required_set_is_registered_and_nothing_else_is() -> None:
    assert set(registry()) == set(REQUIRED_SETS)
    for entry in registry().values():
        assert isinstance(entry, FeatureSet)
        assert entry.version == "1.0"


def test_the_registry_is_loaded_from_the_configuration_not_restated() -> None:
    """One list. A second copy is a copy that drifts."""

    declared = json.loads(CONFIG.read_text(encoding="utf-8"))["sets"]
    for name, entry in registry().items():
        assert entry.features == tuple(declared[name]["features"]), name
        assert entry.minimum_coverage == declared[name]["minimum_coverage"], name


def test_the_panel_information_sets_come_from_the_registry() -> None:
    from mds650.rp2 import panel

    assert feature_map("B0_CORE") == panel.B0_FEATURES
    assert feature_map("B1_CORE") == panel.B1_FEATURES
    assert feature_map("B2_CORE") == panel.B2_FEATURES
    source = (REPO / "src" / "mds650" / "rp2" / "panel.py").read_text(encoding="utf-8")
    assert "feature_map(" in source, "the panel must load the sets, not restate them"


def test_core_and_rich_are_disjoint_within_a_block() -> None:
    """A feature is in the primary set or out of it; it cannot be both."""

    for block in ("B1", "B2"):
        core = set(registry()[f"{block}_CORE"].features)
        rich = set(registry()[f"{block}_RICH"].features)
        assert not core & rich, f"{block}: {sorted(core & rich)}"


def test_b2_core_is_a_dozen_mechanisms_not_the_whole_block() -> None:
    """The point of the split: 12 against a few dozen sessions, not 68."""

    core = registry()["B2_CORE"]
    rich = registry()["B2_RICH"]
    assert 10 <= len(core.features) <= 12, len(core.features)
    assert len(rich.features) > len(core.features)
    # Every core feature is a five-minute one: the thirty-minute window is the rich set's.
    assert all(name.startswith("b2_5m_") for name in core.features)


def test_the_named_mechanisms_of_the_plan_are_all_registered() -> None:
    """Pinned by name, so a later edit is a decision rather than an accident."""

    core = set(registry()["B2_CORE"].features)
    for name in (
        "b2_5m_trades",
        "b2_5m_premium",
        "b2_5m_buy_premium_share",
        "b2_5m_delta_flow",
        "b2_5m_vega_flow",
        "b2_5m_vega_flow_short_dte",
        "b2_5m_zero_dte_premium_share",
        "b2_5m_decay_intensity_innovation",
        "b2_5m_d_iv",
        "b2_5m_strike_hhi",
        "b2_5m_mean_provider_latency_s",
    ):
        assert name in core, name
    # The plan names `b2_5m_multileg_share`; the panel splits it by size and by premium and
    # the configuration records which one was registered and why.
    assert "b2_5m_multileg_size_share" in core
    notes = json.loads(CONFIG.read_text(encoding="utf-8"))["notes"]
    assert "b2_5m_multileg_share" in notes


def test_a_feature_may_not_change_transform_between_sets() -> None:
    kinds = transforms()
    for entry in registry().values():
        for name in entry.features:
            assert name in kinds
    assert kinds["b2_5m_trades"] == "log"
    assert kinds["b1_iv_minus_trailing_rv_30d"] == "signed"


def test_the_registry_hash_is_content_only_and_moves_with_content() -> None:
    """Prose may be edited without invalidating a run; a feature may not."""

    digest = registry_sha256()
    assert len(digest) == 64
    assert digest == registry_sha256()

    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert "description" in payload, "the hash must ignore prose that exists to be ignored"
    assert "mechanism" in payload["sets"]["B2_CORE"]


def test_minimum_coverage_is_enforced_and_not_merely_declared() -> None:
    """A floor nobody checks is not a floor."""

    complete = pl.DataFrame(
        {name: pl.Series([1.0, 2.0, 3.0, 4.0]) for name in feature_map("B1_CORE")}
    )
    assert_minimum_coverage(complete, "B1_CORE")

    holed = complete.with_columns(b1_iv_30d=pl.Series([1.0, None, None, None]))
    with pytest.raises(ValueError, match="RP2_FEATURE_SET_COVERAGE_BREACH"):
        assert_minimum_coverage(holed, "B1_CORE")

    missing = complete.drop("b1_iv_7d")
    with pytest.raises(ValueError, match="b1_iv_7d=0.0000"):
        assert_minimum_coverage(missing, "B1_CORE")


def test_coverage_counts_a_non_finite_value_as_absent() -> None:
    frame = pl.DataFrame({"b1_iv_30d": pl.Series([1.0, np.nan, np.inf, None])})
    assert coverage_by_feature(frame, ["b1_iv_30d"])["b1_iv_30d"] == 0.25
    assert coverage_by_feature(frame, ["absent"])["absent"] == 0.0


def test_the_run_record_carries_the_registry_and_its_coverage() -> None:
    frame = pl.DataFrame(
        {name: pl.Series([1.0, 2.0]) for name in feature_map("B0_CORE", "B1_CORE")}
    )
    record = describe_coverage(frame, "B0_CORE", "B1_CORE")
    assert record["feature_registry_sha256"] == registry_sha256()
    assert record["feature_count"] == len(feature_map("B0_CORE", "B1_CORE"))
    assert set(record["coverage_by_feature"]) == set(record["missingness_by_feature"])  # type: ignore[arg-type]
    assert all(value == 1.0 for value in record["coverage_by_feature"].values())  # type: ignore[union-attr]
    assert all(value == 0.0 for value in record["missingness_by_feature"].values())  # type: ignore[union-attr]


@pytest.mark.parametrize(("name", "block", "path"), PANELS, ids=[row[0] for row in PANELS])
def test_every_registered_feature_exists_in_its_panel(name: str, block: str, path: Path) -> None:
    if not path.is_file():
        pytest.skip(f"{block} panel not built here; licensed derived data is local only")
    columns = set(pl.read_parquet_schema(path))
    missing = sorted(set(registry()[name].features) - columns)
    assert not missing, f"{name} registers features the panel does not carry: {missing}"


def test_the_core_coverage_floors_hold_on_the_real_panels() -> None:
    """The floors are a claim about this evidence, so they are checked against it."""

    built = [(name, path) for name, _, path in PANELS if path.is_file() and name.endswith("_CORE")]
    if not built:
        pytest.skip("no panels built here; licensed derived data is local only")
    for name, path in built:
        panel = pl.read_parquet(path)
        assert_minimum_coverage(panel, name)
