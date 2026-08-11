"""Evaluate the frozen B0/B1a/B2 protocol once on two new blocks.

All parameter selection happens on the frozen 80-session development panel.
The new blocks are read only after the direct protocol freeze and are never
used to choose a model, feature or threshold.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compare_development_models as development
import numpy as np
import polars as pl

from mds650.development_models import (
    INFORMATION_SETS,
    fit_development_candidate,
)
from mds650.metrics import holm_adjust, paired_day_bootstrap, qlike_losses, regression_metrics
from mds650.study_design import B2_FEATURE_NAMES, canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts" / "b2_confirmation"
DEV_PANEL = ROOT / "artifacts" / "phase5" / "common_development_80d.parquet"
NEW_PANEL = Path("D:/MDS650/b2_confirmation/derived/panel_60d.parquet")
PREREG = ROOT / "artifacts" / "phase5" / "preregistration.json"
PROTOCOL = ROOT / "artifacts" / "methodology" / "b2_direct_protocol_freeze_v1.json"
MODEL_NAMES = ("gamma_glm", "lightgbm", "har_rv", "ridge", "elastic_net")
INFORMATION_SET_NAMES = ("B0", "B1a", "B2")
BOOTSTRAP_REPETITIONS = 10_000
SEED = 650


def _json(path: Path) -> dict[str, Any]:
    """Load one JSON object."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write deterministic self-hashed JSON evidence."""
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    output = {**unsigned, "manifest_sha256": canonical_sha256(unsigned)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(output, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )


def _validate_protocol() -> dict[str, Any]:
    """Require the frozen direct protocol and target-blind development selection."""
    protocol = _json(PROTOCOL)
    if protocol.get("status") != "FROZEN_DIRECT_B2_BEFORE_NEW_BLOCK_ACQUISITION":
        raise RuntimeError("B2_CONFIRMATION_PROTOCOL_NOT_FROZEN")
    if protocol.get("new_blocks", {}).get("download_started") is not False:
        raise RuntimeError("B2_CONFIRMATION_PROTOCOL_ACQUISITION_STATE_INVALID")
    prereg = _json(ROOT / "artifacts" / "methodology" / "b2_mechanism_search_preregistration.json")
    if prereg.get("selection_sample", {}).get("independent_samples_read") is not False:
        raise RuntimeError("B2_CONFIRMATION_SELECTION_READ_INDEPENDENT")
    return protocol


def _valid_panel(frame: pl.DataFrame) -> pl.DataFrame:
    """Filter to the common PIT rows without rebalancing event prevalence."""
    if "b1_complete" not in frame.columns:
        source = "b1a_common_complete" if "b1a_common_complete" in frame.columns else "b1a_complete"
        if source not in frame.columns:
            raise RuntimeError("B2_CONFIRMATION_B1_COMPLETENESS_MISSING")
        frame = frame.with_columns(pl.col(source).fill_null(False).alias("b1_complete"))
    if "b2_features_finite" not in frame.columns:
        frame = frame.with_columns(
            pl.all_horizontal([pl.col(feature).is_finite() for feature in B2_FEATURE_NAMES]).alias(
                "b2_features_finite"
            )
        )
    required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "rv30",
        "b0_spot",
        "b0_rv_5m_lag",
        "b0_rv_30m_lag",
        "b0_return_5m_lag",
        "b0_volume_5m_lag",
        "b0_session_minute",
        "b1q_atm_iv",
        *B2_FEATURE_NAMES,
        "b1_complete",
        "b2_features_finite",
    }
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"B2_CONFIRMATION_PANEL_COLUMNS_MISSING:{','.join(sorted(missing))}")
    valid = frame.filter(
        pl.col("rv30").is_not_null()
        & (pl.col("rv30") > 0)
        & pl.col("b1_complete")
        & pl.col("b2_features_finite")
    )
    numeric = [column for column in (*INFORMATION_SETS["B2"], "rv30") if column != "asset"]
    if valid.is_empty() or not np.isfinite(valid.select(numeric).to_numpy()).all():
        raise RuntimeError("B2_CONFIRMATION_VALID_PANEL_EMPTY_OR_NONFINITE")
    return valid.sort("forecast_origin_utc")


