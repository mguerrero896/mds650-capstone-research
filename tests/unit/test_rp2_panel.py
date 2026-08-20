"""Merged panel: information-set definitions, transforms and design assembly."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    INFORMATION_SETS,
    JOIN_KEYS,
    VARIANCE_FLOOR,
    build_design,
    chronological_split,
    common_usable_rows,
    describe_information_set,
    load_merged_panel,
    mask_sha256,
    session_rank,
    standardise,
    transform_column,
    usable_rows,
)


def test_the_three_information_sets_are_disjoint_and_registered() -> None:
    assert set(INFORMATION_SETS) == {"B0", "B1", "B2"}
    assert not set(B0_FEATURES) & set(B1_FEATURES)
    assert not set(B1_FEATURES) & set(B2_FEATURES)
    assert not set(B0_FEATURES) & set(B2_FEATURES)


def test_b2_is_the_core_dozen_with_known_transforms() -> None:
    """The primary B2 set is the twelve core mechanisms, not every channel the block emits.

    The thirty-minute window and the remaining channels are B2-rich: reported and hashed,
    outside every primary contrast, because a hundred-plus dimensions against a few dozen
    independent sessions is estimation variance rather than information.
    """

    assert 10 <= len(B2_FEATURES) <= 12
    assert all(name.startswith("b2_5m_") for name in B2_FEATURES)
    assert set(B2_FEATURES.values()) <= {"log", "signed", "raw"}
    # Signed flow really is registered as signed: it takes both signs.
    assert B2_FEATURES["b2_5m_vega_flow"] == "signed"
    assert B2_FEATURES["b2_5m_premium"] == "log"


def test_transforms_behave_as_declared() -> None:
    values = np.array([-100.0, 0.0, 100.0])
    assert transform_column(values, "raw").tolist() == values.tolist()

    logged = transform_column(values, "log")
    assert logged[0] == pytest.approx(np.log(VARIANCE_FLOOR))
    assert logged[2] == pytest.approx(np.log(100.0))

    signed = transform_column(values, "signed")
    assert signed[0] == pytest.approx(-np.log1p(100.0))
    assert signed[1] == pytest.approx(0.0)
    assert signed[2] == pytest.approx(np.log1p(100.0))
    # A signed transform is odd; a log transform could not represent the left half.
    assert signed[0] == pytest.approx(-signed[2])

    with pytest.raises(ValueError, match="RP2_PANEL_UNKNOWN_TRANSFORM"):
        transform_column(values, "sqrt")


def _panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "asset": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "session_date": ["2026-01-05", "2026-01-06", "2026-01-05", "2026-01-06"],
            "origin_minute": [30, 30, 30, 30],
            "rv30": [1e-5, 2e-5, 3e-5, 4e-5],
            "rv_back_30": [1e-5, 2e-5, 3e-5, 4e-5],
            "ret_30": [0.001, -0.002, 0.003, -0.004],
        }
    )


def test_build_design_resolves_every_registered_feature_or_refuses_to_build() -> None:
    """A design named after an information set must contain that whole information set."""

    design, names = build_design(_panel(), [{"rv_back_30": "log", "ret_30": "raw"}])
    assert names == ("intercept", "rv_back_30", "ret_30")
    assert design.shape == (4, 3)
    assert np.allclose(design[:, 0], 1.0)

    with pytest.raises(ValueError, match="RP2_PANEL_REQUIRED_MISSING"):
        build_design(_panel(), [B0_FEATURES])


def test_build_design_can_omit_the_intercept_and_rejects_an_empty_selection() -> None:
    design, names = build_design(_panel(), [{"ret_30": "raw"}], intercept=False)
    assert names == ("ret_30",)
    assert design.shape == (4, 1)
    with pytest.raises(ValueError, match="RP2_PANEL_EMPTY_DESIGN"):
        build_design(_panel(), [], intercept=False)


def test_registered_b1_feature_missing_from_panel_fails_closed() -> None:
    """A B1 column the registry promises and the panel lacks must stop the run."""

    frame = _panel().with_columns(
        **{name: pl.lit(0.1) for name in B1_FEATURES if name != "b1_iv_30d"}
    )
    with pytest.raises(ValueError, match="RP2_PANEL_REQUIRED_MISSING:b1_iv_30d"):
        build_design(frame, [B1_FEATURES])


def test_registered_b2_feature_missing_from_panel_fails_closed() -> None:
    frame = _panel().with_columns(
        **{name: pl.lit(0.1) for name in B2_FEATURES if name != "b2_5m_premium"}
    )
    with pytest.raises(ValueError, match="RP2_PANEL_REQUIRED_MISSING:b2_5m_premium"):
        build_design(frame, [B2_FEATURES])


def test_nested_information_sets_use_the_same_evaluation_rows() -> None:
    """B0 may not be scored on a row B0+B1 dropped: the increment would be free."""

    target = np.array([1e-5, 2e-5, 3e-5, 4e-5])
    b0 = np.column_stack([np.ones(4), np.array([1.0, 2.0, 3.0, 4.0])])
    b0_b1 = np.column_stack([b0, np.array([1.0, np.nan, 3.0, 4.0])])
    b0_b1_b2 = np.column_stack([b0_b1, np.array([1.0, 2.0, 3.0, np.inf])])

    mask = common_usable_rows({"B0": b0, "B0+B1": b0_b1, "B0+B1+B2": b0_b1_b2}, target)
    assert mask.tolist() == [True, False, True, False]
    # Each design on its own would have kept more rows than the contrast may use.
    assert usable_rows(b0, target).sum() == 4
    assert int(mask.sum()) == 2


def test_the_evaluation_mask_hash_distinguishes_masks_of_equal_size() -> None:
    """Two masks can keep the same number of rows and not the same rows."""

    left = np.array([True, True, False, False])
    right = np.array([False, False, True, True])
    assert left.sum() == right.sum()
    assert mask_sha256(left) != mask_sha256(right)
    assert mask_sha256(left) == mask_sha256(left.copy())
    assert len(mask_sha256(left)) == 64


def test_an_information_set_record_names_what_it_actually_resolved() -> None:
    """The intercept is not a feature: counting it makes 22 registered read as 23 resolved."""

    mask = np.array([True, False, True, True])
    record = describe_information_set(
        ("B0_subset",), ("intercept", "rv_back_30", "ret_30"), mask
    )
    assert record["requested_information_set"] == ["B0_subset"]
    assert record["resolved_feature_names"] == ["rv_back_30", "ret_30"]
    assert record["feature_count"] == 2
    assert record["includes_intercept"] is True
    assert record["evaluation_mask_sha256"] == mask_sha256(mask)

    without = describe_information_set(("B2_treatment",), ("b2_5m_premium",), mask)
    assert without["includes_intercept"] is False
    assert without["feature_count"] == 1


def test_a_resolved_record_can_be_compared_against_the_registry_directly() -> None:
    """The section 3 exit criterion is resolved == registered, so the record must be that."""

    frame = _panel().with_columns(**{name: pl.lit(0.1) for name in B1_FEATURES})
    _, names = build_design(frame, [B1_FEATURES])
    record = describe_information_set(("B1",), names, np.ones(frame.height, dtype=bool))
    assert set(record["resolved_feature_names"]) == set(B1_FEATURES)
    assert record["feature_count"] == len(B1_FEATURES)


def test_session_rank_is_dense_and_ordered_in_time() -> None:
    sessions = np.array(["2026-01-06", "2026-01-05", "2026-01-06", "2026-01-02"])
    assert session_rank(sessions).tolist() == [2, 1, 2, 0]


def test_usable_rows_requires_a_positive_target_and_a_finite_design() -> None:
    design = np.array([[1.0, 2.0], [1.0, np.nan], [1.0, 4.0], [1.0, 5.0]])
    target = np.array([1.0, 1.0, 0.0, 2.0])
    assert usable_rows(design, target).tolist() == [True, False, False, True]


def test_chronological_split_divides_by_session_never_by_row() -> None:
    index = np.array([0, 0, 1, 1, 2, 2, 3, 3], dtype=np.int64)
    train, test = chronological_split(index, train_share=0.5)
    # Whole sessions land on one side; no session is split across the boundary.
    assert train.tolist() == [True, True, True, True, False, False, False, False]
    assert (train & test).sum() == 0
    assert (train | test).all()
    with pytest.raises(ValueError, match="RP2_PANEL_TRAIN_SHARE_INVALID"):
        chronological_split(index, train_share=1.0)


def test_standardise_uses_training_statistics_only_and_leaves_the_intercept() -> None:
    design = np.column_stack([np.ones(6), np.array([0.0, 2.0, 4.0, 100.0, 200.0, 300.0])])
    train = np.array([True, True, True, False, False, False])
    out = standardise(design, train)
    assert np.allclose(out[:, 0], 1.0)
    # Training block is centred and scaled; test rows keep the training scale, so
    # their values stay far from zero rather than being re-centred on themselves.
    assert out[train, 1].mean() == pytest.approx(0.0, abs=1e-12)
    assert out[train, 1].std() == pytest.approx(1.0)
    assert out[~train, 1].min() > 5.0


def test_standardise_tolerates_a_constant_column_and_validates_inputs() -> None:
    design = np.column_stack([np.ones(4), np.full(4, 7.0)])
    out = standardise(design, np.array([True, True, False, False]))
    assert np.isfinite(out).all()
    assert np.allclose(out[:, 1], 0.0)
    with pytest.raises(ValueError, match="RP2_PANEL_STANDARDISE_SHAPE"):
        standardise(design, np.ones(3, dtype=bool))
    with pytest.raises(ValueError, match="RP2_PANEL_STANDARDISE_EMPTY_TRAIN"):
        standardise(design, np.zeros(4, dtype=bool))


def _complete(root: object) -> object:
    """Write a B0/B1/B2 trio that meets every core coverage floor.

    The loader enforces the registry's floors, so a fixture that is merely enough to join
    is no longer enough to load. That is the point of the floor, and it means the join
    semantics and the floor need separate tests.
    """

    from pathlib import Path

    directory = Path(str(root))
    keys = {
        "asset": ["AAPL", "AAPL", "MSFT", "MSFT"],
        "session_date": ["2026-01-05", "2026-01-06", "2026-01-05", "2026-01-06"],
        "origin_minute": [30, 30, 30, 30],
    }
    pl.DataFrame(
        {**keys, "rv30": [1e-5, 2e-5, 3e-5, 4e-5]}
        | {name: [1.0, 2.0, 3.0, 4.0] for name in B0_FEATURES}
    ).write_parquet(directory / "b0.parquet")
    pl.DataFrame({**keys} | {name: [0.30, 0.31, 0.40, 0.41] for name in B1_FEATURES}).write_parquet(
        directory / "b1.parquet"
    )
    pl.DataFrame(
        {**keys} | {name: [1000.0, 1100.0, 2000.0, 2100.0] for name in B2_FEATURES}
    ).write_parquet(directory / "b2.parquet")
    return directory


def test_load_merged_panel_joins_on_the_origin_key(tmp_path: object) -> None:
    root = _complete(tmp_path)
    merged = load_merged_panel(root / "b0.parquet", root / "b1.parquet", root / "b2.parquet")
    assert merged.height == 4
    assert set(JOIN_KEYS) <= set(merged.columns)
    assert "b1_iv_30d" in merged.columns
    assert "b2_5m_premium" in merged.columns
    assert merged["b1_iv_30d"].null_count() == 0


def test_load_merged_panel_refuses_a_panel_below_its_coverage_floor(tmp_path: object) -> None:
    """A left join keeps unmatched rows as nulls, and the floor is what says how many.

    Without it, a B1 build covering half the origins would arrive as a panel with half its
    surface missing, and every contrast would quietly drop those rows instead of the run
    stopping.
    """

    root = _complete(tmp_path)
    surface = pl.read_parquet(root / "b1.parquet").head(1)
    surface.write_parquet(root / "sparse_b1.parquet")
    with pytest.raises(ValueError, match="RP2_FEATURE_SET_COVERAGE_BREACH"):
        load_merged_panel(root / "b0.parquet", root / "sparse_b1.parquet", root / "b2.parquet")


def test_missing_b1_file_fails_closed(tmp_path: object) -> None:
    """A run cannot be called B0+B1 because the B1 file quietly was not there."""

    from pathlib import Path

    root = Path(str(tmp_path))
    _panel().write_parquet(root / "b0.parquet")
    pl.DataFrame(
        {
            "asset": ["AAPL"],
            "session_date": ["2026-01-05"],
            "origin_minute": [30],
            "b2_5m_premium": [1.0],
        }
    ).write_parquet(root / "b2.parquet")
    with pytest.raises(FileNotFoundError, match="RP2_PANEL_INPUT_MISSING:B1:"):
        load_merged_panel(root / "b0.parquet", root / "absent.parquet", root / "b2.parquet")


def test_missing_b2_file_fails_closed(tmp_path: object) -> None:
    from pathlib import Path

    root = Path(str(tmp_path))
    _panel().write_parquet(root / "b0.parquet")
    pl.DataFrame(
        {
            "asset": ["AAPL"],
            "session_date": ["2026-01-05"],
            "origin_minute": [30],
            "b1_iv_30d": [0.3],
        }
    ).write_parquet(root / "b1.parquet")
    with pytest.raises(FileNotFoundError, match="RP2_PANEL_INPUT_MISSING:B2:"):
        load_merged_panel(root / "b0.parquet", root / "b1.parquet", root / "absent.parquet")


def _origin_frame(minutes: list[int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "asset": ["AAPL"] * len(minutes),
            "session_date": ["2026-06-15"] * len(minutes),
            "origin_minute": minutes,
        }
    )


def test_a_duplicated_origin_key_is_refused() -> None:
    """A duplicate origin double-weights that row in every mean and bootstrap after it."""

    from mds650.rp2.panel import assert_unique_origin_key

    assert_unique_origin_key(_origin_frame([30, 35, 40]))
    with pytest.raises(ValueError, match="RP2_PANEL_ORIGIN_KEY_DUPLICATED:1"):
        assert_unique_origin_key(_origin_frame([30, 35, 35]))


def test_a_missing_origin_key_column_is_refused() -> None:
    from mds650.rp2.panel import assert_unique_origin_key

    with pytest.raises(ValueError, match="RP2_PANEL_ORIGIN_KEY_MISSING"):
        assert_unique_origin_key(pl.DataFrame({"asset": ["AAPL"]}))


def test_a_join_that_fans_the_panel_out_is_refused() -> None:
    """A duplicated key on the right multiplies rows; it looks like more data."""

    from mds650.rp2.panel import assert_one_to_one_join

    left = _origin_frame([30, 35])
    right = _origin_frame([30, 30, 35]).with_columns(value=pl.Series([1.0, 2.0, 3.0]))
    joined = left.join(right, on=list(JOIN_KEYS), how="left")
    assert joined.height > left.height
    with pytest.raises(ValueError, match="RP2_PANEL_JOIN_CARDINALITY"):
        assert_one_to_one_join(left, right, joined)


def test_a_clean_one_to_one_join_passes() -> None:
    from mds650.rp2.panel import assert_one_to_one_join

    left = _origin_frame([30, 35])
    right = _origin_frame([30, 35]).with_columns(value=pl.Series([1.0, 2.0]))
    joined = left.join(right, on=list(JOIN_KEYS), how="left")
    assert_one_to_one_join(left, right, joined)
    assert joined.height == left.height


def test_a_missing_required_column_fails_closed() -> None:
    from mds650.rp2.panel import assert_required_columns

    frame = _origin_frame([30])
    assert_required_columns(frame, ["asset", "origin_minute"])
    with pytest.raises(ValueError, match="RP2_PANEL_REQUIRED_MISSING:rv30"):
        assert_required_columns(frame, ["asset", "rv30"])


def test_a_record_may_not_claim_a_registry_it_did_not_resolve() -> None:
    """Labelling a ten-feature treatment subset `B2` reads as 96 features silently lost.

    The provenance exists so that requested and resolved can be compared. A label that
    names a registry has to mean that whole registry, or the comparison is meaningless.
    """

    mask = np.ones(3, dtype=bool)
    with pytest.raises(ValueError, match="RP2_PANEL_INFORMATION_SET_MISLABELLED:B2"):
        describe_information_set(("B2",), ("b2_5m_premium", "b2_5m_delta_flow"), mask)

    # A subset is fine when it says it is one.
    record = describe_information_set(
        ("B2_mechanism",), ("b2_5m_premium", "b2_5m_delta_flow"), mask
    )
    assert record["feature_count"] == 2

    # A composite label is checked part by part.
    full = tuple(B0_FEATURES) + tuple(B1_FEATURES)
    assert describe_information_set(("B0+B1",), full, mask)["feature_count"] == len(full)
    with pytest.raises(ValueError, match="RP2_PANEL_INFORMATION_SET_MISLABELLED:B1"):
        describe_information_set(("B0+B1",), tuple(B0_FEATURES), mask)
