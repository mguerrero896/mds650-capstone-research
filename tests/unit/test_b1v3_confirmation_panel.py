"""Target-blind contracts for the B1v3 confirmation predictor panel."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

import mds650.b1v3_confirmation_panel as panel_module
from mds650.b1v3 import B1V3_FEATURES
from mds650.b1v3_confirmation import canonical_sha256
from mds650.b1v3_confirmation_panel import (
    apply_b2_availability_sidecar,
    assemble_predictor_panel,
    build_b0_target_blind,
    build_origin_grid,
    build_spot_frame,
    strip_target_columns,
    validate_fmp_cache_document,
)
from mds650.phase6 import B0V2_FEATURES
from mds650.study_design import B2_FEATURE_NAMES


def test_origin_grid_uses_xnys_early_close_and_frozen_roles() -> None:
    frame = build_origin_grid(
        training_sessions=("2024-11-27",),
        confirmation_sessions=("2024-11-29",),
        assets=("AAPL",),
    )

    assert frame.height == 72 + 36
    assert frame.filter(pl.col("role") == "training_warmup").height == 72
    assert frame.filter(pl.col("role") == "confirmation").height == 36
    assert frame["origin_id"].n_unique() == frame.height
    assert frame.filter(pl.col("session_date") == "2024-11-29").select(
        pl.col("forecast_origin_utc").max()
    ).item() == datetime(2024, 11, 29, 17, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("training", "confirmation", "assets", "code"),
    [
        (("2024-11-27", "2024-11-27"), ("2024-11-29",), ("AAPL",), "ALLOWLIST"),
        (("2024-11-27",), ("2024-11-27",), ("AAPL",), "ALLOWLIST"),
        (("2024-11-27",), ("2024-11-29",), ("MSFT", "AAPL"), "ALLOWLIST"),
        (("2024-11-28",), ("2024-11-29",), ("AAPL",), "NOT_XNYS_SESSION"),
    ],
)
def test_origin_grid_fails_closed_on_invalid_frozen_scope(
    training: tuple[str, ...],
    confirmation: tuple[str, ...],
    assets: tuple[str, ...],
    code: str,
) -> None:
    with pytest.raises(ValueError, match=code):
        build_origin_grid(
            training_sessions=training,
            confirmation_sessions=confirmation,
            assets=assets,
        )


def test_fmp_cache_must_match_report_identity_and_self_hash() -> None:
    document: dict[str, object] = {
        "schema_version": "b1v3-provider-preflight-cache-2.0",
        "provider": "fmp",
        "request_fingerprint": "a" * 64,
        "status_code": 200,
        "headers": {"content-type": "application/json"},
        "payload": [{"date": "2024-08-02 09:30:00", "close": 1.0}],
        "response_sha256": "b" * 64,
        "network_attempts": 1,
    }
    document["cache_self_hash"] = canonical_sha256(document)
    report = {
        "provider": "fmp",
        "pass": True,
        "request_fingerprint": "a" * 64,
        "response_sha256": "b" * 64,
    }

    assert validate_fmp_cache_document(document, report) == document["payload"]
    report["response_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="B1V3_FMP_CACHE_REPORT_BINDING_INVALID"):
        validate_fmp_cache_document(document, report)

    document["response_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="B1V3_FMP_CACHE_SELF_HASH_INVALID"):
        validate_fmp_cache_document(document, report)


def test_fmp_cache_rejects_non_list_payload() -> None:
    document: dict[str, object] = {
        "schema_version": "b1v3-provider-preflight-cache-2.0",
        "provider": "fmp",
        "request_fingerprint": "a" * 64,
        "status_code": 200,
        "payload": {"unexpected": True},
        "response_sha256": "b" * 64,
    }
    document["cache_self_hash"] = canonical_sha256(document)
    report = {
        "provider": "fmp",
        "pass": True,
        "request_fingerprint": "a" * 64,
        "response_sha256": "b" * 64,
    }
    with pytest.raises(ValueError, match="B1V3_FMP_CACHE_PAYLOAD_INVALID"):
        validate_fmp_cache_document(document, report)


def test_spot_frame_uses_exact_prior_bar_and_never_silent_fill() -> None:
    origins = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            "asset": ["AAPL", "AAPL"],
            "session_date": ["2024-08-02", "2024-08-02"],
            "forecast_origin_utc": [
                datetime(2024, 8, 2, 14, 35, tzinfo=UTC),
                datetime(2024, 8, 2, 14, 40, tzinfo=UTC),
            ],
        }
    )
    bars = pl.DataFrame(
        {
            "asset": ["AAPL"],
            "session_date": ["2024-08-02"],
            "bar_timestamp_raw_utc": [datetime(2024, 8, 2, 14, 34, tzinfo=UTC)],
            "available_at_utc": [datetime(2024, 8, 2, 14, 35, tzinfo=UTC)],
            "close": [219.86],
        }
    )

    spots = build_spot_frame(bars, origins)

    assert spots["spot_available"].to_list() == [True, False]
    assert spots["spot"].to_list() == [219.86, None]
    assert spots["spot_missing_reason"].to_list() == [None, "FMP_ORIGIN_SPOT_UNAVAILABLE"]
    with pytest.raises(ValueError, match="B1V3_SPOT_DUPLICATE_BAR"):
        build_spot_frame(pl.concat([bars, bars]), origins)
    with pytest.raises(ValueError, match="B1V3_SPOT_INPUT_SCHEMA_INVALID"):
        build_spot_frame(bars.drop("close"), origins)


def test_strip_target_columns_removes_all_target_scaffolding() -> None:
    frame = pl.DataFrame(
        {
            "origin_id": ["AAPL:1"],
            "rv30": [None],
            "target_price_count": [0],
            "target_return_count": [0],
            "drop_reason": ["RV30_ORIGIN_CLOSE_MISSING"],
            **{feature: [1.0] for feature in B0V2_FEATURES if feature != "b0v2_asset_identity"},
            "b0v2_asset_identity": ["AAPL"],
        }
    )

    clean = strip_target_columns(frame)

    assert not {"rv30", "target_price_count", "target_return_count"} & set(clean.columns)
    assert clean["drop_reason"].item() == "ORIGIN_CLOSE_MISSING"

    with pytest.raises(ValueError, match="B1V3_B0_TARGET_COLUMN_REMAINS"):
        strip_target_columns(pl.DataFrame({"origin_id": ["x"], "prediction_score": [1.0]}))


def test_b0_wrapper_is_predictor_only_and_marks_completeness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = pl.DataFrame(
        {
            "origin_id": ["AAPL:1"],
            "rv30": [None],
            "target_price_count": [0],
            "target_return_count": [0],
            "drop_reason": [None],
            **{
                feature: [1.0]
                for feature in B0V2_FEATURES
                if feature != "b0v2_asset_identity"
            },
            "b0v2_asset_identity": ["AAPL"],
        }
    )

    def fake_builder(
        bars: pl.DataFrame,
        origins: pl.DataFrame,
        *,
        delay_minutes: int,
        include_target: bool,
    ) -> pl.DataFrame:
        assert bars.is_empty()
        assert origins.is_empty()
        assert delay_minutes == 1
        assert include_target is False
        return source

    monkeypatch.setattr(panel_module, "build_b0v2_features", fake_builder)
    result = build_b0_target_blind(pl.DataFrame(), pl.DataFrame())

    assert result["b0_complete"].item() is True
    assert result["b0_missing_reason"].item() is None
    assert not {"rv30", "target_price_count", "target_return_count"} & set(result.columns)


def test_b2_sidecar_masks_delay_exclusion_instead_of_zero_coding() -> None:
    canonical = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            "b2v2_max_created_at_utc": [
                datetime(2024, 8, 2, 14, 34, tzinfo=UTC),
                None,
            ],
            "b2v2_cutoff_utc": [
                datetime(2024, 8, 2, 14, 34, tzinfo=UTC),
                datetime(2024, 8, 2, 14, 39, tzinfo=UTC),
            ],
            **{feature: [1.0, 0.0] for feature in B2_FEATURE_NAMES},
        }
    )
    sidecar = pl.DataFrame(
        {
            "canonical_variant": ["primary_5m_60s", "primary_5m_60s"],
            "origin_id": ["AAPL:1", "AAPL:2"],
            "row_status": [
                "PIT_USABLE_ELIGIBLE_ACTIVITY",
                "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES",
            ],
            "eligible_for_corrected_pit_panel": [True, False],
            "source_temporal_state": [
                "SOURCE_AVAILABLE",
                "RECORD_CREATION_DELAY_OBSERVED",
            ],
        }
    )

    corrected = apply_b2_availability_sidecar(
        canonical,
        sidecar,
        canonical_variant="primary_5m_60s",
    )

    excluded = corrected.filter(pl.col("origin_id") == "AAPL:2")
    assert excluded["b2v2_availability_eligible"].item() is False
    assert all(excluded[feature].item() is None for feature in B2_FEATURE_NAMES)
    assert corrected.filter(pl.col("origin_id") == "AAPL:1")[B2_FEATURE_NAMES[0]].item() == 1.0


def test_b2_sidecar_fails_closed_on_identity_missingness_and_future_time() -> None:
    cutoff = datetime(2024, 8, 2, 14, 34, tzinfo=UTC)
    canonical = pl.DataFrame(
        {
            "origin_id": ["AAPL:1"],
            "b2v2_max_created_at_utc": [cutoff],
            "b2v2_cutoff_utc": [cutoff],
            **{feature: [1.0] for feature in B2_FEATURE_NAMES},
        }
    )
    sidecar = pl.DataFrame(
        {
            "canonical_variant": ["primary_5m_60s"],
            "origin_id": ["AAPL:1"],
            "row_status": ["PIT_USABLE_ELIGIBLE_ACTIVITY"],
            "eligible_for_corrected_pit_panel": [True],
            "source_temporal_state": ["SOURCE_AVAILABLE"],
        }
    )

    with pytest.raises(ValueError, match="B1V3_B2_AVAILABILITY_SCHEMA_INVALID"):
        apply_b2_availability_sidecar(
            canonical.drop("b2v2_cutoff_utc"),
            sidecar,
            canonical_variant="primary_5m_60s",
        )
    with pytest.raises(ValueError, match="B1V3_B2_CANONICAL_DUPLICATE_ORIGIN"):
        apply_b2_availability_sidecar(
            pl.concat([canonical, canonical]),
            sidecar,
            canonical_variant="primary_5m_60s",
        )
    with pytest.raises(ValueError, match="B1V3_B2_SIDECAR_DUPLICATE_ORIGIN"):
        apply_b2_availability_sidecar(
            canonical,
            pl.concat([sidecar, sidecar]),
            canonical_variant="primary_5m_60s",
        )
    with pytest.raises(ValueError, match="B1V3_B2_SIDECAR_ORIGIN_MISSING"):
        apply_b2_availability_sidecar(
            canonical,
            sidecar.with_columns(pl.lit("AAPL:missing").alias("origin_id")),
            canonical_variant="primary_5m_60s",
        )
    future = canonical.with_columns(
        pl.lit(datetime(2024, 8, 2, 14, 34, 1, tzinfo=UTC)).alias(
            "b2v2_max_created_at_utc"
        )
    )
    with pytest.raises(ValueError, match="B1V3_B2_FUTURE_CREATED_AT"):
        apply_b2_availability_sidecar(
            future,
            sidecar,
            canonical_variant="primary_5m_60s",
        )


def test_assembled_panel_preserves_origins_and_explicit_component_missingness() -> None:
    origins = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            "asset": ["AAPL", "AAPL"],
            "session_date": ["2024-08-02", "2024-08-02"],
            "forecast_origin_utc": [
                datetime(2024, 8, 2, 14, 35, tzinfo=UTC),
                datetime(2024, 8, 2, 14, 40, tzinfo=UTC),
            ],
            "forecast_origin_ns": [1_722_609_300_000_000_000, 1_722_609_600_000_000_000],
            "role": ["training_warmup", "training_warmup"],
            "session_minute": [5, 10],
            "session_tercile": ["first", "first"],
        }
    )
    b0 = origins.select("origin_id").with_columns(
        pl.Series("b0_complete", [True, True]),
        pl.Series("b0_missing_reason", [None, None], dtype=pl.String),
        *[
            pl.Series(feature, [1.0, 1.0])
            if feature != "b0v2_asset_identity"
            else pl.Series(feature, ["AAPL", "AAPL"])
            for feature in B0V2_FEATURES
        ],
    )
    b1 = pl.DataFrame(
        {
            "origin_id": ["AAPL:1"],
            **{feature: [1.0] for feature in B1V3_FEATURES},
            "b1v3a_complete": [True],
            "b1v3b_complete": [True],
            "b1v3c_complete": [True],
            "max_sip_timestamp_ns": [1_722_609_299_000_000_000],
        }
    )
    b2 = pl.DataFrame(
        {
            "origin_id": ["AAPL:1", "AAPL:2"],
            **{feature: [1.0, None] for feature in B2_FEATURE_NAMES},
            "b2v2_availability_eligible": [True, False],
            "b2v2_availability_status": [
                "PIT_USABLE_ELIGIBLE_ACTIVITY",
                "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES",
            ],
            "b2v2_max_created_at_utc": [
                datetime(2024, 8, 2, 14, 34, tzinfo=UTC),
                None,
            ],
            "b2v2_cutoff_utc": [
                datetime(2024, 8, 2, 14, 34, tzinfo=UTC),
                datetime(2024, 8, 2, 14, 39, tzinfo=UTC),
            ],
        }
    )

    panel = assemble_predictor_panel(origins=origins, b0=b0, b1=b1, b2=b2)

    assert panel.height == origins.height
    assert panel["origin_id"].to_list() == origins["origin_id"].to_list()
    assert panel.filter(pl.col("origin_id") == "AAPL:2")["b1v3a_complete"].item() is False
    assert panel.filter(pl.col("origin_id") == "AAPL:2")["b1v3_missing_reason"].item() == (
        "B1V3_SOURCE_ROW_MISSING"
    )
    assert not any("rv30" in column.lower() for column in panel.columns)
