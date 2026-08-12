from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from mds650.metrics import qlike_losses
from mds650.phase6_evaluation import evaluate_phase6


def _predictions(*, negative_b2: bool = True) -> pl.DataFrame:
    rows = []
    assets = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
    forecasts = {
        "B0v2": 2.0,
        "B1v2a": 1.4,
        "B2v2": 2.5 if negative_b2 else 1.1,
    }
    for day in range(10):
        for index, asset in enumerate(assets):
            origin = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(days=day, minutes=5 * index)
            for role in ("gamma_glm_confirmatory", "lightgbm_robustness"):
                for information_set, forecast in forecasts.items():
                    rows.append(
                        {
                            "origin_id": f"{asset}:{origin.isoformat()}",
                            "asset": asset,
                            "session_date": origin.date().isoformat(),
                            "forecast_origin_utc": origin,
                            "session_tercile": ("first", "middle", "last")[index % 3],
                            "volatility_regime": ("low", "normal", "high")[index % 3],
                            "rv30": 1.0,
                            "fold": 1,
                            "model_role": role,
                            "information_set": information_set,
                            "forecast": forecast,
                            "qlike_loss": float(qlike_losses([1.0], [forecast])[0]),
                        }
                    )
    return pl.DataFrame(rows)


def _timing_predictions() -> pl.DataFrame:
    primary = _predictions(negative_b2=False)
    parts = [primary.with_columns(pl.lit("FMP_DELAY_2_MINUTES").alias("timing_variant"))]
    for variant in (
        "window_15m_60s",
        "window_30m_60s",
        "latency_5m_120s",
        "latency_5m_300s",
    ):
        parts.append(
            primary.filter(pl.col("information_set") == "B2v2").with_columns(
                pl.lit(variant).alias("timing_variant")
            )
        )
    return pl.concat(parts)


def _method() -> dict[str, object]:
    return {
        "inference": {"bootstrap_repetitions": 1_000, "seed": 650},
        "training_mde": {"delta_b1v2": 0.001, "delta_b2v2": 0.001},
    }


def test_global_family_contains_exactly_two_hypotheses() -> None:
    result = evaluate_phase6(_predictions(), _method())

    assert set(result["global_holm"]) == {"delta_b1v2", "delta_b2v2"}


def test_negative_result_is_preserved_without_claiming_an_edge() -> None:
    result = evaluate_phase6(_predictions(), _method())

    assert result["global"]["gamma_glm_confirmatory"]["delta_b2v2"]["estimate"] < 0
    assert result["decision"] == "GLOBAL_EDGE_NOT_CONFIRMED"
    assert result["all_signs_retained"] is True


def test_positive_edge_requires_and_passes_every_frozen_gate() -> None:
    result = evaluate_phase6(
        _predictions(negative_b2=False),
        _method(),
        timing_predictions=_timing_predictions(),
    )

    assert result["decision"] == "GLOBAL_B2V2_EDGE_CONFIRMED"
    assert set(result["confirmed_contrasts"]) == {"delta_b1v2", "delta_b2v2"}
    assert set(result["targeted_holm"]) == {
        "META",
        "MSFT",
        "last_session_tercile",
    }


def test_missing_timing_variant_fails_closed() -> None:
    incomplete = _timing_predictions().filter(pl.col("timing_variant") != "latency_5m_300s")

    with pytest.raises(ValueError, match="PHASE6_TIMING_VARIANTS_INCOMPLETE"):
        evaluate_phase6(
            _predictions(negative_b2=False),
            _method(),
            timing_predictions=incomplete,
        )


def test_timing_reversal_prevents_b2_global_confirmation() -> None:
    timing = _timing_predictions().with_columns(
        pl.when(
            (pl.col("timing_variant") == "latency_5m_300s") & (pl.col("information_set") == "B2v2")
        )
        .then(2.5)
        .otherwise(pl.col("forecast"))
        .alias("forecast")
    )
    timing = timing.with_columns(
        pl.Series(
            "qlike_loss",
            qlike_losses(timing["rv30"].to_numpy(), timing["forecast"].to_numpy()),
        )
    )

    result = evaluate_phase6(
        _predictions(negative_b2=False),
        _method(),
        timing_predictions=timing,
    )

    assert "delta_b2v2" not in result["confirmed_contrasts"]
