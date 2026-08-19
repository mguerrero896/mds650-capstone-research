"""Merged B0/B1/B2 research panel and the design matrices built from it.

One place decides what belongs to each nested information set and how each column is
transformed, so that Blocks 7-11 all see exactly the same B0, B1 and B2 definitions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
import polars as pl

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.int64]

JOIN_KEYS: Final[tuple[str, ...]] = ("asset", "session_date", "origin_minute")
TARGET: Final = "rv30"
VARIANCE_FLOOR: Final = 1e-12

#: B0 columns and how to transform them. ``log`` for strictly positive levels, ``signed``
#: for quantities that take either sign over many orders of magnitude, ``raw`` otherwise.
B0_FEATURES: Final[dict[str, str]] = {
    "rv_back_5": "log",
    "rv_back_15": "log",
    "rv_back_30": "log",
    "rq_back_30": "log",
    "rs_up_back_30": "log",
    "rs_down_back_30": "log",
    "jump_back_30": "log",
    "rv_session_to_date": "log",
    "rv_prev_day": "log",
    "rv_week": "log",
    "parkinson_30": "log",
    "volume_30": "log",
    "dollar_volume_30": "log",
    "ret_5": "raw",
    "ret_30": "raw",
    "minutes_since_open": "raw",
    "minutes_to_close": "raw",
    "day_of_week": "raw",
    # Market-wide state. These columns were built into the panel from the start and were
    # never registered, so every block downstream of 4 ran a B0 that could not see the
    # market at all — the ladder's own `b0_market` variant was the only thing using them.
    # A B2 increment measured against a baseline blind to SPY and QQQ credits option flow
    # with whatever the market was doing at the time.
    "SPY_rv_30": "log",
    "SPY_ret_30": "raw",
    "QQQ_rv_30": "log",
    "QQQ_ret_30": "raw",
}

#: B1-core: the primary option-state set, ten high-coverage features. Everything else the
#: surface emits is B1-rich — reported, hashed and available, but out of the primary set,
#: because a feature present on 60% of origins removes 40% of the evaluation rows from
#: every nested contrast that includes it. See docs/rp2_v3/B1_CONTEMPORANEOUS_SPEC.md.
B1_FEATURES: Final[dict[str, str]] = {
    "b1_iv_7d": "log",
    "b1_iv_30d": "log",
    "b1_iv_60d": "log",
    "b1_term_slope": "raw",
    "b1_smile_level": "log",
    "b1_risk_reversal_25": "raw",
    "b1_median_relative_spread": "log",
    "b1_median_quote_age_s": "log",
    "b1_surface_coverage": "raw",
    "b1_iv_minus_trailing_rv_30d": "signed",
}

_B2_WINDOWS: Final[tuple[str, ...]] = ("5m", "30m")
_B2_LEVELS: Final[tuple[str, ...]] = ("trades", "contracts", "size", "premium")
_B2_SIGNED: Final[tuple[str, ...]] = (
    "vega_flow",
    "gamma_flow",
    "delta_flow",
    "vega_flow_call",
    "vega_flow_put",
    "vega_flow_short_dte",
    "vega_flow_long_dte",
    "d_iv",
    "d_mid_rel",
    "d_spread",
    "decay_intensity_innovation",
)
_B2_RAW: Final[tuple[str, ...]] = (
    "otm_premium_share",
    "buy_premium_share",
    "sell_premium_share",
    "passive_premium_share",
    "sweep_premium_share",
    "late_arrival_share",
    "multileg_size_share",
    "multileg_premium_share",
)
#: Concentration and arrival-shape statistics are not prefix-summable, so the builder
#: computes them on the concentration window only. Registering them for every window
#: claimed four features that cannot exist — and `build_design` skips absent columns
#: silently, so the claim went unnoticed for the whole programme.
_B2_CONCENTRATION: Final[tuple[str, ...]] = (
    "strike_hhi",
    "expiry_hhi",
    "contract_entropy",
    "interarrival_cv",
)
#: The window those statistics are computed on; must match the builder's own constant.
_B2_CONCENTRATION_WINDOW: Final = "5m"
_B2_LOG: Final[tuple[str, ...]] = (
    "vega_flow_abs",
    "decay_intensity_last",
    "rate_per_second",
    "mean_latency_s",
)


def b2_features() -> dict[str, str]:
    """B2 column-to-transform map: per-window features, plus the concentration window."""

    mapping: dict[str, str] = {}
    for window in _B2_WINDOWS:
        for name in _B2_LEVELS + _B2_LOG:
            mapping[f"b2_{window}_{name}"] = "log"
        for name in _B2_SIGNED:
            mapping[f"b2_{window}_{name}"] = "signed"
        for name in _B2_RAW:
            mapping[f"b2_{window}_{name}"] = "raw"
    for name in _B2_CONCENTRATION:
        mapping[f"b2_{_B2_CONCENTRATION_WINDOW}_{name}"] = "raw"
    return mapping


B2_FEATURES: Final[dict[str, str]] = b2_features()

INFORMATION_SETS: Final[dict[str, dict[str, str]]] = {
    "B0": B0_FEATURES,
    "B1": B1_FEATURES,
    "B2": B2_FEATURES,
}


def load_merged_panel(b0_path: Path, b1_path: Path, b2_path: Path) -> pl.DataFrame:
    """Left-join the surface and flow panels onto the B0 panel on the origin key.

    Every input is required. Skipping an absent file let a run keep its name while losing a
    whole information set: a rebuild launched as ``B0+B1+B2`` after a failed B2 build would
    quietly produce a B0+B1 panel, and every artifact downstream would still be labelled
    B0+B1+B2. There is no reading of the result that recovers what was missing.
    """

    for label, path in (("B1", b1_path), ("B2", b2_path)):
        if not path.is_file():
            raise FileNotFoundError(f"RP2_PANEL_INPUT_MISSING:{label}:{path}")
    panel = pl.read_parquet(b0_path)
    assert_unique_origin_key(panel)
    for path in (b1_path, b2_path):
        other = pl.read_parquet(path)
        joined = panel.join(other, on=list(JOIN_KEYS), how="left")
        assert_one_to_one_join(panel, other, joined)
        panel = joined
    return panel


def transform_column(values: FloatArray, kind: str) -> FloatArray:
    """Apply the registered transform, keeping every output finite where the input is."""

    if kind == "log":
        return np.log(np.maximum(values, VARIANCE_FLOOR))
    if kind == "signed":
        return np.sign(values) * np.log1p(np.abs(values))
    if kind == "raw":
        return values
    raise ValueError("RP2_PANEL_UNKNOWN_TRANSFORM")


def build_design(
    panel: pl.DataFrame, feature_maps: list[dict[str, str]], *, intercept: bool = True
) -> tuple[FloatArray, tuple[str, ...]]:
    """Stack the requested information sets into one design matrix.

    Every registered column must be present. A design silently missing features is a design
    that no longer is the information set it is named after, and the run that used it still
    reports the name. `assert_required_columns` has existed for this since the panel was
    written and had no caller anywhere in production until now.
    """

    blocks: list[FloatArray] = []
    names: list[str] = []
    if intercept:
        blocks.append(np.ones(panel.height, dtype=np.float64))
        names.append("intercept")
    for mapping in feature_maps:
        assert_required_columns(panel, list(mapping))
        for column, kind in mapping.items():
            values = np.asarray(panel[column].cast(pl.Float64).to_numpy(), dtype=np.float64)
            blocks.append(transform_column(values, kind))
            names.append(column)
    if not blocks:
        raise ValueError("RP2_PANEL_EMPTY_DESIGN")
    return np.column_stack(blocks), tuple(names)


def common_usable_rows(
    designs: Mapping[str, FloatArray], target: FloatArray
) -> npt.NDArray[np.bool_]:
    """Rows every design in a nested comparison can be scored on.

    A base model evaluated on rows the expanded model had to drop is being handed an easier
    sample, and the increment between them then measures the sample as much as the
    information. One mask, intersected across every set in the contrast, is the only way the
    difference of two losses is a difference in information.
    """

    if not designs:
        raise ValueError("RP2_PANEL_NO_DESIGNS")
    mask = np.ones(target.shape[0], dtype=np.bool_)
    for name, design in designs.items():
        if design.shape[0] != target.shape[0]:
            raise ValueError(f"RP2_PANEL_DESIGN_ROWS:{name}")
        mask &= usable_rows(design, target)
    return mask


def lift_mask(
    base: npt.NDArray[np.bool_], selected: npt.NDArray[np.bool_]
) -> npt.NDArray[np.bool_]:
    """Map a mask defined over the rows ``base`` kept back onto the original row space.

    Every block filters the panel down to its usable rows and then splits that subset into
    train and test. The rows a run actually scored are therefore a mask over the subset,
    while the provenance has to describe the panel; without lifting, two runs that scored
    different sessions would record the same evaluation mask.
    """

    if int(base.sum()) != selected.shape[0]:
        raise ValueError("RP2_PANEL_MASK_LIFT_SHAPE")
    out = np.zeros(base.shape[0], dtype=np.bool_)
    out[np.flatnonzero(base)[selected]] = True
    return out


def mask_sha256(mask: npt.NDArray[np.bool_]) -> str:
    """Content hash of an evaluation mask.

    A row count cannot identify a mask: two contrasts can keep the same number of rows and
    not the same rows. The hash travels with every artifact so that claim is checkable.
    """

    return hashlib.sha256(np.ascontiguousarray(mask, dtype=np.bool_).tobytes()).hexdigest()


def describe_information_set(
    requested: Sequence[str], resolved: Sequence[str], mask: npt.NDArray[np.bool_]
) -> dict[str, object]:
    """The provenance every artifact must carry about the design it was fitted on.

    Without it, a document can call a run ``B0+B1+B2`` and nothing in the artifact says how
    many features that actually resolved to, or which rows were scored.

    The intercept is recorded as a flag rather than as a feature. Counting it would make a
    22-feature registry report 23 resolved, and the exit criterion of this gate is that
    resolved equals registered — a comparison the record has to be able to support directly.
    """

    features = [name for name in resolved if name != "intercept"]
    # A label that names a registry has to mean that whole registry. Calling a ten-feature
    # treatment subset ``B2`` makes the requested-versus-resolved comparison read as
    # ninety-six silently missing features, which is the very check this record exists for.
    for label in requested:
        for part in label.split("+"):
            registry = INFORMATION_SETS.get(part)
            if registry is not None and not set(registry) <= set(features):
                raise ValueError(f"RP2_PANEL_INFORMATION_SET_MISLABELLED:{part}")
    return {
        "requested_information_set": list(requested),
        "resolved_feature_names": features,
        "feature_count": len(features),
        "includes_intercept": "intercept" in resolved,
        "evaluation_mask_sha256": mask_sha256(mask),
    }


def session_rank(sessions: npt.NDArray[np.str_]) -> IntArray:
    """Dense integer rank of each row's session date, ordered in time."""

    unique = np.unique(sessions)
    lookup = {value: index for index, value in enumerate(unique)}
    return np.array([lookup[value] for value in sessions], dtype=np.int64)


