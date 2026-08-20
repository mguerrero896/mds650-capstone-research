"""Fold-local imputation: what the training rows may teach, and what they may not."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from mds650.rp2.preprocessing import (
    MISSING_SUFFIX,
    describe_preprocessor,
    fit_preprocessor,
    transform_features,
)

FEATURES = ("b1_iv_30d", "b1_term_slope")


def _frame(iv: list[float | None], slope: list[float | None]) -> pl.DataFrame:
    return pl.DataFrame({"b1_iv_30d": iv, "b1_term_slope": slope})


def test_imputation_uses_training_rows_only() -> None:
    """The median that fills a gap comes from the rows the model was allowed to see."""

    frame = _frame([0.20, 0.30, 0.40, None], [0.0, 0.0, 0.0, 0.0])
    train = np.array([True, True, True, False])
    fitted = fit_preprocessor(frame, FEATURES, train)
    assert fitted.medians["b1_iv_30d"] == pytest.approx(np.log(0.30))

    # The same panel with a wildly different validation row teaches nothing new.
    other = _frame([0.20, 0.30, 0.40, 900.0], [0.0, 0.0, 0.0, 0.0])
    assert fit_preprocessor(other, FEATURES, train).medians == fitted.medians


def test_validation_extreme_values_do_not_change_training_median() -> None:
    """A leak here is small and is still a leak."""

    train = np.array([True, True, True, True, False, False])
    calm = _frame([0.2, 0.3, 0.4, 0.5, 0.31, 0.32], [0.0] * 6)
    wild = _frame([0.2, 0.3, 0.4, 0.5, 1e4, 1e-4], [0.0] * 6)
    left = fit_preprocessor(calm, FEATURES, train)
    right = fit_preprocessor(wild, FEATURES, train)
    assert left.medians == right.medians
    assert left.means == right.means
    assert left.scales == right.scales


def test_missing_indicator_preserves_missingness_information() -> None:
    """An imputed median and an observed median are not the same evidence."""

    frame = _frame([0.20, None, 0.40, None], [0.1, 0.2, 0.3, 0.4])
    train = np.array([True, True, True, False])
    fitted = fit_preprocessor(frame, FEATURES, train)
    assert fitted.missing_indicator_features == ("b1_iv_30d",)

    design = transform_features(frame, FEATURES, fitted)
    names = fitted.column_names()
    assert names == ("intercept", "b1_iv_30d", "b1_term_slope", f"b1_iv_30d{MISSING_SUFFIX}")
    indicator = design[:, names.index(f"b1_iv_30d{MISSING_SUFFIX}")]
    assert indicator.tolist() == [0.0, 1.0, 0.0, 1.0]
    # The imputed rows carry the training median, which after centring is not zero unless
    # the median happens to be the mean.
    imputed = design[:, names.index("b1_iv_30d")]
    assert imputed[1] == pytest.approx(imputed[3])
    assert np.isfinite(design).all()


def test_a_feature_complete_in_training_earns_no_indicator() -> None:
    """A column that is constant by construction costs a degree of freedom and says nothing."""

    frame = _frame([0.2, 0.3, 0.4, None], [0.1, 0.2, 0.3, 0.4])
    train = np.array([True, True, True, False])
    fitted = fit_preprocessor(frame, FEATURES, train)
    assert fitted.missing_indicator_features == ()
    design = transform_features(frame, FEATURES, fitted)
    assert design.shape == (4, 3)
    # The scored row is imputed with the training median rather than dropped.
    assert np.isfinite(design).all()


def test_nothing_is_learned_from_the_rows_being_scored() -> None:
    """The transform is a function of the fitted object, not of the frame it is given."""

    train = np.array([True, True, True, False])
    frame = _frame([0.2, 0.3, 0.4, 0.5], [0.1, 0.2, 0.3, 0.4])
    fitted = fit_preprocessor(frame, FEATURES, train)

    left = transform_features(frame, FEATURES, fitted)
    moved = _frame([0.2, 0.3, 0.4, 5000.0], [0.1, 0.2, 0.3, 0.4])
    right = transform_features(moved, FEATURES, fitted)
    assert np.allclose(left[:3], right[:3]), "an unrelated row changed the training rows"


def test_the_preprocessor_refuses_what_it_cannot_fit() -> None:
    frame = _frame([0.2, 0.3], [0.1, 0.2])
    with pytest.raises(ValueError, match="RP2_PREPROCESS_TRAIN_MASK_SHAPE"):
        fit_preprocessor(frame, FEATURES, np.ones(3, dtype=bool))
    with pytest.raises(ValueError, match="RP2_PREPROCESS_EMPTY_TRAIN"):
        fit_preprocessor(frame, FEATURES, np.zeros(2, dtype=bool))
    with pytest.raises(ValueError, match="RP2_PREPROCESS_MISSING_COLUMN:absent"):
        fit_preprocessor(frame, ("absent",), np.ones(2, dtype=bool))
    blank = _frame([None, None], [0.1, 0.2])
    with pytest.raises(ValueError, match="RP2_PREPROCESS_FEATURE_ABSENT_IN_TRAIN"):
        fit_preprocessor(blank, FEATURES, np.ones(2, dtype=bool))

    fitted = fit_preprocessor(frame, FEATURES, np.ones(2, dtype=bool))
    with pytest.raises(ValueError, match="RP2_PREPROCESS_FEATURE_MISMATCH"):
        transform_features(frame, ("b1_term_slope",), fitted)


def test_a_constant_feature_is_left_unscaled_rather_than_divided_by_zero() -> None:
    frame = pl.DataFrame({"b1_iv_30d": [0.3, 0.3, 0.3], "b1_term_slope": [0.1, 0.2, 0.3]})
    fitted = fit_preprocessor(frame, FEATURES, np.ones(3, dtype=bool))
    assert fitted.scales["b1_iv_30d"] == 1.0
    design = transform_features(frame, FEATURES, fitted)
    assert np.isfinite(design).all()
    assert np.allclose(design[:, 1], 0.0)


def test_the_run_record_names_what_was_imputed() -> None:
    frame = _frame([0.2, None, 0.4], [0.1, 0.2, 0.3])
    fitted = fit_preprocessor(frame, FEATURES, np.ones(3, dtype=bool))
    record = describe_preprocessor(fitted)
    assert record["missing_indicator_features"] == ["b1_iv_30d"]
    assert record["imputed_feature_count"] == 1
    assert set(record["medians"]) == set(FEATURES)  # type: ignore[arg-type]


def test_b0_b1_b2_are_evaluated_on_the_same_common_rows() -> None:
    """One mask for the whole contrast, and it is not "every design column is finite".

    That rule let a missing B1 diagnostic remove the origin from B0's evaluation too, so the
    larger information set was judged on a sample its own missingness had chosen.
    """

    from mds650.rp2.panel import (
        B0_FEATURES,
        B1_FEATURES,
        B2_FEATURES,
        common_evaluation_mask,
        common_usable_rows,
    )

    rows = 6
    frame = pl.DataFrame(
        {
            "asset": ["AAA"] * rows,
            "session_date": ["2026-01-05"] * rows,
            "origin_minute": list(range(30, 30 + rows)),
            "rv30": [1e-5] * rows,
            **{name: [1.0] * rows for name in B0_FEATURES},
            **{name: [1.0] * rows for name in B1_FEATURES},
            **{name: [1.0] * rows for name in B2_FEATURES},
            # Availability is a panel property rather than a fitted feature.
            "b2_5m_is_empty_window": [0.0] * rows,
        }
    )
    # One origin is missing a single B1 feature. Its surface and its flow window both exist.
    frame = frame.with_columns(b1_term_slope=pl.Series([1.0, None, 1.0, 1.0, 1.0, 1.0]))
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)

    mask = common_evaluation_mask(frame, target)
    assert mask.all(), "an imputable gap is not an availability failure"

    # The old rule drops that origin from every set in the contrast, B0 included.
    from mds650.rp2.panel import build_design

    designs = {
        "B0": build_design(frame, [B0_FEATURES])[0],
        "B0+B1": build_design(frame, [B0_FEATURES, B1_FEATURES])[0],
    }
    assert int(common_usable_rows(designs, target).sum()) == rows - 1

    # And an origin with no option data at all is still excluded, because that is
    # availability rather than missingness.
    unavailable = frame.with_columns(
        b1_surface_coverage=pl.Series([1.0, 1.0, None, 1.0, 1.0, 1.0])
    )
    assert int(common_evaluation_mask(unavailable, target).sum()) == rows - 1


def test_the_common_mask_refuses_a_panel_without_its_availability_columns() -> None:
    from mds650.rp2.panel import common_evaluation_mask

    frame = pl.DataFrame(
        {
            "asset": ["AAA"],
            "session_date": ["2026-01-05"],
            "origin_minute": [30],
            "b1_surface_coverage": [1.0],
        }
    )
    with pytest.raises(ValueError, match="RP2_PANEL_AVAILABILITY_MISSING:b2_5m_is_empty_window"):
        common_evaluation_mask(frame, np.array([1e-5]))


#: The blocks whose primary contrasts must use the common mask and the fold-local design.
PRIMARY_BLOCKS: tuple[str, ...] = (
    "rp2_block8_ladder",
    "rp2_block9_generalization",
    "rp2_block10_inference",
    "rp2_block11_economics",
    "rp2_block11b_forward_economics",
    "rp2_block12_prospective_design",
)


def test_every_primary_block_uses_the_common_mask_and_fold_local_statistics() -> None:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    for name in PRIMARY_BLOCKS:
        source = (repo / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert "common_evaluation_mask(frame, target)" in source, name
        assert "fold_design(frame, features[name], train)" in source, name
        assert "common_usable_rows(designs" not in source, name
        assert "standardise(designs" not in source, name


def test_a_held_out_asset_fold_refits_its_own_statistics() -> None:
    """Passing a narrower training mask to the model cannot undo what the design learned.

    A leave-one-asset-out design imputed and scaled with statistics that saw the held-out
    asset's history is not an unseen-asset result, however the model is then fitted.
    """

    from pathlib import Path as _Path

    source = (
        _Path(__file__).resolve().parents[2] / "scripts" / "rp2_block9_generalization.py"
    ).read_text(encoding="utf-8")
    loop = source[source.index("for asset in sorted(") :]
    assert "fold_design(frame, features[set_name], asset_train)" in loop, (
        "the held-out fold must refit its own preprocessing"
    )
    assert "fitter(designs[set_name], target, asset_train)" not in loop

    # And the statistics really do differ once the held-out rows are excluded.
    frame = _frame([0.2, 0.3, 0.4, 50.0], [0.1, 0.2, 0.3, 0.4])
    everything = np.ones(4, dtype=bool)
    without_last = np.array([True, True, True, False])
    assert (
        fit_preprocessor(frame, FEATURES, everything).medians
        != fit_preprocessor(frame, FEATURES, without_last).medians
    )


def test_every_block_records_the_statistics_it_fitted_with() -> None:
    """Computed and never written is the same as not computed, for an audit."""

    from pathlib import Path as _Path

    repo = _Path(__file__).resolve().parents[2]
    for name in PRIMARY_BLOCKS:
        source = (repo / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert "preprocessors[name] = describe_preprocessor(fitted)" in source, name
        assert '"preprocessing": preprocessors' in source, name
