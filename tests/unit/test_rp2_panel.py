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
    b2_features,
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


def test_b2_features_cover_both_windows_with_known_transforms() -> None:
    mapping = b2_features()
    assert mapping == B2_FEATURES
    assert any(name.startswith("b2_5m_") for name in mapping)
    assert any(name.startswith("b2_30m_") for name in mapping)
    assert set(mapping.values()) <= {"log", "signed", "raw"}
    # Signed flow really is registered as signed: it takes both signs.
    assert mapping["b2_5m_vega_flow"] == "signed"
    assert mapping["b2_5m_premium"] == "log"


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
    record = describe_information_set(
        ("B0",), ("intercept", "rv_back_30", "ret_30"), np.array([True, False, True, True])
    )
    assert record["requested_information_set"] == ["B0"]
    assert record["resolved_feature_names"] == ["intercept", "rv_back_30", "ret_30"]
    assert record["feature_count"] == 3
    assert record["evaluation_mask_sha256"] == mask_sha256(np.array([True, False, True, True]))


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


def test_load_merged_panel_joins_on_the_origin_key(
    tmp_path: object,
) -> None:
    from pathlib import Path

    root = Path(str(tmp_path))
    base = _panel()
    base.write_parquet(root / "b0.parquet")
    surface = pl.DataFrame(
        {
            "asset": ["AAPL", "MSFT"],
            "session_date": ["2026-01-05", "2026-01-05"],
            "origin_minute": [30, 30],
            "b1_iv_30d": [0.30, 0.40],
        }
    )
    surface.write_parquet(root / "b1.parquet")

    flow = pl.DataFrame(
        {
            "asset": ["AAPL", "MSFT"],
            "session_date": ["2026-01-05", "2026-01-05"],
            "origin_minute": [30, 30],
            "b2_5m_premium": [1000.0, 2000.0],
        }
    )
    flow.write_parquet(root / "b2.parquet")

    merged = load_merged_panel(root / "b0.parquet", root / "b1.parquet", root / "b2.parquet")
    assert merged.height == base.height
    assert set(JOIN_KEYS) <= set(merged.columns)
    assert "b1_iv_30d" in merged.columns
    # Rows without a surface match keep a null rather than being dropped.
    assert merged["b1_iv_30d"].null_count() == 2


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