def usable_rows(design: FloatArray, target: FloatArray) -> npt.NDArray[np.bool_]:
    """Rows with a strictly positive target and a fully finite design."""

    return np.isfinite(design).all(axis=1) & np.isfinite(target) & (target > 0.0)


def chronological_split(
    session_index: IntArray, *, train_share: float
) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
    """Split by session, never by row: the first ``train_share`` of sessions trains."""

    if not 0.0 < train_share < 1.0:
        raise ValueError("RP2_PANEL_TRAIN_SHARE_INVALID")
    unique = np.unique(session_index)
    boundary = unique[int(len(unique) * train_share)]
    return session_index < boundary, session_index >= boundary


def standardise(
    design: FloatArray, train: npt.NDArray[np.bool_], *, has_intercept: bool = True
) -> FloatArray:
    """Z-score every non-intercept column using training statistics only.

    GLMs, ridge and spline bases are all scale-sensitive, and the raw panel mixes
    log-variances near -20 with minute counts near 350.  Trees are unaffected but see the
    same matrix, which keeps every family comparable on identical inputs.
    """

    if design.ndim != 2 or train.shape[0] != design.shape[0]:
        raise ValueError("RP2_PANEL_STANDARDISE_SHAPE")
    if not train.any():
        raise ValueError("RP2_PANEL_STANDARDISE_EMPTY_TRAIN")
    out = design.copy()
    start = 1 if has_intercept else 0
    block = design[train, start:]
    centre = block.mean(axis=0)
    spread = block.std(axis=0)
    spread = np.where(spread > 0.0, spread, 1.0)
    out[:, start:] = (design[:, start:] - centre) / spread
    return out


