"""Extension 1 - is the Block 7 mechanism useful for anything other than RV30 level?

Block 7 found that two option-flow features carry information beyond B0+B1: the Hawkes
burst-intensity innovation and the buyer-initiated premium share.  Block 8 found that
information does not improve a level forecast of RV30.  This asks whether it is useful for
three *different* jobs, each of which a level forecast is the wrong instrument for:

A. **Other targets.** Does the mechanism speak to a horizon, a component, or a direction
   that RV30 does not?
B. **Regime / attention.** Can it flag that the next thirty minutes will be in the tail,
   which is a classification question, not a level question?
C. **Execution timing.** Can it *rank* origins by how violent they are about to be? An
   execution desk does not need a calibrated variance; it needs to know which window is
   worse than the others, and rank information is not level information.

EXPLORATORY. This is a battery of new tests on already-observed data, so every family
carries Holm adjustment and the test count is reported with the results.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
from scipy import stats
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from mds650.b1v3_confirmation import canonical_sha256
from mds650.metrics import holm_adjust
from mds650.rp2.bars import FULL_SESSION_MINUTES, build_session_grid, load_bar_sources
from mds650.rp2.dml import cross_fitted_residuals, dml_partial_out, time_block_folds
from mds650.rp2.feature_registry import describe_features, feature_map
from mds650.rp2.ladder import LADDER
from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    VARIANCE_FLOOR,
    build_design,
    chronological_split,
    common_usable_rows,
    describe_information_set,
    lift_mask,
    load_merged_panel,
    mask_sha256,
    session_rank,
    standardise,
    usable_rows,
)
from mds650.rp2.preprocessing import describe_preprocessor, fold_design
from mds650.rp2.realized import backward_rv, forward_measures, log_returns

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_ext1_mechanism_utility"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"

#: The two treatments that replicated across universes in Block 7, plus the eight others
#: from the core block so the joint test is comparable to Block 7's.
#: The sets this extension actually fits. Its battery predates the core/rich split and
#: includes rich channels, so a record built from the core sets alone would omit
#: variables that were fitted.
FITTED_SETS: tuple[str, ...] = ("B0_CORE", "B1_CORE", "B2_CORE", "B2_RICH")

CORE_TREATMENTS: tuple[str, ...] = (
    "b2_5m_vega_flow",
    "b2_5m_gamma_flow",
    "b2_5m_delta_flow",
    "b2_5m_premium",
    "b2_5m_trades",
    "b2_5m_decay_intensity_innovation",
    "b2_5m_d_iv",
    "b2_5m_buy_premium_share",
    "b2_5m_strike_hhi",
    "b2_5m_otm_premium_share",
)
REPLICATED: tuple[str, ...] = ("b2_5m_decay_intensity_innovation", "b2_5m_buy_premium_share")
HORIZONS: tuple[int, ...] = (5, 15, 30, 60, 120)
TAIL_QUANTILE = 0.90
DECILES = 10

type FloatArray = npt.NDArray[np.float64]


# --------------------------------------------------------------------------- targets


def build_target_battery(
    data_root: Path, origins_by_key: dict[tuple[str, str], FloatArray]
) -> pl.DataFrame:
    """Forward realized measures at several horizons on the production origin grid."""

    bars = load_bar_sources(data_root)
    rows: list[pl.DataFrame] = []
    for (asset, session_date), group in bars.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        key = (str(asset), str(session_date))
        origins = origins_by_key.get(key)
        if origins is None:
            continue
        grid = build_session_grid(group, session=session_date)
        if grid.fill_share > 0.05 or grid.close.min() <= 0.0:
            continue
        returns = log_returns(grid.close)
        cumulative = np.concatenate([[0.0], np.cumsum(returns)])
        index = origins.astype(np.int64)
        record: dict[str, object] = {
            "asset": [str(asset)] * index.size,
            "session_date": [str(session_date)] * index.size,
            "origin_minute": index,
        }
        for horizon in HORIZONS:
            valid = index + horizon <= returns.size
            safe = np.where(valid, index, 0)
            measures = forward_measures(returns, safe, horizon)
            blank = np.full(index.size, np.nan)
            record[f"y_rv_{horizon}"] = np.where(valid, measures.rv, blank)
            record[f"y_jump_{horizon}"] = np.where(valid, measures.jump, blank)
            record[f"y_continuous_{horizon}"] = np.where(valid, measures.continuous, blank)
            record[f"y_rs_up_{horizon}"] = np.where(valid, measures.semivariance_up, blank)
            record[f"y_rs_down_{horizon}"] = np.where(valid, measures.semivariance_down, blank)
            forward_return = (
                cumulative[np.minimum(index + horizon, returns.size)] - cumulative[index]
            )
            record[f"y_signed_return_{horizon}"] = np.where(valid, forward_return, blank)
            record[f"y_abs_return_{horizon}"] = np.where(valid, np.abs(forward_return), blank)
        # Change in realized variance relative to the trailing window of equal length.
        back = backward_rv(returns, index, 30)
        record["y_rv_ratio_30"] = np.where(
            index + 30 <= returns.size,
            forward_measures(returns, np.where(index + 30 <= returns.size, index, 0), 30).rv
            / np.maximum(back, VARIANCE_FLOOR),
            np.nan,
        )
        rows.append(pl.DataFrame(record))
    if not rows:
        raise SystemExit("RP2_EXT1_EMPTY_TARGETS")
    return pl.concat(rows, how="vertical")


# ------------------------------------------------------------------- A: other targets


def _dml_on_target(
    nuisance: FloatArray,
    treatment: FloatArray,
    response: FloatArray,
    sessions: npt.NDArray[np.int64],
    names: tuple[str, ...],
    *,
    folds: int,
    evaluation_base: npt.NDArray[np.bool_],
) -> dict[str, object] | None:
    finite = np.isfinite(response)
    if int(finite.sum()) < 2000 or np.unique(sessions[finite]).size < 20:
        return None
    blocks = time_block_folds(sessions[finite], folds=folds, purge_sessions=1)
    response_residual = cross_fitted_residuals(nuisance[finite], response[finite], blocks)
    treatment_residual = np.column_stack(
        [
            cross_fitted_residuals(nuisance[finite], treatment[finite, index], blocks)
            for index in range(treatment.shape[1])
        ]
    )
    try:
        estimate = dml_partial_out(response_residual, treatment_residual, sessions[finite], names)
    except ValueError:
        return None
    return {
        "joint_wald": estimate.joint_statistic,
        "joint_p_value": estimate.joint_p_value,
        "rows": estimate.rows,
        "clusters": estimate.clusters,
        "evaluation_mask_sha256": mask_sha256(lift_mask(evaluation_base, finite)),
        "coefficients": {
            name: {"t": float(estimate.t_statistic[i]), "p": float(estimate.p_value[i])}
            for i, name in enumerate(estimate.treatment_names)
        },
    }


def target_battery(
    frame: pl.DataFrame,
    nuisance: FloatArray,
    treatment: FloatArray,
    sessions: npt.NDArray[np.int64],
    names: tuple[str, ...],
    *,
    folds: int,
    evaluation_base: npt.NDArray[np.bool_],
) -> dict[str, object]:
    """DML of the core B2 block against every alternative target.

    Each alternative target has its own availability, so each is fitted on its own rows.
    One mask hash for the battery would say that outcomes measured on different samples
    were measured on the same one.
    """

    results: dict[str, object] = {}
    raw_p: dict[str, float] = {}
    for column in sorted(c for c in frame.columns if c.startswith("y_")):
        values = np.asarray(frame[column].to_numpy(), dtype=np.float64)
        # Variance-like targets are tested on the log scale; returns on their own scale.
        if "return" in column and "abs" not in column:
            response = values
        elif "ratio" in column:
            response = np.log(np.maximum(values, VARIANCE_FLOOR))
        else:
            response = np.log(np.maximum(values, VARIANCE_FLOOR))
            response = np.where(values > 0.0, response, np.nan)
        outcome = _dml_on_target(
            nuisance,
            treatment,
            response,
            sessions,
            names,
            folds=folds,
            evaluation_base=evaluation_base,
        )
        if outcome is None:
            continue
        results[column] = outcome
        raw_p[column] = float(outcome["joint_p_value"])  # type: ignore[arg-type]
    if raw_p:
        adjusted = holm_adjust(raw_p)
        for column, value in adjusted.items():
            block = results[column]
            assert isinstance(block, dict)
            block["holm_p"] = value
        results["_family_size"] = len(raw_p)
    return results


# ------------------------------------------------------- B: regime / attention flagging


def tail_classification(
    target: FloatArray,
    designs: dict[str, FloatArray],
    train: npt.NDArray[np.bool_],
    test: npt.NDArray[np.bool_],
    assets: npt.NDArray[np.str_],
) -> dict[str, object]:
    """Can the mechanism flag that the next window lands in the variance tail?

    The tail threshold is per asset and estimated on training rows only, so a
    high-variance name does not define the tail for a quiet one.
    """

    label = np.zeros(target.size, dtype=bool)
    for asset in np.unique(assets):
        mask = assets == asset
        threshold = float(np.quantile(target[mask & train], TAIL_QUANTILE))
        label |= mask & (target > threshold)
    out: dict[str, object] = {
        "tail_quantile": TAIL_QUANTILE,
        "tail_rate_train": float(label[train].mean()),
        "tail_rate_test": float(label[test].mean()),
    }
    for name, design in designs.items():
        model = LogisticRegression(max_iter=2000, C=1.0)
        model.fit(standardise(design, train)[train], label[train])
        score = np.asarray(
            model.predict_proba(standardise(design, train)[test])[:, 1], dtype=np.float64
        )
        out[name] = {"auc": _auc(label[test], score)}
    return out


def _auc(label: npt.NDArray[np.bool_], score: FloatArray) -> float:
    """Rank-based AUC; ties share their averaged rank."""

    positives = int(label.sum())
    negatives = int(label.size - positives)
    if positives == 0 or negatives == 0:
        return float("nan")
    ranks = stats.rankdata(score)
    return float((ranks[label].sum() - positives * (positives + 1) / 2.0) / (positives * negatives))


# ------------------------------------------------------------- C: execution-timing rank


def ranking_utility(
    target: FloatArray,
    designs: dict[str, FloatArray],
    train: npt.NDArray[np.bool_],
    test: npt.NDArray[np.bool_],
) -> dict[str, object]:
    """Does the mechanism improve the ORDERING of origins by realized variance?

    Level accuracy and rank accuracy are different properties: QLIKE punishes a badly
    calibrated level even when the ordering is right, which is exactly the case an
    execution desk cares about.
    """

    out: dict[str, object] = {}
    for name, design in designs.items():
        forecast = LADDER["lightgbm"](standardise(design, train), target, train)
        predicted, realized = forecast[test], target[test]
        order = np.argsort(predicted)
        buckets = np.array_split(order, DECILES)
        means = [float(np.mean(realized[bucket])) for bucket in buckets]
        out[name] = {
            "spearman": float(stats.spearmanr(predicted, realized).statistic),
            "kendall_tau": float(stats.kendalltau(predicted, realized).statistic),
            "bottom_decile_mean_rv": means[0],
            "top_decile_mean_rv": means[-1],
            "decile_spread_ratio": means[-1] / max(means[0], VARIANCE_FLOOR),
        }
    return out


# ------------------------------------------------------------------------------- main


def run_role(
    panel: pl.DataFrame, targets: pl.DataFrame, *, role: str, train_share: float, folds: int
) -> dict[str, object]:
    frame = (
        panel.filter(pl.col("role") == role)
        .join(targets, on=["asset", "session_date", "origin_minute"], how="left")
        .sort(["session_date", "asset", "origin_minute"])
    )
    rv30 = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)

    nuisance, nuisance_names = build_design(frame, [B0_FEATURES, B1_FEATURES])
    # The historical treatment battery predates the core/rich split and names channels
    # that are now B2-rich. The extension resolves against the whole registry: rich means
    # out of the primary contrasts, not out of existence.
    available = feature_map("B2_CORE", "B2_RICH")
    unknown = [n for n in CORE_TREATMENTS if n not in available]
    if unknown:
        raise ValueError(f"RP2_EXT1_UNKNOWN_TREATMENT:{','.join(sorted(unknown))}")
    treatment_map = {n: available[n] for n in CORE_TREATMENTS}
    treatment, names = build_design(frame, [treatment_map], intercept=False)
    keep = usable_rows(nuisance, rv30) & np.isfinite(treatment).all(axis=1)
    information_sets = {
        "B0+B1": describe_information_set(("B0", "B1"), nuisance_names, keep),
        "B2_mechanism": describe_information_set(("B2_mechanism",), names, keep),
    }
    if int(keep.sum()) < 2000:
        return {
            "status": "INSUFFICIENT_ROWS",
            "rows": int(keep.sum()),
            "information_sets": information_sets,
        }

    frame = frame.filter(pl.Series(keep))
    rv30, nuisance, treatment = rv30[keep], nuisance[keep], treatment[keep]
    sessions = session_rank(frame["session_date"].to_numpy())
    train, test = chronological_split(sessions, train_share=train_share)
    assets = frame["asset"].to_numpy()

    # Registry designs are imputed and scaled from this fold's training rows, like the
    # primary blocks. build_design still runs first, so a registered feature the panel does
    # not carry stops the run before anything is fitted.
    _, base_names = build_design(frame, [B0_FEATURES, B1_FEATURES])
    _, full_names = build_design(frame, [B0_FEATURES, B1_FEATURES, B2_FEATURES])
    replicated_map = {n: available[n] for n in REPLICATED}
    _, replicated_names = build_design(frame, [B0_FEATURES, B1_FEATURES, replicated_map])
    base_design, _, base_fitted = fold_design(frame, [*B0_FEATURES, *B1_FEATURES], train)
    full_design, _, full_fitted = fold_design(
        frame, [*B0_FEATURES, *B1_FEATURES, *B2_FEATURES], train
    )
    replicated_design, _, replicated_fitted = fold_design(
        frame, [*B0_FEATURES, *B1_FEATURES, *replicated_map], train
    )
    preprocessing = {
        "B0+B1": describe_preprocessor(base_fitted),
        "B0+B1+mechanism": describe_preprocessor(replicated_fitted),
        "B0+B1+B2": describe_preprocessor(full_fitted),
    }
    designs = {
        "B0+B1": base_design,
        "B0+B1+mechanism": replicated_design,
        "B0+B1+B2": full_design,
    }
    finite = common_usable_rows(designs, rv30)
    evaluated = lift_mask(keep, test & finite)
    information_sets |= {
        "nested_B0+B1": describe_information_set(("B0", "B1"), base_names, evaluated),
        "nested_B0+B1+mechanism": describe_information_set(
            ("B0", "B1", "B2_mechanism"), replicated_names, evaluated
        ),
        "nested_B0+B1+B2": describe_information_set(("B0", "B1", "B2"), full_names, evaluated),
    }

    return {
        "status": "MEASURED",
        "rows": int(keep.sum()),
        "train_share": train_share,
        "information_sets": information_sets,
        "preprocessing": preprocessing,
        "test_rows": int(test.sum()),
        "sessions": int(np.unique(sessions).size),
        "a_other_targets": target_battery(
            frame, nuisance, treatment, sessions, names, folds=folds, evaluation_base=keep
        ),
        "b_tail_classification": tail_classification(
            rv30, designs, train & finite, test & finite, assets
        ),
        "c_execution_ranking": ranking_utility(rv30, designs, train & finite, test & finite),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-share", type=float, default=0.6)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args(argv)

    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL)
    origins_by_key: dict[tuple[str, str], FloatArray] = {}
    for (asset, session_date), group in panel.group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        origins_by_key[(str(asset), str(session_date))] = np.asarray(
            group["origin_minute"].to_numpy(), dtype=np.float64
        )
    targets = build_target_battery(args.data_root, origins_by_key)

    document: dict[str, object] = {
        # Which frozen sets were fitted, how complete they were, and the hash of the
        # registry that decided them. Without it an artifact records a design width and
        # nothing a reader can check that width against.
        "feature_registry": describe_features(
            panel,
            [*feature_map("B0_CORE", "B1_CORE", "B2_CORE"), *CORE_TREATMENTS],
            sets=FITTED_SETS,
        ),
        "extension": 1,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "question": "is the Block 7 mechanism useful for a job other than RV30 level?",
        "core_treatments": list(CORE_TREATMENTS),
        "replicated_treatments": list(REPLICATED),
        "horizons": list(HORIZONS),
        "session_minutes": FULL_SESSION_MINUTES,
    }
    for role in ("D", "V"):
        document[role] = run_role(
            panel, targets, role=role, train_share=args.train_share, folds=args.folds
        )
    document["utility_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "mechanism_utility.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for role in ("D", "V"):
        block = document[role]
        assert isinstance(block, dict)
        print(f"=== role {role}: {block.get('status')} rows={block.get('rows')} ===")
        battery = block.get("a_other_targets")
        if isinstance(battery, dict):
            print(f"  A. other targets (family of {battery.get('_family_size')}):")
            for name, stats_block in sorted(battery.items()):
                if not isinstance(stats_block, dict):
                    continue
                print(
                    f"     {name:<24} joint p={stats_block['joint_p_value']:.2e} "
                    f"holm={stats_block.get('holm_p', float('nan')):.4f}"
                )
        tail = block.get("b_tail_classification")
        if isinstance(tail, dict):
            print("  B. tail classification (AUC):")
            for name in ("B0+B1", "B0+B1+mechanism", "B0+B1+B2"):
                entry = tail.get(name)
                if isinstance(entry, dict):
                    print(f"     {name:<18} AUC={entry['auc']:.4f}")
        rank = block.get("c_execution_ranking")
        if isinstance(rank, dict):
            print("  C. execution ranking:")
            for name, entry in rank.items():
                assert isinstance(entry, dict)
                print(
                    f"     {name:<18} spearman={entry['spearman']:.4f} "
                    f"decile_spread={entry['decile_spread_ratio']:.2f}x"
                )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