def _add_regime(dev: pl.DataFrame, new: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, float]]:
    """Apply development-only volatility cutpoints to the new panel."""
    lower = dev["b0_rv_30m_lag"].quantile(1 / 3)
    upper = dev["b0_rv_30m_lag"].quantile(2 / 3)
    if lower is None or upper is None:
        raise RuntimeError("B2_CONFIRMATION_REGIME_CUTPOINTS_INVALID")
    lower_value = lower
    upper_value = upper
    if not np.isfinite([float(lower_value), float(upper_value)]).all():
        raise RuntimeError("B2_CONFIRMATION_REGIME_CUTPOINTS_INVALID")
    classified = new.with_columns(
        pl.when(pl.col("b0_rv_30m_lag") <= float(lower_value))
        .then(pl.lit("low"))
        .when(pl.col("b0_rv_30m_lag") <= float(upper_value))
        .then(pl.lit("normal"))
        .otherwise(pl.lit("high"))
        .alias("volatility_regime")
    )
    return classified, {"lower": float(lower_value), "upper": float(upper_value)}


def _validate_independent_panel(frame: pl.DataFrame) -> None:
    """Enforce the frozen two-block, target and point-in-time contract."""
    required = {
        "block_id",
        "session_date",
        "target_price_count",
        "target_return_count",
        "b2v2_cutoff_utc",
        "b2v2_max_created_at_utc",
    }
    missing = required - set(frame.columns)
    if missing:
        missing_text = ",".join(sorted(missing))
        raise RuntimeError(
            f"B2_CONFIRMATION_INDEPENDENT_CONTRACT_COLUMNS_MISSING:{missing_text}"
        )
    block_counts = {
        str(block): int(frame.filter(pl.col("block_id") == block)["session_date"].n_unique())
        for block in frame["block_id"].unique().to_list()
    }
    if len(block_counts) != 2 or any(count < 30 for count in block_counts.values()):
        raise RuntimeError(f"B2_CONFIRMATION_BLOCK_COUNT_INVALID:{block_counts}")
    if frame["origin_id"].n_unique() != frame.height:
        raise RuntimeError("B2_CONFIRMATION_INDEPENDENT_ORIGIN_DUPLICATE")
    if frame.filter(
        (pl.col("target_price_count") != 31) | (pl.col("target_return_count") != 30)
    ).height:
        raise RuntimeError("B2_CONFIRMATION_RV30_TARGET_SHAPE_INVALID")
    if frame.filter(
        pl.col("b2v2_max_created_at_utc").is_not_null()
        & (pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc"))
    ).height:
        raise RuntimeError("B2_CONFIRMATION_FUTURE_CREATED_AT")


def _write_effect_figure(contrasts: list[dict[str, Any]], path: Path) -> None:
    """Write a dependency-free SVG of the registered B1 and B2 contrasts."""
    rows = [
        row
        for row in contrasts
        if row.get("contrast") in {"delta_b1", "delta_b2"}
    ]
    rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("block_id")),
            str(row.get("contrast")),
            str(row.get("model_name")),
        ),
    )
    width, height = 1_100, max(220, 30 * len(rows) + 80)
    if not rows:
        path.write_text(
            "<svg xmlns='http://www.w3.org/2000/svg' width='1100' height='220'></svg>\n",
            encoding="utf-8",
        )
        return
    scale = max((abs(float(row["estimate"])) for row in rows), default=1.0) or 1.0
    center = 620
    lines = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>",
        "<rect width='100%' height='100%' fill='white'/>",
        "<text x='20' y='24' font-size='16'>Frozen confirmation QLIKE contrasts</text>",
    ]
    for index, row in enumerate(rows):
        y = 50 + index * 30
        estimate = float(row["estimate"])
        length = estimate / scale * 300
        x = center if length >= 0 else center + length
        colour = "#1b7f3a" if estimate >= 0 else "#b3261e"
        label = f"{row['block_id']} / {row['model_name']} / {row['contrast']}"
        lines.append(f"<text x='20' y='{y + 4}' font-size='11'>{label}</text>")
        lines.append(
            f"<rect x='{x:.2f}' y='{y - 9}' width='{abs(length):.2f}' "
            f"height='16' fill='{colour}'/>"
        )
        lines.append(f"<text x='940' y='{y + 4}' font-size='11'>{estimate:.6f}</text>")
    lines.append(
        f"<line x1='{center}' x2='{center}' y1='38' y2='{height - 12}' stroke='#333'/></svg>"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_model_card(results: Mapping[str, Any], path: Path) -> None:
    """Write a concise, auditable card for the frozen confirmation run."""
    path.write_text(
        "# B2 confirmation model card\n\n"
        "This run fits all registered estimators on the 80-session development panel "
        "and reads the two 30-session historical blocks once for confirmation.\n\n"
        f"- Status: `{results['status']}`\n"
        f"- Models: {', '.join(str(item) for item in results['models'])}\n"
        f"- Information sets: {', '.join(str(item) for item in results['information_sets'])}\n"
        f"- Bootstrap: {results['bootstrap_repetitions']} paired XNYS session clusters\n"
        f"- MDE: {results['mde']:.8f}\n"
        "- Primary estimand: QLIKE(B1a) - QLIKE(B2); positive means B2 lowers loss.\n"
        "- No RL or deep neural network is used: the frozen task is supervised RV30 "
        "forecasting with a small tabular information set.\n",
        encoding="utf-8",
    )


def _contrast(
    frame: pl.DataFrame, *, model: str, baseline: str, expanded: str, block: str
) -> dict[str, Any]:
    """Compute one paired-day QLIKE contrast without selecting on its sign."""
    left = frame.filter(
        (pl.col("model_name") == model)
        & (pl.col("information_set") == baseline)
        & (pl.col("block_id") == block)
    ).select("origin_id", "asset", "session_date", pl.col("qlike_loss").alias("baseline_loss"))
    right = frame.filter(
        (pl.col("model_name") == model)
        & (pl.col("information_set") == expanded)
        & (pl.col("block_id") == block)
    ).select("origin_id", "asset", "session_date", pl.col("qlike_loss").alias("expanded_loss"))
    paired = left.join(
        right, on=["origin_id", "asset", "session_date"], how="inner", validate="1:1"
    ).with_columns((pl.col("baseline_loss") - pl.col("expanded_loss")).alias("loss_difference"))
    if paired.height != left.height or paired.height != right.height:
        raise RuntimeError(f"B2_CONFIRMATION_UNPAIRED:{model}:{baseline}:{expanded}:{block}")
    inference = paired_day_bootstrap(paired, repetitions=BOOTSTRAP_REPETITIONS, seed=SEED)
    return {
        "block_id": block,
        "model_name": model,
        "contrast": "delta_b1" if baseline == "B0" else "delta_b2",
        "definition": f"QLIKE({baseline})-QLIKE({expanded})",
        "baseline_information_set": baseline,
        "expanded_information_set": expanded,
        "baseline_mean_qlike": float(cast(float, paired["baseline_loss"].mean())),
        "expanded_mean_qlike": float(cast(float, paired["expanded_loss"].mean())),
        **inference,
    }


def _metrics(frame: pl.DataFrame) -> list[dict[str, Any]]:
    """Return QLIKE/MAE/RMSE by block, model and information set."""
    rows: list[dict[str, Any]] = []
    for block in sorted(frame["block_id"].unique().to_list()):
        for model in MODEL_NAMES:
            for information_set in INFORMATION_SET_NAMES:
                subset = frame.filter(
                    (pl.col("block_id") == block)
                    & (pl.col("model_name") == model)
                    & (pl.col("information_set") == information_set)
                )
                values = regression_metrics(
                    subset["rv30"].to_numpy(), subset["forecast"].to_numpy()
                )
                rows.append(
                    {
                        "block_id": block,
                        "model_name": model,
                        "information_set": information_set,
                        "observations": subset.height,
                        **values,
                    }
                )
    return rows


def _stability(frame: pl.DataFrame, contrasts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute registered secondary stability slices without model selection."""
    rows: list[dict[str, Any]] = []
    for block in sorted(frame["block_id"].unique().to_list()):
        for model in MODEL_NAMES:
            for group_type, column in (
                ("asset", "asset"),
                ("session_tercile", "session_tercile"),
                ("volatility_regime", "volatility_regime"),
            ):
                for group in (
                    frame.filter(pl.col("block_id") == block)[column].unique().sort().to_list()
                ):
                    subset = frame.filter((pl.col("block_id") == block) & (pl.col(column) == group))
                    if subset.is_empty():
                        continue
                    left = subset.filter(
                        (pl.col("model_name") == model) & (pl.col("information_set") == "B1a")
                    ).select(
                        "origin_id", "asset", "session_date", pl.col("qlike_loss").alias("left")
                    )
                    right = subset.filter(
                        (pl.col("model_name") == model) & (pl.col("information_set") == "B2")
                    ).select(
                        "origin_id", "asset", "session_date", pl.col("qlike_loss").alias("right")
                    )
                    paired = left.join(
                        right, on=["origin_id", "asset", "session_date"], how="inner"
                    ).with_columns((pl.col("left") - pl.col("right")).alias("loss_difference"))
                    if paired["session_date"].n_unique() < 2:
                        continue
                    inference = paired_day_bootstrap(paired, repetitions=2_000, seed=SEED)
                    rows.append(
                        {
                            "block_id": block,
                            "model_name": model,
                            "group_type": group_type,
                            "group": str(group),
                            **inference,
                        }
                    )
    return rows


def main() -> None:
    """Fit on development, predict the two blocks once, and emit evidence."""
    protocol = _validate_protocol()
    prereg = _json(PREREG)
    mechanism_prereg = _json(
        ROOT / "artifacts" / "methodology" / "b2_mechanism_search_preregistration.json"
    )
    frozen_mde = float(protocol.get("inference", {}).get("mde", 0.0))
    mechanism_mde = float(mechanism_prereg.get("inference", {}).get("mde", 0.0))
    if frozen_mde <= 0 or mechanism_mde <= 0 or not np.isclose(
        frozen_mde, mechanism_mde, rtol=0.0, atol=1e-15
    ):
        raise RuntimeError("B2_CONFIRMATION_MDE_SOURCE_MISMATCH")
    development_panel = _valid_panel(pl.read_parquet(DEV_PANEL))
    development_panel = development_panel.with_columns(
        pl.when(pl.col("b0_session_minute") <= 130)
        .then(pl.lit("first"))
        .when(pl.col("b0_session_minute") <= 260)
        .then(pl.lit("middle"))
        .otherwise(pl.lit("last"))
        .alias("session_tercile")
    )
    # Fit and freeze every development-only estimator before opening the
    # independent panel.  This ordering is part of the no-selection-on-new-
    # blocks contract, not merely a bookkeeping convention.
    fitted_models: list[tuple[str, str, Any, dict[str, Any]]] = []
    variant_ledger: list[dict[str, Any]] = []
    for information_set in INFORMATION_SET_NAMES:
        for model in MODEL_NAMES:
            selected, variants = development._select_parameters(
                development_panel,
                information_set=information_set,
                model_name=model,
                preregistration=prereg,
            )
            variant_ledger.extend(
                [{**record, "independent_samples_read": False} for record in variants]
            )
            fitted_models.append(
                (
                    information_set,
                    model,
                    fit_development_candidate(
                        development_panel,
                        feature_columns=INFORMATION_SETS[information_set],
                        model_name=model,
                        parameters=selected,
                        seed=SEED,
                    ),
                    selected,
                )
            )

    # The independent rows are opened only after all development choices are
    # frozen above; no feature, threshold or model decision can inspect them.
    new_raw = pl.read_parquet(NEW_PANEL)
    _validate_independent_panel(new_raw)
    new_panel, cutpoints = _add_regime(development_panel, _valid_panel(new_raw))
    new_panel = new_panel.with_columns(
        pl.when(pl.col("b0_session_minute") <= 130)
        .then(pl.lit("first"))
        .when(pl.col("b0_session_minute") <= 260)
        .then(pl.lit("middle"))
        .otherwise(pl.lit("last"))
        .alias("session_tercile")
    )
    forecasts: list[pl.DataFrame] = []
    for information_set, model, fitted, selected in fitted_models:
        forecast = fitted.predict(new_panel)
        target = np.asarray(new_panel["rv30"].to_numpy(), dtype=np.float64)
        forecasts.append(
            new_panel.select(
                "origin_id",
                "asset",
                "session_date",
                "forecast_origin_utc",
                "block_id",
                "session_tercile",
                "volatility_regime",
                "rv30",
            ).with_columns(
                pl.lit(model).alias("model_name"),
                pl.lit(information_set).alias("information_set"),
                pl.Series("forecast", forecast),
                pl.Series("qlike_loss", qlike_losses(target, forecast)),
                pl.lit(json.dumps(selected, sort_keys=True)).alias("selected_parameters"),
            )
        )
    forecast_frame = pl.concat(forecasts).sort(
        ["block_id", "model_name", "information_set", "origin_id"]
    )
    contrasts: list[dict[str, Any]] = []
    for block in sorted(forecast_frame["block_id"].unique().to_list()):
        for model in MODEL_NAMES:
            contrasts.append(
                _contrast(forecast_frame, model=model, baseline="B0", expanded="B1a", block=block)
            )
            contrasts.append(
                _contrast(forecast_frame, model=model, baseline="B1a", expanded="B2", block=block)
            )
    b2_pvalues = {
        f"{row['block_id']}:{row['model_name']}": float(row["p_value_two_sided"])
        for row in contrasts
        if row["contrast"] == "delta_b2"
    }
    holm = holm_adjust(b2_pvalues)
    for row in contrasts:
        if row["contrast"] == "delta_b2":
            row["p_value_holm_all_b2_models"] = holm[f"{row['block_id']}:{row['model_name']}"]
    metrics = _metrics(forecast_frame)
    calibration = (
        forecast_frame.group_by(["block_id", "model_name", "information_set"])
        .agg(
            pl.len().alias("observations"),
            (pl.col("forecast") / pl.col("rv30")).mean().alias("mean_forecast_to_actual"),
            (pl.col("forecast") / pl.col("rv30")).median().alias("median_forecast_to_actual"),
        )
        .sort(["block_id", "model_name", "information_set"])
    )
    stability = _stability(forecast_frame, contrasts)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    forecast_frame.write_parquet(
        ARTIFACT_ROOT / "frozen_evaluation_forecasts.parquet", compression="zstd"
    )
    pl.DataFrame(metrics).write_csv(ARTIFACT_ROOT / "frozen_evaluation_metrics.csv")
    pl.DataFrame(stability).write_csv(ARTIFACT_ROOT / "frozen_evaluation_stability.csv")
    calibration.write_csv(ARTIFACT_ROOT / "frozen_evaluation_calibration.csv")
    result_payload: dict[str, Any] = {
        "schema_version": "b2-confirmation-frozen-evaluation-1.0",
        "status": "PASS_TWO_NEW_BLOCKS_EVALUATED",
        "selection_panel": "artifacts/phase5/common_development_80d.parquet",
        "selection_panel_sha256": hashlib.sha256(DEV_PANEL.read_bytes()).hexdigest(),
        "independent_panel": "MDS650_DATA_ROOT/b2_confirmation/derived/panel_60d.parquet",
        "independent_samples_read": True,
        "new_block_count": len(new_panel["block_id"].unique()),
        "new_block_session_counts": {
            str(block): int(
                new_panel.filter(pl.col("block_id") == block)["session_date"].n_unique()
            )
            for block in new_panel["block_id"].unique().sort().to_list()
        },
        "new_valid_origin_count": new_panel.height,
        "models": list(MODEL_NAMES),
        "information_sets": list(INFORMATION_SET_NAMES),
        "bootstrap_repetitions": BOOTSTRAP_REPETITIONS,
        "metrics": metrics,
        "contrasts": contrasts,
        "holm_b2": holm,
        "mde": frozen_mde,
        "mde_source": "artifacts/methodology/b2_direct_protocol_freeze_v1.json",
        "regime_cutpoints_from_development": cutpoints,
        "variant_ledger": variant_ledger,
        "forecast_sha256": hashlib.sha256(
            (ARTIFACT_ROOT / "frozen_evaluation_forecasts.parquet").read_bytes()
        ).hexdigest(),
        "target_outcome_read": True,
        "selection_used_independent_samples": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    figure_path = ARTIFACT_ROOT / "frozen_evaluation_qlike_effects.svg"
    model_card_path = ROOT / "docs" / "b2_confirmation_model_card.md"
    _write_effect_figure(contrasts, figure_path)
    _write_model_card(result_payload, model_card_path)
    result_payload["figure_path"] = "artifacts/b2_confirmation/frozen_evaluation_qlike_effects.svg"
    result_payload["model_card_path"] = "docs/b2_confirmation_model_card.md"
    _write_json(ARTIFACT_ROOT / "frozen_evaluation_results.json", result_payload)
    print(
        json.dumps(
            {
                "status": "PASS_TWO_NEW_BLOCKS_EVALUATED",
                "origins": new_panel.height,
                "contrasts": len(contrasts),
            }
        )
    )


if __name__ == "__main__":
    main()
