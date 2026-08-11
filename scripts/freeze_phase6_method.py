"""Freeze Phase 6 methods and training-only MDE before any OOS read."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

import polars as pl

from mds650.phase6_evaluation import (
    phase6_information_sets,
    training_mde_from_forecasts,
    training_only_oof_forecasts,
    validate_phase6_evaluation_panel,
)
from mds650.study_design import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
PHASE6 = ROOT / "artifacts" / "phase6"
PANEL_PATH = PHASE6 / "common_panel.parquet"
PREREGISTRATION_PATH = PHASE6 / "preregistration.json"
TRAINING_FORECASTS_PATH = PHASE6 / "training_mde_oof_forecasts.parquet"
TRAINING_LEDGER_PATH = PHASE6 / "training_mde_variant_ledger.json"
METHOD_FREEZE_PATH = PHASE6 / "method_freeze.json"
B0_SENSITIVITY_PATH = PHASE6 / "b0v2_sensitivities.parquet"
B2_SENSITIVITY_PATH = PHASE6 / "b2v2_sensitivities.parquet"


def _sha256(path: Path) -> str:
    """Hash a file incrementally without loading it wholly into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write one canonical JSON artifact."""
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_method_freeze(
    panel_path: Path,
    preregistration_path: Path,
) -> dict[str, Any]:
    """Build the immutable method contract from training rows only.

    Parameters
    ----------
    panel_path
        Canonical Phase 6 panel. It is read only after the preregistration
        proves no registered out-of-sample data have been accessed.
    preregistration_path
        Frozen preregistration JSON carrying the self-hash and read counter.

    Raises
    ------
    RuntimeError
        If the preregistration is invalid or OOS data were read beforehand.
    """
    preregistration = json.loads(preregistration_path.read_text(encoding="utf-8"))
    if preregistration.get("oos_read_count") != 0:
        raise RuntimeError("OOS_ACCESSED_BEFORE_METHOD_FREEZE")
    unsigned = {
        key: value
        for key, value in preregistration.items()
        if key != "manifest_sha256"
    }
    if (
        preregistration.get("status") != "FROZEN_BEFORE_OOS"
        or preregistration.get("manifest_sha256") != canonical_sha256(unsigned)
    ):
        raise RuntimeError("PHASE6_PREREGISTRATION_INVALID")
    panel = validate_phase6_evaluation_panel(
        pl.read_parquet(panel_path), preregistration
    )
    training_dates = set(preregistration["folds"][0]["train_dates"])
    training = panel.filter(pl.col("session_date").is_in(training_dates))
    forecasts, variants = training_only_oof_forecasts(training, preregistration)
    forecasts.write_parquet(TRAINING_FORECASTS_PATH, compression="zstd")
    mde = training_mde_from_forecasts(
        forecasts,
        draws=int(preregistration["inference"]["bootstrap_repetitions"]),
        seed=int(preregistration["inference"]["seed"]),
    )
    ledger = {
        "schema_version": "phase6-training-mde-ledger-1.0",
        "status": "TRAINING_ONLY",
        "oos_read_count": 0,
        "training_sessions": sorted(training_dates),
        "forecast_origin_count": forecasts["origin_id"].n_unique(),
        "forecast_row_count": forecasts.height,
        "variants": variants,
        "mde": mde,
        "forecast_sha256": _sha256(TRAINING_FORECASTS_PATH),
    }
    ledger["manifest_sha256"] = canonical_sha256(ledger)
    _write_json(TRAINING_LEDGER_PATH, ledger)
    source_paths = (
        ROOT / "src/mds650/phase6.py",
        ROOT / "src/mds650/phase6_evaluation.py",
        ROOT / "src/mds650/modeling.py",
        ROOT / "src/mds650/metrics.py",
        ROOT / "src/mds650/temporal_validation.py",
        ROOT / "scripts/build_phase6_panel.py",
        ROOT / "scripts/run_phase6_replication.py",
        ROOT / "scripts/report_phase6_results.py",
        ROOT / "scripts/finalize_phase6_evidence.py",
        Path(__file__).resolve(),
    )
    freeze: dict[str, Any] = {
        "schema_version": "phase6-method-freeze-1.0",
        "status": "FROZEN_AFTER_TRAINING_BEFORE_OOS",
        "oos_read_count": 0,
        "information_sets": {
            name: list(features)
            for name, features in phase6_information_sets().items()
        },
        "models": preregistration["models"],
        "folds": preregistration["folds"],
        "estimands": preregistration["estimands"],
        "inference": preregistration["inference"],
        "training_mde": mde,
        "mde_method": {
            "scope": "INITIAL_60_TRAINING_SESSIONS_ONLY",
            "oof_blocks": 3,
            "oof_sessions": 30,
            "bootstrap_unit": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
            "draws": preregistration["inference"]["bootstrap_repetitions"],
            "power": 0.80,
            "familywise_alpha": 0.05,
            "holm_family_size": 2,
            "null_critical_quantile": 0.9875,
            "power_tail_quantile": 0.20,
        },
        "success_rules": preregistration["success_rules"],
        "stability": preregistration["stability"],
        "timing": preregistration["timing"],
        "package_versions": {
            package: version(package)
            for package in ("lightgbm", "numpy", "polars", "scikit-learn")
        },
        "input_hashes": {
            "common_panel.parquet": _sha256(panel_path),
            "preregistration.json": _sha256(preregistration_path),
            "training_mde_oof_forecasts.parquet": _sha256(
                TRAINING_FORECASTS_PATH
            ),
            "training_mde_variant_ledger.json": _sha256(TRAINING_LEDGER_PATH),
            "b0v2_sensitivities.parquet": _sha256(B0_SENSITIVITY_PATH),
            "b2v2_sensitivities.parquet": _sha256(B2_SENSITIVITY_PATH),
            "uv.lock": _sha256(ROOT / "uv.lock"),
        },
        "source_code_hashes": {
            path.relative_to(ROOT).as_posix(): _sha256(path)
            for path in source_paths
        },
        "preregistration_manifest_sha256": preregistration["manifest_sha256"],
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    freeze["manifest_sha256"] = canonical_sha256(freeze)
    return freeze


def main() -> None:
    """Write the deterministic method freeze and its training evidence."""
    freeze = build_method_freeze(PANEL_PATH, PREREGISTRATION_PATH)
    _write_json(METHOD_FREEZE_PATH, freeze)
    print(
        json.dumps(
            {
                "status": freeze["status"],
                "oos_read_count": freeze["oos_read_count"],
                "training_mde": freeze["training_mde"],
                "manifest_sha256": freeze["manifest_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
