"""Contracts for canonical, paired RV30 inference."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl

from mds650.canonical_validation import (
    evaluate_canonical_predictions,
    validate_claim_eligibility,
)


def _shared_predictions() -> pl.DataFrame:
    """Build matched origins for both registered model families."""

    rows: list[dict[str, object]] = []
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    for model_role in ("gamma_glm_confirmatory", "lightgbm_robustness"):
        for day in range(3):
            for index in range(3):
                origin = start + timedelta(days=day, minutes=5 * index)
                for information_set, forecast in (
                    ("B0v2", 0.0040),
                    ("B1v2a", 0.0045),
                    ("B2v2", 0.0048),
                ):
                    rows.append(
                        {
                            "block": "synthetic",
                            "fold": 1,
                            "model_role": model_role,
                            "information_set": information_set,
                            "origin_id": f"AAPL:{origin.isoformat()}",
                            "asset": "AAPL",
                            "session_date": origin.date().isoformat(),
                            "forecast_origin_utc": origin,
                            "session_tercile": "first",
                            "volatility_regime": "normal",
                            "rv30": 0.0050,
                            "forecast": forecast,
                            "analysis_status": "HISTORICAL_REGISTERED_REFERENCE",
                        }
                    )
    return pl.DataFrame(rows)


def test_contrasts_pair_only_shared_origin_and_day() -> None:
    """Nested contrasts use the exact same forecast origins and day clusters."""

    results = evaluate_canonical_predictions(
        _shared_predictions(),
        bootstrap_seed=7,
        draws=200,
        mde_by_contrast={"delta_b1v2": 0.001, "delta_b2v2": 0.001},
    )

    assert results["contrast_integrity"]["unpaired_rows"] == 0
    assert all(row["paired_rows"] == 9 for row in results["contrasts"])


def test_model_disagreement_cannot_become_global_edge() -> None:
    """Opposite registered model signs prevent a universal positive claim."""

    result = validate_claim_eligibility(
        {"gamma_b2": 0.01, "lightgbm_b2": -0.01, "mde_pass": True}
    )

    assert result == "MODEL_FAMILY_DEPENDENT"
