"""One-read orchestration tests for the frozen B1v3 confirmation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from mds650.b1v3_confirmation_run import (
    bind_b1v3_confirmation_targets,
    consume_authorization_exclusively,
    join_registered_timing_targets,
)
from mds650.b1v3_evaluation import b1v3_information_sets
from mds650.study_design import canonical_sha256

_ASSETS = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")


def _dates() -> list[str]:
    start = datetime(2024, 11, 1, tzinfo=UTC)
    return [(start + timedelta(days=index)).date().isoformat() for index in range(30)]


def _preregistration() -> dict[str, Any]:
    document: dict[str, Any] = {
        "status": "FROZEN_BEFORE_CONFIRMATION",
        "safe_to_evaluate_b1v3": "NO",
        "outcome_read_count": 0,
        "training_sessions": [
            (datetime(2024, 8, 1, tzinfo=UTC) + timedelta(days=index)).date().isoformat()
            for index in range(60)
        ],
        "confirmation_sessions": _dates(),
        "common_predictor_panel_sha256": "3" * 64,
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _authorization() -> dict[str, Any]:
    document: dict[str, Any] = {
        "status": "CONFIRMATION_EVALUATION_IN_PROGRESS",
        "safe_to_evaluate_b1v3": "YES",
        "outcome_read_count": 2,
        "training_read_count": 1,
        "confirmation_read_count": 1,
        "evaluation_attempt_count": 1,
        "results_inspected": False,
        "common_panel_sha256": "3" * 64,
        "method_freeze_sha256": "2" * 64,
        "timing_panel_manifest_sha256": "4" * 64,
        "quality_report_sha256": "5" * 64,
        "confirmation_code_sha256": "6" * 64,
        "uv_lock_sha256": "7" * 64,
        "preregistration_manifest_sha256": _preregistration()["manifest_sha256"],
        "prerequisites": {
            name: True
            for name in (
                "focused_tests",
                "full_tests",
                "ruff",
                "mypy",
                "coverage",
                "json_schema",
                "no_leakage",
                "hygiene",
                "deterministic_replay",
                "clean_install",
                "spec_kit",
                "disk_gate",
            )
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _confirmation_inputs() -> tuple[pl.DataFrame, pl.DataFrame]:
    features = b1v3_information_sets()["B2"]
    common_rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []
    for day_index, session_date in enumerate(_dates()):
        for asset_index, asset in enumerate(_ASSETS):
            origin = datetime.fromisoformat(f"{session_date}T15:00:00+00:00") + timedelta(
                minutes=asset_index * 5
            )
            origin_id = f"{asset}|{origin.isoformat()}"
            feature_values = {
                name: asset if name == "b0v2_asset_identity" else 0.1
                for name in features
            }
            common_rows.append(
                {
                    "origin_id": origin_id,
                    "asset": asset,
                    "session_date": session_date,
                    "forecast_origin_utc": origin,
                    "role": "confirmation",
                    "session_tercile": ("first", "middle", "last")[day_index % 3],
                    "b0_information_set_complete": True,
                    "b1v3a_information_set_complete": True,
                    "b2_information_set_complete": True,
                    **feature_values,
                }
            )
            target_rows.append(
                {
                    "origin_id": origin_id,
                    "asset": asset,
                    "session_date": session_date,
                    "forecast_origin_utc": origin,
                    "role": "confirmation",
                    "target_price_count": 31,
                    "target_return_count": 30,
                    "rv30": 0.001,
                    "drop_reason": None,
                    "max_predictor_available_at_utc": origin,
                    **{
                        name: feature_values[name]
                        for name in b1v3_information_sets()["B0"]
                    },
                }
            )
    return pl.DataFrame(common_rows), pl.DataFrame(target_rows)


def test_confirmation_binding_preserves_exact_target_contract_and_b0() -> None:
    common, targets = _confirmation_inputs()

    bound = bind_b1v3_confirmation_targets(
        common,
        targets,
        preregistration=_preregistration(),
        authorization=_authorization(),
    )

    assert bound.height == 30 * len(_ASSETS)
    assert bound["target_price_count"].unique().to_list() == [31]
    assert bound["target_return_count"].unique().to_list() == [30]
    assert set(bound["role"].unique()) == {"confirmation"}


def test_confirmation_binding_excludes_registered_incomplete_b0_origin() -> None:
    common, targets = _confirmation_inputs()
    excluded_origin = str(common["origin_id"][0])
    incomplete = pl.col("origin_id") == excluded_origin
    common = common.with_columns(
        pl.when(incomplete)
        .then(pl.lit(False))
        .otherwise(pl.col(name))
        .alias(name)
        for name in (
            "b0_information_set_complete",
            "b1v3a_information_set_complete",
            "b2_information_set_complete",
        )
    )
    targets = targets.with_columns(
        pl.when(incomplete)
        .then(pl.lit(None, dtype=pl.Datetime(time_zone="UTC")))
        .otherwise(pl.col("max_predictor_available_at_utc"))
        .alias("max_predictor_available_at_utc"),
        pl.when(incomplete)
        .then(pl.lit("B0V2_UNDERLYING_HISTORY_MISSING"))
        .otherwise(pl.col("drop_reason"))
        .alias("drop_reason"),
    )

    bound = bind_b1v3_confirmation_targets(
        common,
        targets,
        preregistration=_preregistration(),
        authorization=_authorization(),
    )

    assert bound.height == 30 * len(_ASSETS) - 1
    assert excluded_origin not in set(bound["origin_id"])


def test_confirmation_binding_rejects_predictor_drift_and_future_availability() -> None:
    common, targets = _confirmation_inputs()
    drift = targets.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(9.0))
        .otherwise(pl.col("b0v2_log_spot"))
        .alias("b0v2_log_spot")
    )
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_B0_DRIFT"):
        bind_b1v3_confirmation_targets(
            common,
            drift,
            preregistration=_preregistration(),
            authorization=_authorization(),
        )
    future = targets.with_columns(
        (pl.col("forecast_origin_utc") + pl.duration(seconds=1)).alias(
            "max_predictor_available_at_utc"
        )
    )
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_PREDICTOR_FUTURE"):
        bind_b1v3_confirmation_targets(
            common,
            future,
            preregistration=_preregistration(),
            authorization=_authorization(),
        )


def test_timing_join_uses_only_primary_complete_origin_intersection() -> None:
    common, targets = _confirmation_inputs()
    primary = bind_b1v3_confirmation_targets(
        common,
        targets,
        preregistration=_preregistration(),
        authorization=_authorization(),
    )
    variant = common.with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.lit(False))
        .otherwise(pl.col("b2_information_set_complete"))
        .alias("b2_information_set_complete")
    )

    joined = join_registered_timing_targets(variant, primary)

    assert joined.height == primary.height - 1
    assert joined["origin_id"].n_unique() == joined.height
    assert joined["rv30"].null_count() == 0


def test_authorization_is_consumed_exclusively_before_target_read(tmp_path: Path) -> None:
    path = tmp_path / "authorization.json"
    authorization = _authorization()

    digest = consume_authorization_exclusively(path, authorization)

    assert len(digest) == 64
    assert path.is_file()
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_ALREADY_CONSUMED"):
        consume_authorization_exclusively(path, authorization)
    unsafe = _authorization()
    unsafe["unsafe_path"] = "C:/Users/person/private"
    unsafe["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in unsafe.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_CONFIRMATION_AUTHORIZATION_HYGIENE_INVALID"):
        consume_authorization_exclusively(tmp_path / "unsafe.json", unsafe)
