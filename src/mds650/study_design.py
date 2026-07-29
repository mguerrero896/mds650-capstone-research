"""Deterministic study-session and preregistration manifests for Phase 5."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import exchange_calendars as xcals  # type: ignore[import-untyped]

B2_FEATURE_NAMES = [
    "b2_log_trade_count",
    "b2_unique_contract_share",
    "b2_log_mean_trade_premium",
    "b2_log_max_trade_premium",
    "b2_call_put_premium_imbalance_scaled",
    "b2_execution_side_premium_imbalance",
    "b2_repeated_contract_premium_share",
    "b2_strike_concentration",
    "b2_expiry_concentration",
]

OUTER_FOLDS = [
    {
        "fold": 1,
        "train_end": "2026-05-19",
        "test_start": "2026-05-20",
        "test_end": "2026-06-03",
    },
    {
        "fold": 2,
        "train_end": "2026-06-03",
        "test_start": "2026-06-04",
        "test_end": "2026-06-17",
    },
    {
        "fold": 3,
        "train_end": "2026-06-17",
        "test_start": "2026-06-18",
        "test_end": "2026-07-02",
    },
    {
        "fold": 4,
        "train_end": "2026-07-02",
        "test_start": "2026-07-06",
        "test_end": "2026-07-17",
    },
]


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    """Hash a JSON object using deterministic key ordering.

    Parameters
    ----------
    payload:
        JSON-serializable mapping.

    Returns
    -------
    str
        Lowercase SHA-256 digest of compact canonical JSON.

    Raises
    ------
    TypeError
        If ``payload`` contains a value that JSON cannot serialize.
    """
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def source_sha256(path: Path) -> str:
    """Hash text source independently of checkout line endings.

    Parameters
    ----------
    path:
        UTF-8-compatible source file to hash.

    Returns
    -------
    str
        Lowercase SHA-256 after normalizing CRLF and CR to LF.
    """
    normalized = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def build_study_sessions(
    calendar_name: str,
    development_end: date,
    development_count: int,
    holdout_count: int,
) -> dict[str, list[str]]:
    """Build ordered development and prospective holdout session arrays.

    Parameters
    ----------
    calendar_name:
        Exchange calendar identifier understood by ``exchange_calendars``.
    development_end:
        Final development trading session.
    development_count, holdout_count:
        Positive numbers of sessions on each side of the boundary.

    Returns
    -------
    dict[str, list[str]]
        ISO dates under ``development`` and ``holdout``.

    Raises
    ------
    ValueError
        If counts are non-positive, the end date is not a session, too few
        sessions are resolved, or the two arrays overlap.

    Examples
    --------
    ``build_study_sessions("XNYS", date(2026, 7, 17), 80, 10)``
    returns the approved 80/10 Phase 5 split.
    """
    if development_count <= 0 or holdout_count <= 0:
        raise ValueError("SESSION_COUNT_MUST_BE_POSITIVE")

    calendar = xcals.get_calendar(calendar_name)
    span_days = (development_count + holdout_count) * 3 + 30
    development_index = calendar.sessions_in_range(
        development_end - timedelta(days=span_days),
        development_end,
    )
    if development_index.empty or development_index[-1].date() != development_end:
        raise ValueError("DEVELOPMENT_END_NOT_SESSION")
    development = [value.date().isoformat() for value in development_index[-development_count:]]
    if len(development) != development_count:
        raise ValueError("STUDY_SESSION_COUNT_INVALID")

    holdout_index = calendar.sessions_in_range(
        development_end + timedelta(days=1),
        development_end + timedelta(days=span_days),
    )
    holdout = [value.date().isoformat() for value in holdout_index[:holdout_count]]
    if len(holdout) != holdout_count:
        raise ValueError("STUDY_SESSION_COUNT_INVALID")
    if set(development) & set(holdout):
        raise ValueError("DEVELOPMENT_HOLDOUT_OVERLAP")
    return {"development": development, "holdout": holdout}


def build_session_manifest(
    sessions: Mapping[str, Sequence[str]],
    *,
    calendar_name: str = "XNYS",
) -> dict[str, Any]:
    """Create a self-hashed manifest for two disjoint ordered session arrays.

    Parameters
    ----------
    sessions:
        Mapping containing ``development`` and ``holdout`` date sequences.
    calendar_name:
        Calendar used to resolve the sequences.

    Returns
    -------
    dict[str, Any]
        Deterministic manifest with counts, boundaries and a self-hash.

    Raises
    ------
    ValueError
        If either sequence is empty, contains duplicates, is unordered, or
        overlaps the other sequence.
    """
    development = list(sessions.get("development", ()))
    holdout = list(sessions.get("holdout", ()))
    if not development or not holdout:
        raise ValueError("STUDY_SESSION_COUNT_INVALID")
    if development != sorted(set(development)) or holdout != sorted(set(holdout)):
        raise ValueError("STUDY_SESSION_ORDER_OR_DUPLICATE_INVALID")
    if set(development) & set(holdout):
        raise ValueError("DEVELOPMENT_HOLDOUT_OVERLAP")

    manifest: dict[str, Any] = {
        "schema_version": "phase5-study-sessions-1.0",
        "calendar": calendar_name,
        "development": development,
        "development_count": len(development),
        "development_start": development[0],
        "development_end": development[-1],
        "holdout": holdout,
        "holdout_count": len(holdout),
        "holdout_start": holdout[0],
        "holdout_end": holdout[-1],
        "disjoint": True,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def build_preregistration(
    session_manifest: Mapping[str, Any],
    *,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the frozen, outcome-blind Phase 5 methodological contract.

    Parameters
    ----------
    session_manifest:
        Self-hashed manifest produced by :func:`build_session_manifest`.
    provenance:
        Branch, commit, Python version, lock hash and approved design hash.

    Returns
    -------
    dict[str, Any]
        Self-hashed preregistration with no forecasts, losses or results.

    Raises
    ------
    ValueError
        If the session manifest, counts, or provenance is incomplete.
    """
    unsigned_sessions = {
        key: value for key, value in session_manifest.items() if key != "manifest_sha256"
    }
    if session_manifest.get("manifest_sha256") != canonical_sha256(unsigned_sessions):
        raise ValueError("SESSION_MANIFEST_HASH_MISMATCH")
    if (
        session_manifest.get("development_count") != 80
        or session_manifest.get("holdout_count") != 10
        or session_manifest.get("disjoint") is not True
    ):
        raise ValueError("STUDY_SESSION_COUNT_INVALID")

    required_provenance = {
        "branch",
        "commit",
        "python_version",
        "uv_lock_sha256",
        "design_sha256",
        "spec_kit_commit",
        "worktree_dirty",
    }
    if required_provenance != set(provenance):
        raise ValueError("PREREGISTRATION_PROVENANCE_INVALID")

    manifest: dict[str, Any] = {
        "schema_version": "phase5-preregistration-1.0",
        "status": "FROZEN_BEFORE_MODEL_OR_QLIKE",
        "approved_on": "2026-07-29",
        "target": {
            "name": "RV30",
            "price_count": 31,
            "return_count": 30,
            "horizon_minutes": 30,
        },
        "session_manifest_sha256": session_manifest["manifest_sha256"],
        "development_sessions": session_manifest["development"],
        "holdout_sessions": session_manifest["holdout"],
        "holdout_reads": 0,
        "information_sets": {
            "B0": [
                "spot",
                "lagged_rv_5m",
                "lagged_rv_30m",
                "lagged_return_5m",
                "lagged_volume_5m",
                "session_minute",
                "asset_identity",
            ],
            "B1a_addition": ["massive_atm_iv_30_60_dte"],
            "B2_addition": B2_FEATURE_NAMES,
        },
        "b2_feature_names": B2_FEATURE_NAMES,
        "feature_design_outcome_blind": True,
        "timing": {
            "fmp_primary_delay_minutes": 1,
            "fmp_sensitivity_delay_minutes": 2,
            "b2_primary_delay_seconds": 60,
            "b2_sensitivity_delay_seconds": [120, 300],
            "created_at_semantics": "OPERATIONAL_AVAILABILITY_PROXY_NOT_PUBLICATION_TIME",
        },
        "missingness": {
            "strategy": "COMMON_COMPLETE_CASE",
            "silent_imputation": False,
            "artificial_balancing": False,
            "valid_empty_activity_ratio": 0,
            "provider_missingness_requires_reason": True,
        },
        "estimands": {
            "delta_b1": "QLIKE(B0)-QLIKE(B1a)",
            "delta_b2": "QLIKE(B1a)-QLIKE(B2)",
            "primary": "delta_b2",
            "positive_direction": "expanded_information_set_better",
        },
        "outer_folds": OUTER_FOLDS,
        "purge_embargo_minutes": 30,
        "models": {
            "confirmatory": {
                "name": "GammaRegressor",
                "role": "CONFIRMATORY",
                "link": "log_fixed_by_estimator",
                "alpha_grid": [0.0, 0.01, 0.1, 1.0],
                "max_iter": 2000,
                "tolerance": 1e-8,
            },
            "robustness": {
                "name": "LGBMRegressor",
                "role": "ROBUSTNESS_CHALLENGER",
                "objective": "gamma",
                "grid": {
                    "num_leaves": [7, 15],
                    "max_depth": [3, 5],
                    "learning_rate": [0.03, 0.05],
                    "n_estimators": [200, 500],
                    "min_child_samples": [50],
                    "reg_lambda": [1.0],
                },
            },
        },
        "metrics": {
            "primary": "QLIKE",
            "secondary": ["MAE", "RMSE"],
        },
        "forecast_floor": 1e-12,
        "inference": {
            "cluster_unit": "XNYS_SESSION_DATE_WITH_ALL_ASSETS",
            "bootstrap_repetitions": 10_000,
            "multiplicity": "Holm",
            "confirmatory_family": ["delta_b1", "delta_b2"],
        },
        "stability": [
            "asset",
            "session_tercile",
            "development_defined_volatility_regime",
            "fmp_delay_1_vs_2_minutes",
            "b2_delay_60_120_300_seconds",
        ],
        "asset_selection": {
            "candidate_assets": [
                "SPY",
                "QQQ",
                "AAPL",
                "MSFT",
                "NVDA",
                "TSLA",
                "AMZN",
                "META",
            ],
            "retained_count_min": 4,
            "retained_count_max": 6,
            "outcome_blind": True,
        },
        "outcome_reporting": "RETAIN_ALL_POSITIVE_NEGATIVE_AND_NULL_RESULTS",
        "seed": 650,
        "provenance": dict(provenance),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def freeze_json(path: Path, payload: Mapping[str, Any]) -> str:
    """Write JSON once and reject any later content drift.

    Parameters
    ----------
    path:
        Destination file.
    payload:
        JSON-serializable mapping to freeze.

    Returns
    -------
    str
        Canonical SHA-256 of the frozen payload.

    Raises
    ------
    ValueError
        If an existing file differs from ``payload`` or is not valid JSON.
    """
    digest = canonical_sha256(payload)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("FROZEN_MANIFEST_CORRUPTED") from error
        if not isinstance(existing, dict) or canonical_sha256(existing) != digest:
            raise ValueError("FROZEN_MANIFEST_DRIFT")
        return digest

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return digest