def assert_unique_origin_key(panel: pl.DataFrame) -> None:
    """Fail closed unless ``(asset, session_date, origin_minute)`` identifies one row.

    A duplicated origin key silently double-weights that origin in every mean, every
    bootstrap and every regression downstream, and nothing later in the pipeline would
    surface it.
    """

    missing = [name for name in JOIN_KEYS if name not in panel.columns]
    if missing:
        raise ValueError(f"RP2_PANEL_ORIGIN_KEY_MISSING:{','.join(missing)}")
    duplicates = panel.height - panel.select(JOIN_KEYS).unique().height
    if duplicates:
        raise ValueError(f"RP2_PANEL_ORIGIN_KEY_DUPLICATED:{duplicates}")


def assert_one_to_one_join(left: pl.DataFrame, right: pl.DataFrame, joined: pl.DataFrame) -> None:
    """Fail closed unless a left join neither dropped nor multiplied rows.

    A right side with a duplicated key silently fans the panel out, which looks like more
    data and is really the same origin counted twice.
    """

    if joined.height != left.height:
        raise ValueError(f"RP2_PANEL_JOIN_CARDINALITY:{left.height}->{joined.height}")
    duplicates = right.height - right.select(JOIN_KEYS).unique().height
    if duplicates:
        raise ValueError(f"RP2_PANEL_JOIN_RIGHT_DUPLICATED:{duplicates}")


def assert_required_columns(panel: pl.DataFrame, required: Sequence[str]) -> None:
    """Fail closed on a missing required column instead of silently degrading."""

    missing = [name for name in required if name not in panel.columns]
    if missing:
        raise ValueError(f"RP2_PANEL_REQUIRED_MISSING:{','.join(sorted(missing))}")
