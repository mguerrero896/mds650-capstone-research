"""Development-only diagnostics for the registered B1v3 information set.

The functions in this module may consume rolling-training outcomes supplied by
the caller.  They reject every session in the new independent replication block
and never choose a diagnostic, feature, or model from a replication result.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Final

import numpy as np
import polars as pl
from numpy.typing import NDArray

from mds650.b1v3 import B1V3A_FEATURES
from mds650.b1v3_confirmation import canonical_sha256
from mds650.modeling import FittedPositiveModel

B1_DIAGNOSTIC_FAMILIES: Final[tuple[str, ...]] = (
    "SOURCE_AND_NESTED_FEATURE_COVERAGE",
    "QUOTE_QUALITY_AND_SESSION_CONCENTRATION",
    "IV_INVERSION_AND_GEOMETRY",
    "EXACT_WITHIN_SESSION_LAGS",
    "FEATURE_SCALE_AND_TAILS",
    "COLLINEARITY_AND_GAMMA_SPECIFICATION",
    "CHRONOLOGICAL_LOSS_AND_TEMPORAL_DRIFT",
)
_HASH_LENGTH: Final = 64


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _HASH_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _terminal_reason(row: Mapping[str, Any]) -> str:
    if not bool(row.get("b0_information_set_complete")):
        return "B0_INCOMPLETE"
    if _finite_or_none(row.get(B1V3A_FEATURES[0])) is None:
        return "B1_LEVEL_GEOMETRY_MISSING"
    if _finite_or_none(row.get(B1V3A_FEATURES[1])) is None:
        return "B1_EXACT_5M_LAG_MISSING"
    if _finite_or_none(row.get(B1V3A_FEATURES[2])) is None:
        return "B1_EXACT_30M_LAG_MISSING"
    if not bool(row.get("b1v3a_information_set_complete")):
        return "B1_NESTED_COMPLETENESS_INVALID"
    return "B1V3A_COMPLETE"


def _scopes(asset: str, tercile: str) -> tuple[tuple[str, str], ...]:
    return (
        ("ALL", "ALL"),
        (asset, "ALL"),
        ("ALL", tercile),
        (asset, tercile),
    )


def build_reason_waterfall(frame: pl.DataFrame) -> pl.DataFrame:
    """Build an exhaustive B1v3a terminal-reason waterfall.

    Parameters
    ----------
    frame:
        One row per training forecast origin with B0 and B1v3a completeness.

    Returns
    -------
    polars.DataFrame
        Counts globally, by asset, by session tercile, and by their cross.

    Raises
    ------
    ValueError
        If identities, scope columns, or required B1 fields are invalid.
    """
    required = {
        "origin_id",
        "asset",
        "session_tercile",
        "b0_information_set_complete",
        "b1v3a_information_set_complete",
        *B1V3A_FEATURES,
    }
    if not required <= set(frame.columns) or frame.is_empty():
        raise ValueError("B1_DIAGNOSTIC_FEATURE_SCHEMA_INVALID")
    if frame["origin_id"].n_unique() != frame.height:
        raise ValueError("B1_DIAGNOSTIC_DUPLICATE_ORIGIN")

    counts: Counter[tuple[str, str, str]] = Counter()
    denominators: Counter[tuple[str, str]] = Counter()
    for row in frame.iter_rows(named=True):
        asset = str(row["asset"])
        tercile = str(row["session_tercile"])
        reason = _terminal_reason(row)
        for scope in _scopes(asset, tercile):
            denominators[scope] += 1
            counts[(*scope, reason)] += 1
    rows = [
        {
            "asset": asset,
            "session_tercile": tercile,
            "eligible_origin_count": denominators[(asset, tercile)],
            "terminal_reason_code": reason,
            "terminal_count": count,
            "terminal_share": count / denominators[(asset, tercile)],
        }
        for (asset, tercile, reason), count in sorted(counts.items())
    ]
    result = pl.DataFrame(rows, infer_schema_length=None)
    for group in result.partition_by(["asset", "session_tercile"]):
        if group["terminal_count"].sum() != group["eligible_origin_count"][0]:
            raise ValueError("B1_DIAGNOSTIC_WATERFALL_NOT_EXHAUSTIVE")
    return result.sort(["asset", "session_tercile", "terminal_reason_code"])


def summarize_quote_quality(
    attempts: pl.DataFrame,
    origin_scope: pl.DataFrame,
) -> pl.DataFrame:
    """Summarize quote and IV evidence without inspecting any outcome.

    Parameters
    ----------
    attempts:
        Contract-origin IV attempts from the rolling training block.
    origin_scope:
        Unique origin-to-session-tercile mapping.

    Returns
    -------
    polars.DataFrame
        Quote, IV, age, spread, and failure counts for all registered scopes.

    Raises
    ------
    ValueError
        If schemas or origin mappings are invalid.
    """
    required_attempts = {
        "origin_id",
        "asset",
        "session_date",
        "sip_timestamp",
        "iv_success",
        "failure_reason",
        "quote_age_seconds",
        "relative_spread",
    }
    if not required_attempts <= set(attempts.columns) or attempts.is_empty():
        raise ValueError("B1_DIAGNOSTIC_ATTEMPT_SCHEMA_INVALID")
    if not {"origin_id", "session_tercile"} <= set(origin_scope.columns):
        raise ValueError("B1_DIAGNOSTIC_ORIGIN_SCOPE_INVALID")
    if origin_scope["origin_id"].n_unique() != origin_scope.height:
        raise ValueError("B1_DIAGNOSTIC_ORIGIN_SCOPE_DUPLICATE")
    joined = attempts.join(origin_scope, on="origin_id", how="left", validate="m:1")
    if joined["session_tercile"].null_count():
        raise ValueError("B1_DIAGNOSTIC_ATTEMPT_ORIGIN_UNBOUND")

    grouped: defaultdict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in joined.iter_rows(named=True):
        asset = str(row["asset"])
        tercile = str(row["session_tercile"])
        for scope in _scopes(asset, tercile):
            grouped[scope].append(row)
    output: list[dict[str, Any]] = []
    for (asset, tercile), rows in sorted(grouped.items()):
        ages = [
            value
            for row in rows
            if (value := _finite_or_none(row.get("quote_age_seconds"))) is not None
        ]
        spreads = [
            value
            for row in rows
            if (value := _finite_or_none(row.get("relative_spread"))) is not None
        ]
        failures = Counter(str(row.get("failure_reason") or "NONE") for row in rows)
        output.append(
            {
                "asset": asset,
                "session_tercile": tercile,
                "attempt_count": len(rows),
                "quote_returned_count": sum(row.get("sip_timestamp") is not None for row in rows),
                "iv_success_count": sum(bool(row.get("iv_success")) for row in rows),
                "median_quote_age_seconds": float(np.median(ages)) if ages else None,
                "p95_quote_age_seconds": float(np.quantile(ages, 0.95)) if ages else None,
                "median_relative_spread": float(np.median(spreads)) if spreads else None,
                "p95_relative_spread": float(np.quantile(spreads, 0.95)) if spreads else None,
                "failure_reason_counts_json": json.dumps(
                    dict(sorted(failures.items())), sort_keys=True, separators=(",", ":")
                ),
            }
        )
    return pl.DataFrame(output, infer_schema_length=None).sort(["asset", "session_tercile"])


def summarize_iv_geometry(attempts: pl.DataFrame) -> pl.DataFrame:
    """Summarize quote and IV success across contractual option geometry.

    Parameters
    ----------
    attempts:
        Contract-origin attempts with DTE bucket, option type, target
        moneyness, quote quality, and IV outcome.

    Returns
    -------
    polars.DataFrame
        One deterministic row per asset, bucket, option type, and target
        moneyness combination.

    Raises
    ------
    ValueError
        If the attempt schema is incomplete or no rows are supplied.
    """
    required = {
        "asset",
        "bucket",
        "option_type",
        "target_moneyness",
        "dte",
        "sip_timestamp",
        "iv_success",
        "failure_reason",
        "quote_age_seconds",
        "relative_spread",
    }
    if attempts.is_empty() or not required <= set(attempts.columns):
        raise ValueError("B1_DIAGNOSTIC_IV_GEOMETRY_SCHEMA_INVALID")
    rows: list[dict[str, Any]] = []
    keys = ["asset", "bucket", "option_type", "target_moneyness"]
    for group in attempts.sort(keys).partition_by(keys, maintain_order=True):
        identity = group.row(0, named=True)
        ages = [
            value
            for raw in group["quote_age_seconds"].to_list()
            if (value := _finite_or_none(raw)) is not None
        ]
        spreads = [
            value
            for raw in group["relative_spread"].to_list()
            if (value := _finite_or_none(raw)) is not None
        ]
        dtes = [
            value
            for raw in group["dte"].to_list()
            if (value := _finite_or_none(raw)) is not None
        ]
        successes = int(group["iv_success"].cast(pl.Int64).sum())
        failures = Counter(
            str(value or "NONE") for value in group["failure_reason"].to_list()
        )
        rows.append(
            {
                "asset": str(identity["asset"]),
                "bucket": str(identity["bucket"]),
                "option_type": str(identity["option_type"]),
                "target_moneyness": float(identity["target_moneyness"]),
                "attempt_count": group.height,
                "quote_returned_count": int(group["sip_timestamp"].is_not_null().sum()),
                "iv_success_count": successes,
                "iv_success_rate": successes / group.height,
                "median_dte": float(np.median(dtes)) if dtes else None,
                "median_quote_age_seconds": float(np.median(ages)) if ages else None,
                "median_relative_spread": float(np.median(spreads)) if spreads else None,
                "failure_reason_counts_json": json.dumps(
                    dict(sorted(failures.items())), sort_keys=True, separators=(",", ":")
                ),
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None).sort(keys)


def summarize_lag_availability(frame: pl.DataFrame) -> pl.DataFrame:
    """Measure B1 level and exact-lag availability by asset/session scope.

    Parameters
    ----------
    frame:
        Predictor-only rolling-training origins.

    Returns
    -------
    polars.DataFrame
        Counts and rates globally, by asset, by session tercile, and jointly.

    Raises
    ------
    ValueError
        If origin identity, scope, or B1v3a fields are missing.
    """
    required = {"origin_id", "asset", "session_tercile", *B1V3A_FEATURES}
    if frame.is_empty() or not required <= set(frame.columns):
        raise ValueError("B1_DIAGNOSTIC_LAG_SCHEMA_INVALID")
    if frame["origin_id"].n_unique() != frame.height:
        raise ValueError("B1_DIAGNOSTIC_LAG_ORIGIN_DUPLICATE")
    grouped: defaultdict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in frame.iter_rows(named=True):
        for scope in _scopes(str(row["asset"]), str(row["session_tercile"])):
            grouped[scope].append(row)
    rows: list[dict[str, Any]] = []
    for (asset, tercile), origins in sorted(grouped.items()):
        counts = [
            sum(_finite_or_none(row.get(feature)) is not None for row in origins)
            for feature in B1V3A_FEATURES
        ]
        rows.append(
            {
                "asset": asset,
                "session_tercile": tercile,
                "origin_count": len(origins),
                "level_available_count": counts[0],
                "lag_5m_available_count": counts[1],
                "lag_30m_available_count": counts[2],
                "level_available_rate": counts[0] / len(origins),
                "lag_5m_available_rate": counts[1] / len(origins),
                "lag_30m_available_rate": counts[2] / len(origins),
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None).sort(["asset", "session_tercile"])


def summarize_feature_distributions(
    frame: pl.DataFrame,
    features: Sequence[str],
) -> pl.DataFrame:
    """Describe finite feature coverage, scale, and tails.

    Parameters
    ----------
    frame:
        Diagnostic rows.
    features:
        Numeric feature names to summarize.

    Returns
    -------
    polars.DataFrame
        One deterministic row per feature.

    Raises
    ------
    ValueError
        If a feature is missing or the request is empty.
    """
    requested = tuple(features)
    if not requested or not set(requested) <= set(frame.columns):
        raise ValueError("B1_DIAGNOSTIC_DISTRIBUTION_FEATURE_INVALID")
    rows: list[dict[str, Any]] = []
    for feature in requested:
        values = np.asarray(
            [
                value
                for raw in frame[feature].to_list()
                if (value := _finite_or_none(raw)) is not None
            ],
            dtype=np.float64,
        )
        mean = float(np.mean(values)) if values.size else None
        standard_deviation = float(np.std(values)) if values.size else None
        threshold = max(abs(mean or 0.0) * 1e-10, 1e-12)
        rows.append(
            {
                "feature": feature,
                "row_count": frame.height,
                "finite_count": int(values.size),
                "missing_or_nonfinite_count": int(frame.height - values.size),
                "mean": mean,
                "standard_deviation": standard_deviation,
                "p05": float(np.quantile(values, 0.05)) if values.size else None,
                "median": float(np.median(values)) if values.size else None,
                "p95": float(np.quantile(values, 0.95)) if values.size else None,
                "near_constant": bool(
                    standard_deviation is not None and standard_deviation <= threshold
                ),
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


def collinearity_diagnostics(
    frame: pl.DataFrame,
    features: Sequence[str],
) -> dict[str, Any]:
    """Calculate target-free rank and conditioning diagnostics.

    Parameters
    ----------
    frame:
        Predictor rows.
    features:
        Numeric columns in contractual order.

    Returns
    -------
    dict[str, Any]
        Complete-row count, zero-variance fields, rank, condition number, and
        strongest pairwise correlation.

    Raises
    ------
    ValueError
        If columns are absent or no complete finite row exists.
    """
    requested = tuple(features)
    if not requested or not set(requested) <= set(frame.columns):
        raise ValueError("B1_DIAGNOSTIC_COLLINEARITY_FEATURE_INVALID")
    raw: NDArray[np.float64] = frame.select(requested).to_numpy().astype(
        np.float64, copy=False
    )
    complete = raw[np.isfinite(raw).all(axis=1)]
    if complete.shape[0] == 0:
        raise ValueError("B1_DIAGNOSTIC_COLLINEARITY_NO_COMPLETE_ROW")
    means = np.mean(complete, axis=0)
    standard_deviations = np.std(complete, axis=0)
    variable_mask = standard_deviations > np.maximum(np.abs(means) * 1e-12, 1e-15)
    zero_variance = [
        name for name, variable in zip(requested, variable_mask, strict=True) if not variable
    ]
    variable = complete[:, variable_mask]
    variable_names = [
        name for name, keep in zip(requested, variable_mask, strict=True) if keep
    ]
    standardized: NDArray[np.float64]
    if variable.shape[1]:
        standardized = (variable - np.mean(variable, axis=0)) / np.std(variable, axis=0)
        rank = int(np.linalg.matrix_rank(standardized))
        condition_raw = float(np.linalg.cond(standardized))
    else:
        standardized = np.empty((complete.shape[0], 0), dtype=np.float64)
        rank = 0
        condition_raw = math.inf
    max_correlation: float | None = None
    max_pair: list[str] | None = None
    if standardized.shape[1] >= 2:
        for left in range(standardized.shape[1]):
            for right in range(left + 1, standardized.shape[1]):
                observed = abs(
                    float(np.mean(standardized[:, left] * standardized[:, right]))
                )
                if max_correlation is None or observed > max_correlation:
                    max_correlation = observed
                    max_pair = [variable_names[left], variable_names[right]]
    return {
        "feature_count": len(requested),
        "complete_row_count": int(complete.shape[0]),
        "zero_variance_features": zero_variance,
        "matrix_rank": rank,
        "rank_deficient": rank < len(requested),
        "condition_number": condition_raw if math.isfinite(condition_raw) else None,
        "condition_number_nonfinite": not math.isfinite(condition_raw),
        "max_absolute_pairwise_correlation": max_correlation,
        "max_correlation_pair": max_pair,
    }


def chronological_b1_loss_deltas(forecasts: pl.DataFrame) -> list[dict[str, Any]]:
    """Calculate paired development-only B0 minus B1v3a QLIKE deltas.

    Parameters
    ----------
    forecasts:
        Chronological OOF forecasts containing the registered B0 and B1v3a
        information sets.

    Returns
    -------
    list[dict[str, Any]]
        Fold-level deltas globally, by asset, and by session tercile. Positive
        values favor B1v3a.

    Raises
    ------
    ValueError
        If forecasts are unpaired, duplicated, non-finite, or not Gamma OOF.
    """
    required = {
        "origin_id",
        "asset",
        "session_date",
        "session_tercile",
        "fold",
        "information_set",
        "model_role",
        "qlike_loss",
    }
    if forecasts.is_empty() or not required <= set(forecasts.columns):
        raise ValueError("B1_DIAGNOSTIC_OOF_SCHEMA_INVALID")
    selected = forecasts.filter(pl.col("information_set").is_in(["B0", "B1v3a"]))
    if (
        set(selected["information_set"].unique()) != {"B0", "B1v3a"}
        or set(selected["model_role"].unique()) != {"gamma_glm_confirmatory"}
    ):
        raise ValueError("B1_DIAGNOSTIC_OOF_CONTRACT_INVALID")
    keys = ["origin_id", "asset", "session_date", "session_tercile", "fold"]
    left = selected.filter(pl.col("information_set") == "B0").select(
        *keys, pl.col("qlike_loss").alias("b0_loss")
    )
    right = selected.filter(pl.col("information_set") == "B1v3a").select(
        *keys, pl.col("qlike_loss").alias("b1_loss")
    )
    if left.select(keys).is_duplicated().any() or right.select(keys).is_duplicated().any():
        raise ValueError("B1_DIAGNOSTIC_OOF_DUPLICATE")
    paired = left.join(right, on=keys, how="inner", validate="1:1").with_columns(
        (pl.col("b0_loss") - pl.col("b1_loss")).alias("loss_difference")
    )
    if paired.height != left.height or paired.height != right.height:
        raise ValueError("B1_DIAGNOSTIC_OOF_UNPAIRED")
    values = paired.select("b0_loss", "b1_loss", "loss_difference").to_numpy()
    if not np.isfinite(values).all():
        raise ValueError("B1_DIAGNOSTIC_OOF_NONFINITE")
    output: list[dict[str, Any]] = []
    for fold in sorted(int(value) for value in paired["fold"].unique().to_list()):
        fold_frame = paired.filter(pl.col("fold") == fold)
        scopes: list[tuple[str, str, str, pl.DataFrame]] = [
            ("GLOBAL", "ALL", "ALL", fold_frame)
        ]
        scopes.extend(
            ("ASSET", str(asset), "ALL", fold_frame.filter(pl.col("asset") == asset))
            for asset in sorted(fold_frame["asset"].unique().to_list())
        )
        scopes.extend(
            (
                "SESSION_TERCILE",
                "ALL",
                str(tercile),
                fold_frame.filter(pl.col("session_tercile") == tercile),
            )
            for tercile in sorted(fold_frame["session_tercile"].unique().to_list())
        )
        for scope, asset, tercile, group in scopes:
            differences = [float(value) for value in group["loss_difference"].to_list()]
            output.append(
                {
                    "fold": fold,
                    "scope": scope,
                    "asset": asset,
                    "session_tercile": tercile,
                    "observation_count": group.height,
                    "session_count": group["session_date"].n_unique(),
                    "delta_b1v3": math.fsum(differences) / group.height,
                    "positive_value_favors": "B1v3a",
                }
            )
    return output


def extract_gamma_coefficients(
    fitted: FittedPositiveModel,
    *,
    information_set: str,
    selected_parameters: Mapping[str, float | int],
) -> list[dict[str, Any]]:
    """Extract named link-scale Gamma coefficients from a fitted pipeline.

    Parameters
    ----------
    fitted:
        Registered fitted positive model.
    information_set:
        Information-set label associated with the fit.
    selected_parameters:
        Training-only selected Gamma parameters.

    Returns
    -------
    list[dict[str, Any]]
        Intercept and transformed-feature coefficients in estimator order.

    Raises
    ------
    ValueError
        If the fitted role, estimator shape, names, or values are invalid.
    """
    if fitted.role != "gamma_glm_confirmatory" or not information_set:
        raise ValueError("B1_DIAGNOSTIC_GAMMA_MODEL_INVALID")
    steps: Any = fitted.estimator.named_steps
    preprocess: Any = steps.get("preprocess")
    model: Any = steps.get("model")
    if preprocess is None or model is None:
        raise ValueError("B1_DIAGNOSTIC_GAMMA_PIPELINE_INVALID")
    names = [str(value) for value in preprocess.get_feature_names_out()]
    coefficients = np.asarray(model.coef_, dtype=np.float64).reshape(-1)
    intercept = float(model.intercept_)
    if (
        len(names) != coefficients.size
        or not np.isfinite(coefficients).all()
        or not math.isfinite(intercept)
    ):
        raise ValueError("B1_DIAGNOSTIC_GAMMA_COEFFICIENT_INVALID")
    parameters_json = json.dumps(
        dict(selected_parameters), sort_keys=True, separators=(",", ":")
    )
    rows = [
        {
            "information_set": information_set,
            "feature": "__INTERCEPT__",
            "coefficient": intercept,
            "scale": "GAMMA_LOG_LINK",
            "selected_parameters_json": parameters_json,
        }
    ]
    rows.extend(
        {
            "information_set": information_set,
            "feature": name,
            "coefficient": float(coefficient),
            "scale": "STANDARDIZED_NUMERIC_OR_ONE_HOT_GAMMA_LOG_LINK",
            "selected_parameters_json": parameters_json,
        }
        for name, coefficient in zip(names, coefficients, strict=True)
    )
    return rows


def _validate_finite_records(records: Sequence[Mapping[str, Any]], *, code: str) -> None:
    for record in records:
        for value in record.values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(code)


def build_b1_diagnostic_document(
    *,
    feature_frame: pl.DataFrame,
    attempt_frame: pl.DataFrame,
    training_sessions: Sequence[str],
    replication_sessions: Sequence[str],
    source_hashes: Mapping[str, str],
    chronological_loss_deltas: Sequence[Mapping[str, Any]],
    gamma_coefficients: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic, self-hashed B1 diagnostic document.

    Parameters
    ----------
    feature_frame, attempt_frame:
        Rolling-training B1 feature and quote/IV evidence.
    training_sessions, replication_sessions:
        Frozen disjoint date arrays. Replication dates are metadata only.
    source_hashes:
        SHA-256 identities for every diagnostic source.
    chronological_loss_deltas, gamma_coefficients:
        Development-only registered model diagnostics.

    Returns
    -------
    dict[str, Any]
        Complete diagnostic with a canonical self-hash and zero replication
        target reads.

    Raises
    ------
    ValueError
        If scope, hashes, identities, or numeric evidence are invalid.
    """
    training = tuple(str(value) for value in training_sessions)
    replication = tuple(str(value) for value in replication_sessions)
    if (
        len(training) != 60
        or len(replication) != 30
        or list(training) != sorted(set(training))
        or list(replication) != sorted(set(replication))
        or set(training) & set(replication)
    ):
        raise ValueError("B1_DIAGNOSTIC_SESSION_SCOPE_INVALID")
    feature_dates = set(feature_frame["session_date"].cast(pl.String).unique())
    attempt_dates = set(attempt_frame["session_date"].cast(pl.String).unique())
    if feature_dates & set(replication) or attempt_dates & set(replication):
        raise ValueError("B1_DIAGNOSTIC_REPLICATION_DATE_READ")
    if not feature_dates <= set(training) or not attempt_dates <= set(training):
        raise ValueError("B1_DIAGNOSTIC_NONTRAINING_DATE_READ")
    if not source_hashes or not all(_is_sha256(value) for value in source_hashes.values()):
        raise ValueError("B1_DIAGNOSTIC_SOURCE_HASH_INVALID")
    _validate_finite_records(chronological_loss_deltas, code="B1_DIAGNOSTIC_LOSS_NONFINITE")
    _validate_finite_records(gamma_coefficients, code="B1_DIAGNOSTIC_COEFFICIENT_NONFINITE")

    origin_scope = feature_frame.select("origin_id", "session_tercile")
    waterfall = build_reason_waterfall(feature_frame)
    quote_quality = summarize_quote_quality(attempt_frame, origin_scope)
    iv_geometry = summarize_iv_geometry(attempt_frame)
    lag_availability = summarize_lag_availability(feature_frame)
    b0_numeric = tuple(
        column
        for column in feature_frame.columns
        if column.startswith("b0v2_")
        and column != "b0v2_asset_identity"
        and feature_frame[column].dtype.is_numeric()
    )
    distributions = summarize_feature_distributions(feature_frame, B1V3A_FEATURES)
    collinearity = collinearity_diagnostics(
        feature_frame.filter(pl.col("b1v3a_information_set_complete")),
        (*b0_numeric, *B1V3A_FEATURES),
    )
    document: dict[str, Any] = {
        "schema_version": "b1-diagnostic-1.0",
        "status": "PASS_DEVELOPMENT_ONLY_DIAGNOSTIC",
        "target_blind_replication": True,
        "replication_target_reads": 0,
        "training_sessions": list(training),
        "replication_sessions_metadata_only": list(replication),
        "diagnostic_families": list(B1_DIAGNOSTIC_FAMILIES),
        "source_hashes": dict(sorted(source_hashes.items())),
        "scope": {
            "feature_origin_count": feature_frame.height,
            "attempt_count": attempt_frame.height,
            "asset_count": feature_frame["asset"].n_unique(),
            "training_session_count": len(training),
        },
        "reason_waterfall": waterfall.to_dicts(),
        "quote_quality": quote_quality.to_dicts(),
        "iv_geometry": iv_geometry.to_dicts(),
        "lag_availability": lag_availability.to_dicts(),
        "feature_distributions": distributions.to_dicts(),
        "collinearity": collinearity,
        "chronological_loss_deltas": [dict(record) for record in chronological_loss_deltas],
        "gamma_coefficients": [dict(record) for record in gamma_coefficients],
        "interpretation_boundary": {
            "causal_claim": "PROHIBITED",
            "replication_sign_used_for_diagnosis": False,
            "trading_or_pnl_claim": "PROHIBITED",
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document
