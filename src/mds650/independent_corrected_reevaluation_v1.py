"""Target-blind audit and preregistration for corrected independent B1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import polars as pl

from mds650.phase6 import B0V2_FEATURES, B1V2A_FEATURES, B2V2_FEATURES
from mds650.study_design import canonical_sha256

_SCHEMA_VERSION = "independent-corrected-reevaluation-v1.0"
_STATUS = "FROZEN_AUTHORIZED_BEFORE_CORRECTED_REEVALUATION"


def audit_corrected_b1(
    *, origins: pl.DataFrame, features: pl.DataFrame, attempts: pl.DataFrame
) -> dict[str, Any]:
    """Validate corrected B1 without reading RV30, predictions, or metrics.

    Parameters
    ----------
    origins:
        Frozen forecast-origin table.
    features:
        Corrected B1 feature table, one row per origin.
    attempts:
        Contract-level IV-attempt table used to build ``features``.

    Returns
    -------
    dict[str, Any]
        Sanitized audit counts and coverage measures.

    Raises
    ------
    ValueError
        If origin identity, timing, nesting, exogenous provenance, uniqueness,
        or target-blindness fails.
    """
    required_origin = {"origin_id", "asset", "session_date", "forecast_origin_utc"}
    required_feature = {
        *required_origin,
        "forecast_origin_ns",
        "max_sip_timestamp_ns",
        "b1v2a_complete",
        "b1v2b_complete",
        "b1v2c_complete",
    }
    required_attempt = {
        *required_origin,
        "contract",
        "sip_timestamp_ns",
        "quote_age_seconds",
        "implied_volatility",
        "rate_source_date",
        "exogenous_pit_verified",
    }
    if not required_origin.issubset(origins.columns):
        raise ValueError("CORRECTED_B1_ORIGIN_SCHEMA")
    if not required_feature.issubset(features.columns):
        raise ValueError("CORRECTED_B1_FEATURE_SCHEMA")
    if not required_attempt.issubset(attempts.columns):
        raise ValueError("CORRECTED_B1_ATTEMPT_SCHEMA")

    outcome_columns = sorted(
        name
        for name in {*features.columns, *attempts.columns}
        if name.lower() == "target"
        or name.lower().startswith(("rv30", "qlike", "prediction"))
    )
    if outcome_columns:
        raise ValueError("CORRECTED_B1_OUTCOME_COLUMN")
    if origins["origin_id"].n_unique() != origins.height:
        raise ValueError("CORRECTED_B1_DUPLICATE_ORIGIN")
    if features["origin_id"].n_unique() != features.height:
        raise ValueError("CORRECTED_B1_DUPLICATE_FEATURE_ORIGIN")
    if not origins.select("origin_id").sort("origin_id").equals(
        features.select("origin_id").sort("origin_id")
    ):
        raise ValueError("CORRECTED_B1_ORIGIN_ALIGNMENT")

    duplicate_attempts = (
        attempts.group_by("origin_id", "contract").len().filter(pl.col("len") > 1).height
    )
    if duplicate_attempts:
        raise ValueError("CORRECTED_B1_DUPLICATE_ATTEMPT")
    origin_ns = pl.col("forecast_origin_utc").dt.epoch("ns")
    quote_after_origin_count = attempts.filter(
        pl.col("sip_timestamp_ns").is_not_null()
        & (pl.col("sip_timestamp_ns") > origin_ns)
    ).height
    feature_quote_after_origin_count = features.filter(
        pl.col("max_sip_timestamp_ns").is_not_null()
        & (pl.col("max_sip_timestamp_ns") > pl.col("forecast_origin_ns"))
    ).height
    if quote_after_origin_count or feature_quote_after_origin_count:
        raise ValueError("CORRECTED_B1_FUTURE_QUOTE")
    negative_quote_age_count = attempts.filter(pl.col("quote_age_seconds") < 0).height
    if negative_quote_age_count:
        raise ValueError("CORRECTED_B1_NEGATIVE_QUOTE_AGE")
    rate_not_prior_count = attempts.filter(
        pl.col("rate_source_date").str.to_date()
        >= pl.col("session_date").str.to_date()
    ).height
    if rate_not_prior_count:
        raise ValueError("CORRECTED_B1_NONCAUSAL_RATE")
    if not bool(attempts["exogenous_pit_verified"].all()):
        raise ValueError("CORRECTED_B1_EXOGENOUS_NOT_VERIFIED")
    nonfinite_iv_count = attempts.filter(
        pl.col("implied_volatility").is_not_null()
        & ~pl.col("implied_volatility").is_finite()
    ).height
    if nonfinite_iv_count:
        raise ValueError("CORRECTED_B1_NONFINITE_IV")

    b1b_without_b1a = features.filter(
        pl.col("b1v2b_complete") & ~pl.col("b1v2a_complete")
    ).height
    b1c_without_b1b = features.filter(
        pl.col("b1v2c_complete") & ~pl.col("b1v2b_complete")
    ).height
    if b1b_without_b1a or b1c_without_b1b:
        raise ValueError("CORRECTED_B1_NESTING_INVALID")
    coverage: dict[str, float] = {}
    for name, column in (
        ("b1a_coverage", "b1v2a_complete"),
        ("b1b_coverage", "b1v2b_complete"),
        ("b1c_coverage", "b1v2c_complete"),
    ):
        value = features[column].mean()
        if not isinstance(value, (int, float)):
            raise ValueError("CORRECTED_B1_COVERAGE_INVALID")
        coverage[name] = float(value)
    monotonic = coverage["b1c_coverage"] <= coverage["b1b_coverage"] <= coverage[
        "b1a_coverage"
    ]
    if not monotonic:
        raise ValueError("CORRECTED_B1_COVERAGE_NOT_MONOTONIC")
    by_asset = (
        features.group_by("asset")
        .agg(
            pl.len().alias("origin_count"),
            pl.col("b1v2a_complete").mean().alias("b1a_coverage"),
            pl.col("b1v2b_complete").mean().alias("b1b_coverage"),
            pl.col("b1v2c_complete").mean().alias("b1c_coverage"),
        )
        .sort("asset")
        .to_dicts()
    )
    return {
        "status": "PASS_TARGET_BLIND_CORRECTED_B1",
        "origin_count": features.height,
        "attempt_count": attempts.height,
        **coverage,
        "coverage_by_asset": by_asset,
        "nested_coverage_monotonic": monotonic,
        "duplicate_attempt_count": duplicate_attempts,
        "quote_after_origin_count": quote_after_origin_count + feature_quote_after_origin_count,
        "negative_quote_age_count": negative_quote_age_count,
        "rate_not_strictly_prior_count": rate_not_prior_count,
        "nonfinite_iv_count": nonfinite_iv_count,
        "all_exogenous_inputs_verified": True,
        "outcome_columns_present": outcome_columns,
    }


def build_preregistration(
    *,
    b1_audit: Mapping[str, Any],
    input_hashes: Mapping[str, str],
    source_hashes: Mapping[str, str],
    source_commit: str,
) -> dict[str, Any]:
    """Build the self-hashed corrected independent reevaluation freeze.

    Parameters
    ----------
    b1_audit:
        Target-blind output of :func:`audit_corrected_b1`.
    input_hashes:
        Byte hashes for every frozen analytical input.
    source_hashes:
        Byte hashes for the runner, sealer, builder, and lockfile.
    source_commit:
        Git commit containing the frozen implementation.

    Returns
    -------
    dict[str, Any]
        Self-hashed preregistration authorizing exactly one corrected run.

    Raises
    ------
    ValueError
        If any audit gate or identity is invalid.
    """
    if b1_audit.get("status") != "PASS_TARGET_BLIND_CORRECTED_B1":
        raise ValueError("CORRECTED_PREREG_B1_AUDIT_INVALID")
    if b1_audit.get("nested_coverage_monotonic") is not True:
        raise ValueError("CORRECTED_PREREG_B1_NESTING_INVALID")
    if b1_audit.get("quote_after_origin_count") != 0:
        raise ValueError("CORRECTED_PREREG_FUTURE_QUOTE")
    if b1_audit.get("rate_not_strictly_prior_count") != 0:
        raise ValueError("CORRECTED_PREREG_NONCAUSAL_RATE")
    if b1_audit.get("outcome_columns_present") != []:
        raise ValueError("CORRECTED_PREREG_OUTCOME_COLUMN")
    _require_hash_map(input_hashes, "CORRECTED_PREREG_INPUT_HASH_INVALID")
    _require_hash_map(source_hashes, "CORRECTED_PREREG_SOURCE_HASH_INVALID")
    _require_commit(source_commit)

    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": _STATUS,
        "scientific_role": "CORRECTED_FORENSIC_REEVALUATION",
        "sample_independent_from_phase6": True,
        "pristine_first_read": False,
        "prior_target_results_exist": True,
        "prior_target_read_count": 1,
        "authorized_evaluation_count": 1,
        "corrected_evaluation_performed": False,
        "selection_by_sign": "PROHIBITED",
        "all_signs_must_be_retained": True,
        "tuning_after_freeze": "PROHIBITED",
        "target": {
            "name": "RV30",
            "horizon_minutes": 30,
            "price_count": 31,
            "return_count": 30,
        },
        "information_sets": {
            "B0": list(B0V2_FEATURES),
            "B1a_addition": list(B1V2A_FEATURES),
            "B2_addition": list(B2V2_FEATURES),
        },
        "primary_comparisons": [
            {
                "name": "B1a_vs_B0",
                "estimand": "mean_QLIKE_B0_minus_B1a",
                "positive_favors": "B1a",
            },
            {
                "name": "B2_vs_B1a",
                "estimand": "mean_QLIKE_B1a_minus_B2",
                "positive_favors": "B2",
            },
        ],
        "models": {
            "confirmatory": "Gamma_GLM_log_link_fixed_parameters",
            "robustness": "LightGBM_fixed_parameters_no_tuning",
        },
        "metrics": {"primary": "QLIKE", "secondary": ["MAE", "RMSE"]},
        "inference": {
            "resampling": "PAIRED_TRADING_DAY_CLUSTER_BOOTSTRAP",
            "repetitions": 10000,
            "multiplicity": "HOLM",
            "mde_source": "PHASE6_TRAINING_ONLY_FROZEN",
        },
        "timing": {
            "fmp_primary": "timestamp_raw_plus_1_minute_conservative_assumption",
            "fmp_sensitivity": "timestamp_raw_plus_2_minutes",
            "b1q": "last_SIP_quote_at_or_before_origin_max_age_60s_spread_25pct",
            "b2": "created_at_operational_proxy_at_or_before_origin_minus_60s",
        },
        "sample_limitation": (
            "Independent from Phase 6, but the same target block was previously read under a "
            "superseded B1 input. This run is a corrected forensic reevaluation, not a new "
            "pristine first-read confirmation."
        ),
        "b1_audit": dict(b1_audit),
        "input_hashes": dict(sorted(input_hashes.items())),
        "source_hashes": dict(sorted(source_hashes.items())),
        "source_commit": source_commit,
        "output_contract": {
            "overwrite_existing_results": False,
            "result_status": "CORRECTED_FORENSIC_REEVALUATION_COMPLETE",
            "result_root": "artifacts/independent_replication_pit_v2",
            "bulk_root": "MDS650_DATA_ROOT/independent_replication_30/derived/pit_v2_evaluation",
        },
        "target_or_metric_payload_read_during_freeze": False,
        "model_fit_during_freeze": False,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["preregistration_sha256"] = canonical_sha256(payload)
    return payload


def _require_hash_map(values: Mapping[str, str], error_code: str) -> None:
    """Require a nonempty mapping of lowercase SHA-256 values."""
    if not values:
        raise ValueError(error_code)
    for value in values.values():
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(error_code)


def _require_commit(value: str) -> None:
    """Require a lowercase forty-character Git commit identity."""
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("CORRECTED_PREREG_SOURCE_COMMIT_INVALID")
