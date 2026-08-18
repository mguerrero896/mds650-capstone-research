"""Contract tests for studentized inference on daily loss differentials."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from mds650 import inference


def _long_frame(rng: np.random.Generator, *, effect: float = 0.0) -> pl.DataFrame:
    rows = []
    for day in range(12):
        date = f"2026-01-{day + 2:02d}"
        for origin in range(8):
            for asset in ("AAA", "BBB"):
                base = float(rng.normal(1.0, 0.05))
                rows.append((f"o{origin}", asset, date, "m", "B1", base))
                rows.append((f"o{origin}", asset, date, "m", "B2", base - effect))
                rows.append((f"o{origin}", asset, date, "g", "B1", base))
                rows.append((f"o{origin}", asset, date, "g", "B2", base + effect))
    return pl.DataFrame(
        rows,
        schema=[
            "origin_id",
            "asset",
            "session_date",
            "model_role",
            "information_set",
            "qlike_loss",
        ],
        orient="row",
    )


def test_paired_daily_differences_recovers_effect() -> None:
    frame = _long_frame(np.random.default_rng(1), effect=0.02)
    daily = inference.paired_daily_differences(
        frame, base_set="B1", expanded_set="B2", model="m"
    )
    assert daily.height == 12
    assert daily["origin_count"].to_list() == [16] * 12
    assert daily["mean_difference"].to_numpy() == pytest.approx([0.02] * 12)


def test_paired_daily_differences_rejects_unpaired() -> None:
    frame = _long_frame(np.random.default_rng(2)).filter(
        ~((pl.col("information_set") == "B2") & (pl.col("origin_id") == "o0"))
    )
    with pytest.raises(ValueError, match="INFERENCE_UNPAIRED_ORIGINS"):
        inference.paired_daily_differences(
            frame, base_set="B1", expanded_set="B2", model="m"
        )


def test_interaction_differences_are_signed() -> None:
    frame = _long_frame(np.random.default_rng(3), effect=0.01)
    interaction = inference.interaction_daily_differences(
        frame, base_set="B1", expanded_set="B2", model_a="m", model_b="g"
    )
    assert interaction["mean_difference"].to_numpy() == pytest.approx([0.02] * 12)


def test_cluster_t_detects_signal_and_null() -> None:
    rng = np.random.default_rng(4)
    signal = inference.cluster_t_test(rng.normal(0.05, 0.01, size=30))
    null = inference.cluster_t_test(rng.normal(0.0, 0.01, size=30))
    assert float(signal["p_value"]) < 1e-6
    assert float(null["p_value"]) > 0.01
    assert signal["clusters"] == 30


def test_newey_west_widens_under_autocorrelation() -> None:
    rng = np.random.default_rng(5)
    noise = rng.normal(0.0, 1.0, size=400)
    correlated = np.empty_like(noise)
    correlated[0] = noise[0]
    for index in range(1, noise.size):
        correlated[index] = 0.7 * correlated[index - 1] + noise[index]
    plain = inference.cluster_t_test(correlated + 0.1)
    hac = inference.newey_west_t_test(correlated + 0.1, max_lag=8)
    assert float(hac["standard_error"]) > float(plain["standard_error"])


def test_wild_bootstrap_matches_t_on_null() -> None:
    rng = np.random.default_rng(6)
    series = rng.normal(0.0, 0.01, size=30)
    result = inference.wild_cluster_bootstrap(series, repetitions=999)
    assert 0.01 < float(result["p_value"]) <= 1.0
    assert float(result["ci_low"]) < float(result["ci_high"])
    webb = inference.wild_cluster_bootstrap(series, weights="webb", repetitions=999)
    assert webb["weights"] == "webb"
    with pytest.raises(ValueError, match="INFERENCE_WEIGHTS_INVALID"):
        inference.wild_cluster_bootstrap(series, weights="bad")


def test_autocorrelation_and_ljung_box() -> None:
    rng = np.random.default_rng(7)
    iid = rng.normal(0.0, 1.0, size=200)
    persistent = np.repeat(rng.normal(0.0, 1.0, size=100), 2)
    iid_box = inference.ljung_box(iid, max_lag=5)
    persistent_box = inference.ljung_box(persistent, max_lag=5)
    assert float(iid_box["p_value"]) > 0.05
    assert float(persistent_box["p_value"]) < 1e-4
    correlations = inference.autocorrelation(persistent, max_lag=1)
    assert correlations[0] > 0.3


def test_moving_block_bootstrap_contains_mean() -> None:
    rng = np.random.default_rng(8)
    series = rng.normal(0.05, 0.02, size=30)
    result = inference.moving_block_bootstrap(series, repetitions=999)
    assert float(result["ci_low"]) < float(result["estimate"]) < float(result["ci_high"])
    assert int(result["block_length"]) >= 1


def test_model_confidence_set_drops_dominated_model() -> None:
    rng = np.random.default_rng(9)
    days = 40
    good = rng.normal(1.0, 0.01, size=days)
    twin = good + rng.normal(0.0, 0.005, size=days)
    bad = good + 0.2
    frame = pl.DataFrame(
        {
            "session_date": [f"d{index}" for index in range(days)],
            "good": good,
            "twin": twin,
            "bad": bad,
        }
    )
    result = inference.model_confidence_set(frame, repetitions=999)
    survivors = result["survivors"]
    assert isinstance(survivors, list)
    assert "bad" not in survivors
    assert "good" in survivors


def test_type_s_type_m_low_power_regime() -> None:
    weak = inference.type_s_type_m(0.001, 0.01)
    strong = inference.type_s_type_m(0.05, 0.01)
    assert weak["power"] < 0.1
    assert weak["exaggeration_ratio"] > 5.0
    assert strong["power"] > 0.99
    assert strong["exaggeration_ratio"] == pytest.approx(1.0, abs=0.01)
    assert weak["type_s"] > strong["type_s"]


def test_input_contracts() -> None:
    with pytest.raises(ValueError, match="INFERENCE_REQUIRES_THREE_DAYS"):
        inference.cluster_t_test([1.0, 2.0])
    with pytest.raises(ValueError, match="INFERENCE_NONFINITE_INPUT"):
        inference.cluster_t_test([1.0, float("nan"), 2.0])
    with pytest.raises(ValueError, match="INFERENCE_ZERO_VARIANCE"):
        inference.cluster_t_test([1.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="INFERENCE_SE_INVALID"):
        inference.type_s_type_m(0.01, 0.0)
    with pytest.raises(ValueError, match="INFERENCE_EFFECT_INVALID"):
        inference.type_s_type_m(0.0, 1.0)


def test_model_confidence_set_block_bootstrap() -> None:
    rng = np.random.default_rng(10)
    days = 40
    good = rng.normal(1.0, 0.01, size=days)
    bad = good + 0.2
    frame = pl.DataFrame(
        {
            "session_date": [f"d{index}" for index in range(days)],
            "good": good,
            "bad": bad,
        }
    )
    result = inference.model_confidence_set(frame, repetitions=999, block_length=5)
    assert result["block_length"] == 5
    survivors = result["survivors"]
    assert isinstance(survivors, list)
    assert "bad" not in survivors and "good" in survivors
    with pytest.raises(ValueError, match="INFERENCE_BLOCK_LENGTH_INVALID"):
        inference.model_confidence_set(frame, block_length=0)
