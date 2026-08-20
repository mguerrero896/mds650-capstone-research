"""Fold-local imputation, standardisation and missingness indicators.

Two failures this replaces, and they pull in opposite directions.

**Dropping a row because a secondary feature is missing.** A nested contrast has to be
scored on one set of rows, so a single missing B1 diagnostic removed that origin from B0's
evaluation as well. The larger information set then looks worse than it is on a sample it
did not choose, and the smaller one is credited with rows the comparison never used.

**Imputing with information from the rows being scored.** A median taken over the whole
panel carries the validation rows into the training statistics. It is a small leak and it is
still a leak: the model is told something about the sample it is about to be judged on.

The answer to both is the same object. Statistics are fitted on the training rows of the
fold, applied to every row, and the fact that a value was absent is kept as its own column
rather than being dissolved into the median.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.rp2.feature_registry import transforms

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]

#: Suffix of the column that records whether a feature was present at that origin.
MISSING_SUFFIX: Final = "__missing"
#: A feature with no spread in training would divide by zero; it is left unscaled instead.
MINIMUM_SCALE: Final = 1e-12


@dataclass(frozen=True, slots=True)
class FittedPreprocessor:
    """Everything learned from the training rows of one fold, and nothing else."""

    medians: dict[str, float]
    means: dict[str, float]
    scales: dict[str, float]
    missing_indicator_features: tuple[str, ...]
    features: tuple[str, ...] = field(default=())

    def column_names(self, *, intercept: bool = True) -> tuple[str, ...]:
        """The design's columns, in the order ``transform_features`` produces them."""

        head = ("intercept",) if intercept else ()
        indicators = tuple(f"{name}{MISSING_SUFFIX}" for name in self.missing_indicator_features)
        return head + self.features + indicators


def _transformed(frame: pl.DataFrame, features: Sequence[str]) -> FloatArray:
    """The registry's transform applied column by column, missingness preserved as NaN."""

    from mds650.rp2.panel import transform_column

    kinds = transforms()
    columns: list[FloatArray] = []
    for name in features:
        if name not in frame.columns:
            raise ValueError(f"RP2_PREPROCESS_MISSING_COLUMN:{name}")
        values = np.asarray(frame[name].cast(pl.Float64).to_numpy(), dtype=np.float64)
        present = np.isfinite(values)
        out = np.full(values.shape, np.nan, dtype=np.float64)
        if present.any():
            out[present] = transform_column(values[present], kinds[name])
        columns.append(out)
    return np.column_stack(columns) if columns else np.empty((frame.height, 0))


def fit_preprocessor(
    frame: pl.DataFrame, features: Sequence[str], train_mask: BoolArray
) -> FittedPreprocessor:
    """Learn medians, centres and scales from the training rows of this fold alone.

    A feature that is ever absent in training earns a missingness indicator. A feature that
    is complete in training does not: adding a column that is constant by construction costs
    a degree of freedom and says nothing. Its absence at scoring time is imputed with the
    training median, and the run records that this happened rather than discovering it later.
    """

    if train_mask.shape[0] != frame.height:
        raise ValueError("RP2_PREPROCESS_TRAIN_MASK_SHAPE")
    if not train_mask.any():
        raise ValueError("RP2_PREPROCESS_EMPTY_TRAIN")

    values = _transformed(frame, features)
    train = values[train_mask]
    medians: dict[str, float] = {}
    means: dict[str, float] = {}
    scales: dict[str, float] = {}
    indicators: list[str] = []
    for index, name in enumerate(features):
        column = train[:, index]
        present = np.isfinite(column)
        if not present.any():
            raise ValueError(f"RP2_PREPROCESS_FEATURE_ABSENT_IN_TRAIN:{name}")
        median = float(np.median(column[present]))
        filled = np.where(present, column, median)
        medians[name] = median
        means[name] = float(filled.mean())
        spread = float(filled.std())
        scales[name] = spread if spread > MINIMUM_SCALE else 1.0
        if not present.all():
            indicators.append(name)
    return FittedPreprocessor(
        medians=medians,
        means=means,
        scales=scales,
        missing_indicator_features=tuple(indicators),
        features=tuple(features),
    )


def transform_features(
    frame: pl.DataFrame,
    features: Sequence[str],
    fitted: FittedPreprocessor,
    *,
    intercept: bool = True,
) -> FloatArray:
    """Impute, standardise and append the missingness indicators, using fitted statistics.

    Nothing here is learned from ``frame``. The same fitted object applied to the training
    rows and to the scored rows is what makes the two comparable.
    """

    if tuple(features) != fitted.features:
        raise ValueError("RP2_PREPROCESS_FEATURE_MISMATCH")
    values = _transformed(frame, features)
    blocks: list[FloatArray] = []
    if intercept:
        blocks.append(np.ones(frame.height, dtype=np.float64))
    for index, name in enumerate(features):
        column = values[:, index]
        present = np.isfinite(column)
        filled = np.where(present, column, fitted.medians[name])
        blocks.append((filled - fitted.means[name]) / fitted.scales[name])
    for name in fitted.missing_indicator_features:
        index = features.index(name)
        blocks.append((~np.isfinite(values[:, index])).astype(np.float64))
    return np.column_stack(blocks)


def describe_preprocessor(fitted: FittedPreprocessor) -> dict[str, object]:
    """What a run must record about the statistics it imputed and scaled with."""

    return {
        "features": list(fitted.features),
        "missing_indicator_features": list(fitted.missing_indicator_features),
        "imputed_feature_count": len(fitted.missing_indicator_features),
        "medians": dict(fitted.medians),
        "means": dict(fitted.means),
        "scales": dict(fitted.scales),
    }


def fold_design(
    frame: pl.DataFrame,
    features: Sequence[str],
    train_mask: BoolArray,
    *,
    intercept: bool = True,
) -> tuple[FloatArray, tuple[str, ...], FittedPreprocessor]:
    """Fit on this fold's training rows and transform every row, in one call.

    The two steps belong together: a design standardised with statistics from a different
    fold, or imputed with a median that saw the scored rows, is not the design the fit
    believed it had.
    """

    fitted = fit_preprocessor(frame, features, train_mask)
    design = transform_features(frame, features, fitted, intercept=intercept)
    return design, fitted.column_names(intercept=intercept), fitted
