"""Gate 1: studentized inference over every frozen forecast artifact.

Re-analysis only: reads already-read frozen forecast parquets (no new data
exposure, decision-52 compliant) and publishes cluster-t, Newey-West (DM),
wild cluster bootstrap-t, serial-dependence diagnostics, moving-block CIs,
per-campaign Model Confidence Sets, the Gamma-minus-LightGBM interaction
contrast, Gelman-Carlin design analysis for the LightGBM challenger, and the
legacy sign-bootstrap side by side. Output: artifacts/gate1_inference/.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import polars as pl

from mds650 import inference
from mds650.metrics import paired_day_bootstrap

REPO = Path(__file__).resolve().parents[1]
# ponytail: MDS650_DATA_ROOT carries the documented L008 ambiguity (D:\MDS650 vs
# D:\MDS650\data), so this script uses MDS650_EXTERNAL_ROOT per roadmap 2.6.
DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
EVIDENCE_ROOT = Path(os.environ.get("MDS650_EVIDENCE_ROOT", DATA_ROOT / "evidence_root"))
OUTPUT = REPO / "artifacts" / "gate1_inference"

GAMMA = "gamma_glm_confirmatory"
LGBM = "lightgbm_robustness"

CAMPAIGNS: dict[str, dict[str, Any]] = {
    "C1_development": {
        "path": REPO / "artifacts" / "phase5" / "development_forecasts.parquet",
        "model_column": "model_role",
        "models": [GAMMA, LGBM],
        "chain": [("B0", "B1a"), ("B1a", "B2")],
        "interaction": ("B1a", "B2", GAMMA, LGBM),
    },
    "C2_holdout_prospective": {
        "path": EVIDENCE_ROOT / "artifacts" / "phase5" / "holdout_forecasts.parquet",
        "model_column": "model_role",
        "models": [GAMMA, LGBM],
        "chain": [("B0", "B1a"), ("B1a", "B2")],
        "interaction": ("B1a", "B2", GAMMA, LGBM),
    },
    "C4c_replication_pit_v2": {
        "path": DATA_ROOT
        / "independent_replication_30"
        / "derived"
        / "pit_v2_evaluation"
        / "predictions_pit_v2.parquet",
        "model_column": "model_role",
        "models": [GAMMA, LGBM],
        "chain": [("B0v2", "B1v2a"), ("B1v2a", "B2v2")],
        "interaction": ("B1v2a", "B2v2", GAMMA, LGBM),
    },
    "C5_blocks_2024_exploratory": {
        "path": REPO / "artifacts" / "b2_confirmation" / "frozen_evaluation_forecasts.parquet",
        "model_column": "model_name",
        "models": ["gamma_glm", "lightgbm", "har_rv", "ridge", "elastic_net"],
        "chain": [("B0", "B1a"), ("B1a", "B2")],
        "interaction": ("B1a", "B2", "gamma_glm", "lightgbm"),
        "block_column": "block_id",
    },
    "C6_b1v3_confirmation": {
        "path": DATA_ROOT / "b1v3_confirmation" / "evaluation" / "primary_forecasts.parquet",
        "model_column": "model_role",
        "models": [GAMMA, LGBM],
        "chain": [("B1v3a", "B0"), ("B1v3a", "B2")],
        "interaction": ("B1v3a", "B2", GAMMA, LGBM),
    },
}
# ponytail: C3 (Phase 6) is intentionally absent — its evaluation forecasts were
# never persisted (only aggregates in evidence_root/artifacts/phase6/results.json);
# regenerating them requires re-running the frozen evaluator and is out of Gate 1
# scope. Reported as an explicit exclusion, not silently dropped.

SIGN_FLIP_NOTE = (
    "C6 chain lists (B1v3a, B0) because decision 48 registered the adverse "
    "B0-better-than-B1v3a direction; positive values favor the second set."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _daily(
    frame: pl.DataFrame, spec: dict[str, Any], base: str, expanded: str, model: str
) -> pl.DataFrame:
    return inference.paired_daily_differences(
        frame,
        base_set=base,
        expanded_set=expanded,
        model=model,
        model_column=str(spec["model_column"]),
    )


def _contrast_report(daily: pl.DataFrame) -> dict[str, Any]:
    values = daily["mean_difference"].to_numpy()
    pooled = daily.rename({"mean_difference": "loss_difference"})
    legacy = paired_day_bootstrap(
        pooled.select("session_date", "loss_difference"),
        value_column="loss_difference",
    )
    correlations = inference.autocorrelation(values, max_lag=min(5, values.size - 1))
    report: dict[str, Any] = {
        "cluster_t": inference.cluster_t_test(values),
        "newey_west": inference.newey_west_t_test(values),
        "wild_rademacher": inference.wild_cluster_bootstrap(values, weights="rademacher"),
        "wild_webb": inference.wild_cluster_bootstrap(values, weights="webb"),
        "acf": correlations,
        "ljung_box": inference.ljung_box(values, max_lag=min(5, values.size - 1)),
        "legacy_sign_bootstrap_daily_equal_weight": legacy,
    }
    if abs(correlations[0]) > 0.1:
        report["moving_block"] = inference.moving_block_bootstrap(values)
        report["moving_block_triggered_by_rho1"] = True
    else:
        report["moving_block"] = inference.moving_block_bootstrap(values)
        report["moving_block_triggered_by_rho1"] = False
    return report


def _mcs(frame: pl.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    cells = (
        frame.group_by("session_date", spec["model_column"], "information_set")
        .agg(pl.col("qlike_loss").mean())
        .with_columns(
            (
                pl.col(spec["model_column"]).cast(pl.Utf8)
                + pl.lit("|")
                + pl.col("information_set").cast(pl.Utf8)
            ).alias("cell")
        )
        .pivot(on="cell", index="session_date", values="qlike_loss")
        .sort("session_date")
        .drop_nulls()
    )
    return inference.model_confidence_set(cells)


def _campaign(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["path"])
    frame = pl.read_parquet(path)
    if "timing_variant" in frame.columns:
        frame = frame.filter(pl.col("timing_variant") == "PRIMARY")
    blocks: list[tuple[str, pl.DataFrame]] = [("all", frame)]
    if "block_column" in spec:
        blocks = [
            (str(block), frame.filter(pl.col(spec["block_column"]) == block))
            for block in sorted(frame[spec["block_column"]].unique().to_list())
        ]
    result: dict[str, Any] = {
        "input_path": str(path),
        "input_sha256": _sha256(path),
        "rows": frame.height,
        "sessions": frame["session_date"].n_unique(),
        "blocks": {},
    }
    for block_name, block in blocks:
        entry: dict[str, Any] = {"contrasts": {}, "interaction": {}}
        for base, expanded in spec["chain"]:
            for model in spec["models"]:
                daily = _daily(block, spec, base, expanded, model)
                entry["contrasts"][f"{model}:{base}->{expanded}"] = _contrast_report(daily)
        base, expanded, model_a, model_b = spec["interaction"]
        interaction = inference.interaction_daily_differences(
            block,
            base_set=base,
            expanded_set=expanded,
            model_a=model_a,
            model_b=model_b,
            model_column=str(spec["model_column"]),
        )
        entry["interaction"][f"({model_a}-{model_b}):{base}->{expanded}"] = _contrast_report(
            interaction
        )
        gamma_daily = _daily(block, spec, base, expanded, model_a)
        lgbm_daily = _daily(block, spec, base, expanded, model_b)
        gamma_estimate = float(gamma_daily["mean_difference"].to_numpy().mean())
        lgbm_values = lgbm_daily["mean_difference"].to_numpy()
        lgbm_se = float(lgbm_values.std(ddof=1)) / (lgbm_values.size**0.5)
        if gamma_estimate != 0.0 and lgbm_se > 0.0:
            entry["gelman_carlin_lightgbm_at_gamma_effect"] = inference.type_s_type_m(
                gamma_estimate, lgbm_se
            )
        entry["model_confidence_set"] = _mcs(block, spec)
        result["blocks"][block_name] = entry
    return result


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "schema_version": "gate1-inference-v1.0",
        "note": SIGN_FLIP_NOTE,
        "excluded_campaigns": {
            "C3_phase6": "evaluation forecasts never persisted; aggregates only"
        },
        "seed": 650,
        "campaigns": {},
    }
    for name, spec in CAMPAIGNS.items():
        print(f"[gate1] {name}")
        results["campaigns"][name] = _campaign(name, spec)
    payload = json.dumps(results, indent=1, sort_keys=True)
    (OUTPUT / "results.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT / "results.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"[gate1] wrote {OUTPUT / 'results.json'} sha256={digest[:16]}")


if __name__ == "__main__":
    main()
