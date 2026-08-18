"""Merged B0/B1/B2 research panel and the design matrices built from it.

One place decides what belongs to each nested information set and how each column is
transformed, so that Blocks 7-11 all see exactly the same B0, B1 and B2 definitions.
"""

from __future__ import annotations

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
}

B1_FEATURES: Final[dict[str, str]] = {
    "b1_iv_7d": "log",
    "b1_iv_14d": "log",
    "b1_iv_30d": "log",
    "b1_iv_60d": "log",
    "b1_iv_90d": "log",
    "b1_term_slope": "raw",
    "b1_term_convexity": "raw",
    "b1_smile_slope": "raw",
    "b1_smile_curvature": "raw",
    "b1_smile_residual": "raw",
    "b1_risk_reversal_25": "raw",
    "b1_butterfly_25": "raw",
    "b1_mfiv": "log",
    "b1_vrp_30d": "signed",
    "b1_median_relative_spread": "log",
    "b1_median_quote_age_s": "log",
    "b1_strikes": "log",
    "b1_expiries": "log",
    "b1_pcp_residual": "log",
}

_B2_WINDOWS: Final[tuple[str, ...]] = ("5m", "30m")
_B2_LEVELS: Final[tuple[str, ...]] = ("trades", "contracts", "size", "premium")
_B2_SIGNED: Final[tuple[str, ...]] = (
    "vega_flow", "gamma_flow", "delta_flow", "vega_flow_call", "vega_flow_put",
    "vega_flow_short_dte", "vega_flow_long_dte", "d_iv", "d_mid_rel", "d_spread",
    "hawkes_innovation",
)
_B2_RAW: Final[tuple[str, ...]] = (
    "otm_premium_share", "buy_premium_share", "sell_premium_share",
    "passive_premium_share", "sweep_premium_share", "strike_hhi", "expiry_hhi",
    "contract_entropy", "interarrival_cv",
)
_B2_LOG: Final[tuple[str, ...]] = ("vega_flow_abs", "hawkes_last", "rate_per_second")


def b2_features() -> dict[str, str]:
    """B2 column-to-transform map, generated for both aggregation windows."""

    mapping: dict[str, str] = {}
    for window in _B2_WINDOWS:
        for name in _B2_LEVELS + _B2_LOG:
            mapping[f"b2_{window}_{name}"] = "log"
        for name in _B2_SIGNED:
            mapping[f"b2_{window}_{name}"] = "signed"
        for name in _B2_RAW:
            mapping[f"b2_{window}_{name}"] = "raw"
    return mapping


B2_FEATURES: Final[dict[str, str]] = b2_features()

INFORMATION_SETS: Final[dict[str, dict[str, str]]] = {
    "B0": B0_FEATURES,
    "B1": B1_FEATURES,
    "B2": B2_FEATURES,
}


def load_merged_panel(b0_path: Path, b1_path: Path, b2_path: Path) -> pl.DataFrame:
    """Left-join the surface and flow panels onto the B0 panel on the origin key."""

    panel = pl.read_parquet(b0_path)
    for path in (b1_path, b2_path):
        if not path.is_file():
            continue
        other = pl.read_parquet(path)
        panel = panel.join(other, on=list(JOIN_KEYS), how="left")
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

    Columns absent from the panel are skipped and reported through the returned names, so a
    partially built panel degrades to a smaller design rather than crashing.
    """

    blocks: list[FloatArray] = []
    names: list[str] = []
    if intercept:
        blocks.append(np.ones(panel.height, dtype=np.float64))
        names.append("intercept")
    for mapping in feature_maps:
        for column, kind in mapping.items():
            if column not in panel.columns:
                continue
            values = np.asarray(panel[column].cast(pl.Float64).to_numpy(), dtype=np.float64)
            blocks.append(transform_column(values, kind))
            names.append(column)
    if not blocks:
        raise ValueError("RP2_PANEL_EMPTY_DESIGN")
    return np.column_stack(blocks), tuple(names)


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
