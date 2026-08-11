"""Freeze the development-only B2 mechanism-search protocol before fitting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import polars as pl

from mds650.development_models import B0_FEATURES, B1_FEATURES
from mds650.mechanism_search import B2_FEATURES, MECHANISM_VARIANTS, SEED
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "artifacts" / "phase5" / "common_development_80d.parquet"
MDE_SOURCE = ROOT / "artifacts" / "phase6" / "method_freeze.json"
OUTPUT = ROOT / "artifacts" / "methodology" / "b2_mechanism_search_preregistration.json"
MODEL_NAMES = ("gamma_glm", "har_rv", "ridge", "elastic_net", "lightgbm")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mde() -> float:
    if not MDE_SOURCE.exists():
        raise RuntimeError("MECHANISM_MDE_SOURCE_MISSING")
    payload = json.loads(MDE_SOURCE.read_text(encoding="utf-8"))
    value = payload.get("training_mde", {}).get("delta_b2v2")
    if not isinstance(value, (int, float)) or value <= 0:
        raise RuntimeError("MECHANISM_MDE_SOURCE_INVALID")
    return float(value)


def build_preregistration() -> dict[str, Any]:
    """Build the immutable, target-blind mechanism-search contract."""
    if not PANEL.exists():
        raise RuntimeError("MECHANISM_PANEL_MISSING")
    schema = pl.scan_parquet(PANEL).collect_schema()
    required = {
        "asset",
        "session_date",
        "common_complete",
        "rv30",
        *B0_FEATURES,
        *B1_FEATURES,
        *B2_FEATURES,
    }
    missing = required - set(schema.names())
    if missing:
        raise RuntimeError(f"MECHANISM_PANEL_SCHEMA_INVALID:{','.join(sorted(missing))}")
    dates = (
        pl.scan_parquet(PANEL)
        .select(pl.col("session_date"))
        .unique()
        .sort("session_date")
        .collect()["session_date"]
        .to_list()
    )
    payload: dict[str, Any] = {
        "schema_version": "b2-mechanism-search-preregistration-1.0",
        "status": "FROZEN_DEVELOPMENT_ONLY_BEFORE_MECHANISM_FIT",
        "selection_sample": {
            "panel": "artifacts/phase5/common_development_80d.parquet",
            "panel_sha256": _sha256(PANEL),
            "asset_universe": ["AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA"],
            "session_count": len(dates),
            "date_start": str(dates[0]),
            "date_end": str(dates[-1]),
            "independent_samples_read": False,
            "independent_samples_used_for_selection": False,
        },
        "information_sets": {
            "B1": list(B1_FEATURES),
            "B2_increment": list(B2_FEATURES),
        },
        "base_models": list(MODEL_NAMES),
        "mechanism_variants": list(MECHANISM_VARIANTS),
        "residual_contract": {
            "target": "cross_fitted_rv30_minus_b1_forecast",
            "b2_only_predictors": True,
            "base_model_fit_is_expanding_and_purged": True,
            "cross_fit_minimum_prior_sessions": 20,
            "cross_fit_blocks": 3,
            "forecast_floor": 1e-12,
            "ridge_alpha": 1.0,
            "elastic_net_alpha": 0.01,
            "elastic_net_l1_ratio": 0.5,
        },
        "placebos_and_sensitivities": {
            "placebo": "PERMUTE_CROSSFIT_RESIDUAL_TARGET_WITHIN_TRAINING_ONLY",
            "temporal_sensitivity": "ONE_SESSION_LAGGED_B2_BY_ASSET_AND_ORIGIN_MINUTE",
            "primary_b2_window": "5_MINUTES_AS_IN_PANEL",
        },
        "inference": {
            "primary_metric": "QLIKE",
            "bootstrap_unit": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
            "bootstrap_repetitions": 10000,
            "seed": SEED,
            "multiple_comparisons": "Holm",
            "family": "all_base_models_x_all_mechanism_variants",
            "mde_source": "artifacts/phase6/method_freeze.json:training_mde.delta_b2v2",
            "mde": _mde(),
        },
        "retention_rule": {
            "primary_estimate_positive": True,
            "bootstrap_ci_low_above_zero": True,
            "holm_p_below_0_05": True,
            "estimate_at_least_mde": True,
            "at_least_four_of_six_asset_estimates_positive": True,
            "at_most_one_asset_interval_wholly_negative": True,
            "placebo_not_positive_and_significant": True,
            "lag_sensitivity_not_wholly_negative": True,
        },
        "oos_guard": {
            "oos_read_count": 0,
            "new_blocks_required_after_freeze": 2,
            "minimum_sessions_per_block": 30,
            "blocks_must_be_disjoint_from_all_observed_samples": True,
            "selection_must_not_read_oos": True,
        },
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def main() -> None:
    """Write the frozen mechanism-search manifest and print its hash."""
    payload = build_preregistration()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "manifest_sha256": payload["manifest_sha256"]}))


if __name__ == "__main__":
    main()
