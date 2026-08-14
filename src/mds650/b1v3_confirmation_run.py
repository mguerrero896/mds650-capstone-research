"""Fail-closed helpers for the single B1v3 confirmation evaluation.

This module has no provider transport and does not discover paths.  It binds
the already-authorized RV30 values to immutable predictor identities, prepares
registered timing intersections, and consumes the sole confirmation token with
an exclusive filesystem create before a target reader may run.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import polars as pl

from mds650.b1v3_confirmation import sha256_file
from mds650.b1v3_evaluation import b1v3_information_sets
from mds650.study_design import canonical_sha256

_OUTCOME_ASSETS: Final[frozenset[str]] = frozenset(
    {"AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA"}
)
_FORBIDDEN: Final[tuple[bytes, ...]] = (
    b"c:\\users\\",
    b"c:/users/",
    b"d:\\mds650",
    b"d:/mds650",
    b"api_key",
    b"apikey",
    b"authorization",
    b"bearer ",
)


def _self_hash_valid(document: Mapping[str, Any]) -> bool:
    stored = document.get("manifest_sha256")
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    return isinstance(stored, str) and stored == canonical_sha256(unsigned)


def _confirmation_sessions(preregistration: Mapping[str, Any]) -> set[str]:
    sessions = preregistration.get("confirmation_sessions")
    if not isinstance(sessions, list) or len(sessions) != 30:
        raise ValueError("B1V3_CONFIRMATION_DATE_SCOPE_INVALID")
    parsed = {str(value) for value in sessions}
    if len(parsed) != 30:
        raise ValueError("B1V3_CONFIRMATION_DATE_SCOPE_INVALID")
    return parsed


def _authorization_valid(
    authorization: Mapping[str, Any], preregistration: Mapping[str, Any]
) -> bool:
    return (
        _self_hash_valid(authorization)
        and _self_hash_valid(preregistration)
        and authorization.get("status") == "CONFIRMATION_EVALUATION_IN_PROGRESS"
        and authorization.get("safe_to_evaluate_b1v3") == "YES"
        and authorization.get("outcome_read_count") == 2
        and authorization.get("training_read_count") == 1
        and authorization.get("confirmation_read_count") == 1
        and authorization.get("evaluation_attempt_count") == 1
        and authorization.get("results_inspected") is False
        and authorization.get("preregistration_manifest_sha256")
        == preregistration.get("manifest_sha256")
        and authorization.get("common_panel_sha256")
        == preregistration.get("common_predictor_panel_sha256")
    )


def bind_b1v3_confirmation_targets(
    common_predictors: pl.DataFrame,
    target_frame: pl.DataFrame,
    *,
    preregistration: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> pl.DataFrame:
    """Bind exact confirmation RV30 values to the frozen predictor panel.

    Parameters
    ----------
    common_predictors:
        Predictor-only panel containing the registered confirmation origins.
    target_frame:
        Output of ``build_b0v2_features`` for exactly the 30 authorized dates,
        with 31 closes and 30 one-minute returns per valid target.
    preregistration, authorization:
        Self-hashed frozen method scope and already-consumed access token.

    Returns
    -------
    polars.DataFrame
        Identical complete-case confirmation rows with one RV30 per origin.

    Raises
    ------
    ValueError
        If access, origin identity, B0 equality, timing, target geometry, or
        common complete-case scope drifts.
    """
    if not _authorization_valid(authorization, preregistration):
        raise ValueError("B1V3_CONFIRMATION_ACCESS_DENIED")
    information_sets = b1v3_information_sets()
    b0_features = information_sets["B0"]
    all_features = information_sets["B2"]
    common_required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "session_tercile",
        "b0_information_set_complete",
        "b1v3a_information_set_complete",
        "b2_information_set_complete",
        *all_features,
    }
    target_required = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "target_price_count",
        "target_return_count",
        "rv30",
        "drop_reason",
        "max_predictor_available_at_utc",
        *b0_features,
    }
    if not common_required <= set(common_predictors.columns):
        raise ValueError("B1V3_CONFIRMATION_COMMON_SCHEMA_INVALID")
    if not target_required <= set(target_frame.columns):
        raise ValueError("B1V3_CONFIRMATION_TARGET_SCHEMA_INVALID")
    sessions = _confirmation_sessions(preregistration)
    confirmation = common_predictors.filter(pl.col("role") == "confirmation")
    if (
        confirmation.is_empty()
        or confirmation["origin_id"].n_unique() != confirmation.height
        or set(confirmation["session_date"].cast(pl.String).unique()) != sessions
        or set(confirmation["asset"].cast(pl.String).unique()) != _OUTCOME_ASSETS
    ):
        raise ValueError("B1V3_CONFIRMATION_COMMON_SCOPE_INVALID")
    if (
        target_frame.is_empty()
        or target_frame["origin_id"].n_unique() != target_frame.height
        or set(target_frame["role"].cast(pl.String).unique()) != {"confirmation"}
        or set(target_frame["session_date"].cast(pl.String).unique()) != sessions
        or set(target_frame["asset"].cast(pl.String).unique()) != _OUTCOME_ASSETS
    ):
        raise ValueError("B1V3_CONFIRMATION_TARGET_SCOPE_INVALID")
    keys = ("origin_id", "asset", "session_date", "forecast_origin_utc")
    if not confirmation.select(keys).sort("origin_id").equals(
        target_frame.select(keys).sort("origin_id"), null_equal=True
    ):
        raise ValueError("B1V3_CONFIRMATION_ORIGIN_IDENTITY_MISMATCH")
    if not confirmation.select("origin_id", *b0_features).sort("origin_id").equals(
        target_frame.select("origin_id", *b0_features).sort("origin_id"),
        null_equal=True,
    ):
        raise ValueError("B1V3_CONFIRMATION_B0_DRIFT")
    if target_frame.filter(
        pl.col("max_predictor_available_at_utc").is_null()
        | (pl.col("max_predictor_available_at_utc") > pl.col("forecast_origin_utc"))
    ).height:
        raise ValueError("B1V3_CONFIRMATION_PREDICTOR_FUTURE")
    if target_frame.filter(
        (pl.col("target_price_count") != 31)
        | (pl.col("target_return_count") != 30)
        | pl.col("drop_reason").is_not_null()
        | ~pl.col("rv30").is_finite()
        | (pl.col("rv30") <= 0)
    ).height:
        raise ValueError("B1V3_CONFIRMATION_RV30_CONTRACT_INVALID")
    target_values = target_frame.select(
        "origin_id",
        "target_price_count",
        "target_return_count",
        "rv30",
        pl.col("drop_reason").alias("rv30_drop_reason"),
    )
    bound = confirmation.join(
        target_values,
        on="origin_id",
        how="left",
        validate="1:1",
        maintain_order="left",
    )
    complete = bound.filter(
        pl.col("b0_information_set_complete")
        & pl.col("b1v3a_information_set_complete")
        & pl.col("b2_information_set_complete")
    )
    if (
        complete.is_empty()
        or set(complete["session_date"].cast(pl.String).unique()) != sessions
        or set(complete["asset"].cast(pl.String).unique()) != _OUTCOME_ASSETS
        or complete["rv30"].null_count() > 0
    ):
        raise ValueError("B1V3_CONFIRMATION_COMPLETE_SAMPLE_INVALID")
    return complete.sort(["session_date", "forecast_origin_utc", "asset"])


def join_registered_timing_targets(
    timing_predictors: pl.DataFrame,
    primary_panel: pl.DataFrame,
) -> pl.DataFrame:
    """Join one timing variant to targets on the primary complete-case intersection.

    The function never imputes an unavailable timing value.  It first requires
    all nested information sets for the variant, then intersects exact
    ``origin_id`` values with the already-bound primary panel.
    """
    features = b1v3_information_sets()["B2"]
    required_predictors = {
        "origin_id",
        "asset",
        "session_date",
        "forecast_origin_utc",
        "role",
        "session_tercile",
        "b0_information_set_complete",
        "b1v3a_information_set_complete",
        "b2_information_set_complete",
        *features,
    }
    required_targets = {
        "origin_id",
        "target_price_count",
        "target_return_count",
        "rv30",
        "rv30_drop_reason",
    }
    if not required_predictors <= set(timing_predictors.columns):
        raise ValueError("B1V3_TIMING_PREDICTOR_SCHEMA_INVALID")
    if not required_targets <= set(primary_panel.columns):
        raise ValueError("B1V3_TIMING_TARGET_SCHEMA_INVALID")
    if (
        timing_predictors["origin_id"].n_unique() != timing_predictors.height
        or primary_panel["origin_id"].n_unique() != primary_panel.height
    ):
        raise ValueError("B1V3_TIMING_ORIGIN_DUPLICATE")
    eligible = timing_predictors.filter(
        pl.col("b0_information_set_complete")
        & pl.col("b1v3a_information_set_complete")
        & pl.col("b2_information_set_complete")
    )
    targets = primary_panel.select(*required_targets)
    joined = eligible.join(
        targets,
        on="origin_id",
        how="inner",
        validate="1:1",
        maintain_order="left",
    )
    numeric = [feature for feature in features if feature != "b0v2_asset_identity"]
    if (
        joined.is_empty()
        or joined["origin_id"].n_unique() != joined.height
        or joined.filter(
            (pl.col("target_price_count") != 31)
            | (pl.col("target_return_count") != 30)
            | pl.col("rv30_drop_reason").is_not_null()
            | ~pl.col("rv30").is_finite()
            | (pl.col("rv30") <= 0)
            | pl.any_horizontal(
                ~pl.col(name).cast(pl.Float64, strict=False).is_finite() for name in numeric
            )
        ).height
    ):
        raise ValueError("B1V3_TIMING_TARGET_INTERSECTION_INVALID")
    return joined.sort(["session_date", "forecast_origin_utc", "asset"])


def consume_authorization_exclusively(
    path: Path, authorization: Mapping[str, Any]
) -> str:
    """Atomically consume the one-read token before any confirmation target read.

    The file is created with exclusive-create semantics.  A crash after this
    point intentionally leaves the evaluation consumed and requires a new,
    explicitly approved confirmation design rather than a silent retry.
    """
    if (
        not _self_hash_valid(authorization)
        or authorization.get("status") != "CONFIRMATION_EVALUATION_IN_PROGRESS"
        or authorization.get("confirmation_read_count") != 1
        or authorization.get("evaluation_attempt_count") != 1
        or authorization.get("results_inspected") is not False
    ):
        raise ValueError("B1V3_CONFIRMATION_AUTHORIZATION_INVALID")
    payload = (
        json.dumps(authorization, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if any(token in payload.lower() for token in _FORBIDDEN):
        raise ValueError("B1V3_CONFIRMATION_AUTHORIZATION_HYGIENE_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError("B1V3_CONFIRMATION_ALREADY_CONSUMED") from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return sha256_file(path)
