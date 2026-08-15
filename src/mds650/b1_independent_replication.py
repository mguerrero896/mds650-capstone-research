"""Target-blind freeze for the Phase 7 independent temporal replication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Final

import exchange_calendars as xcals  # type: ignore[import-untyped]

from mds650.b1v3_confirmation import canonical_sha256
from mds650.b1v3_evaluation import b1v3_information_sets, b1v3_method_contract
from mds650.b1v3_provider_preflight_v2 import (
    CandidatePreflightPlan,
    CandidateSession,
    derive_xnys_calendar_sessions,
)

_HASH_LENGTH: Final = 64
_TERMINAL_STATES: Final[tuple[str, ...]] = (
    "REPLICATED_MODEL_INDEPENDENT",
    "REPLICATED_GAMMA_ONLY",
    "NOT_REPLICATED",
    "INVALID_REPLICATION",
)
_REPLICATION_ASSETS: Final[tuple[str, ...]] = (
    "AAPL",
    "AMZN",
    "META",
    "MSFT",
    "NVDA",
    "TSLA",
)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _HASH_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _validated_sessions(
    values: Sequence[str],
    *,
    expected: int,
    code: str,
) -> list[str]:
    sessions = [str(value) for value in values]
    try:
        parsed = [date.fromisoformat(value) for value in sessions]
    except ValueError as exc:
        raise ValueError(code) from exc
    if len(sessions) != expected or parsed != sorted(set(parsed)):
        raise ValueError(code)
    calendar = xcals.get_calendar("XNYS")
    observed = [
        str(value.date())
        for value in calendar.sessions_in_range(sessions[0], sessions[-1])
    ]
    if observed != sessions:
        raise ValueError(code)
    return sessions


def _source_dates(source: Mapping[str, Any], key: str) -> list[str]:
    raw = source.get(key)
    if not isinstance(raw, list):
        raise ValueError("EXPOSURE_SOURCE_DATE_ARRAY_INVALID")
    try:
        return [date.fromisoformat(str(value)).isoformat() for value in raw]
    except ValueError as exc:
        raise ValueError("EXPOSURE_SOURCE_DATE_ARRAY_INVALID") from exc


def collect_exposed_result_dates(
    *,
    phase5_ledger: Mapping[str, Any],
    b1v3_plan: Mapping[str, Any],
    independent_window: Mapping[str, Any],
) -> list[str]:
    """Collect prior exposed dates from three explicitly allowlisted documents.

    Parameters
    ----------
    phase5_ledger:
        Date-only Phase 5/6 exposure ledger.
    b1v3_plan:
        Provider-passed 60/30 B1v3 confirmation plan.
    independent_window:
        Previously sealed independent-replication window manifest.

    Returns
    -------
    list[str]
        Sorted unique union of only the allowlisted date arrays.

    Raises
    ------
    ValueError
        If any source status or date array is invalid.
    """
    if (
        phase5_ledger.get("status") != "PASS_DATE_ONLY_EXPOSURE_LEDGER"
        or b1v3_plan.get("status") != "PASS_PRISTINE_60_30_FROZEN"
        or independent_window.get("status")
        != "READY_FOR_BOUNDED_BODY_ACQUISITION"
    ):
        raise ValueError("EXPOSURE_SOURCE_STATUS_INVALID")
    dates = {
        *_source_dates(phase5_ledger, "exposed_sessions"),
        *_source_dates(b1v3_plan, "training_sessions"),
        *_source_dates(b1v3_plan, "confirmation_sessions"),
        *_source_dates(independent_window, "all_dates"),
    }
    return sorted(dates)


def build_exposure_ledger(
    *,
    training_sessions: Sequence[str],
    replication_sessions: Sequence[str],
    exposed_result_dates: Sequence[str],
    prior_evidence_cutoff_session: date,
    design_sha256: str,
) -> dict[str, Any]:
    """Freeze exact date roles before provider payload or outcome access.

    Parameters
    ----------
    training_sessions, replication_sessions:
        Exact ordered XNYS arrays of length 60 and 30.
    exposed_result_dates:
        Date-only inventory of every prior prediction, loss, OOS read, or
        reported scientific result.
    prior_evidence_cutoff_session:
        Last session in the reusable training/evidence source. Every new
        replication session must follow it.
    design_sha256:
        Identity of the approved Phase 7 design.

    Returns
    -------
    dict[str, Any]
        Date-only, zero-read, canonically self-hashed exposure ledger.

    Raises
    ------
    ValueError
        If counts, XNYS membership, order, overlap, chronology, or hashes fail.
    """
    training = _validated_sessions(
        training_sessions,
        expected=60,
        code="TRAINING_SESSION_INVALID",
    )
    replication = _validated_sessions(
        replication_sessions,
        expected=30,
        code="REPLICATION_SESSION_INVALID",
    )
    if not _is_sha256(design_sha256):
        raise ValueError("REPLICATION_DESIGN_HASH_INVALID")
    try:
        exposed = sorted(
            {date.fromisoformat(str(value)).isoformat() for value in exposed_result_dates}
        )
    except ValueError as exc:
        raise ValueError("EXPOSED_RESULT_DATE_INVALID") from exc
    overlap = set(training) & set(replication)
    if overlap:
        raise ValueError("REPLICATION_TRAINING_OVERLAP")
    if set(replication) & set(exposed):
        raise ValueError("REPLICATION_DATE_PREVIOUSLY_EXPOSED")
    if any(
        date.fromisoformat(value) <= prior_evidence_cutoff_session for value in replication
    ):
        raise ValueError("REPLICATION_NOT_AFTER_EVIDENCE_CUTOFF")
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-exposure-1.0",
        "status": "FROZEN_DATE_ONLY_ZERO_READS",
        "training_sessions": training,
        "replication_sessions": replication,
        "exposed_result_dates": exposed,
        "prior_evidence_cutoff_session": prior_evidence_cutoff_session.isoformat(),
        "overlap_count": 0,
        "provider_payload_reads": 0,
        "replication_target_reads": 0,
        "design_sha256": design_sha256,
    }
    document["ledger_sha256"] = canonical_sha256(document)
    return document


def build_replication_preregistration(
    *,
    exposure_ledger: Mapping[str, Any],
    design_sha256: str,
    code_sha256: str,
    uv_lock_sha256: str,
) -> dict[str, Any]:
    """Freeze methods and hypotheses before any new provider payload.

    Parameters
    ----------
    exposure_ledger:
        Valid date-only zero-read ledger.
    design_sha256, code_sha256, uv_lock_sha256:
        Immutable design, implementation, and environment identities.

    Returns
    -------
    dict[str, Any]
        Self-hashed preregistration with provider and outcome access closed.

    Raises
    ------
    ValueError
        If the ledger or source identities do not match the frozen contract.
    """
    hashes = (design_sha256, code_sha256, uv_lock_sha256)
    if not all(_is_sha256(value) for value in hashes):
        raise ValueError("REPLICATION_PREREGISTRATION_HASH_INVALID")
    stored = exposure_ledger.get("ledger_sha256")
    unsigned = {key: value for key, value in exposure_ledger.items() if key != "ledger_sha256"}
    if (
        exposure_ledger.get("status") != "FROZEN_DATE_ONLY_ZERO_READS"
        or exposure_ledger.get("provider_payload_reads") != 0
        or exposure_ledger.get("replication_target_reads") != 0
        or stored != canonical_sha256(unsigned)
        or exposure_ledger.get("design_sha256") != design_sha256
    ):
        raise ValueError("REPLICATION_EXPOSURE_LEDGER_INVALID")
    method = b1v3_method_contract()
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-preregistration-1.0",
        "status": "FROZEN_BEFORE_PROVIDER_PAYLOAD",
        "target_blind": True,
        "safe_to_access_replication_targets": "NO",
        "provider_payload_reads_at_freeze": 0,
        "replication_target_reads": 0,
        "exposure_ledger_sha256": stored,
        "training_sessions": list(exposure_ledger["training_sessions"]),
        "replication_sessions": list(exposure_ledger["replication_sessions"]),
        "information_sets": {
            name: list(features) for name, features in b1v3_information_sets().items()
        },
        "method": method,
        "estimands": {
            "delta_b1v3": "QLIKE(B0)-QLIKE(B1v3a)",
            "delta_b2": "QLIKE(B1v3a)-QLIKE(B2)",
            "positive_value_favors": "EXPANDED_INFORMATION_SET",
        },
        "mde_policy": "TRAINING_ONLY_DAILY_CLUSTERS_BEFORE_REPLICATION",
        "timing_sensitivities": {
            "fmp_minutes": [1, 2],
            "massive_cutoff_seconds": [0, 60, 300],
            "uw_created_at_cutoff_seconds": [60, 120, 300],
        },
        "storage_policy": {
            "heavy_root": "MDS650_B1_REPLICATION_DATA_ROOT",
            "minimum_projected_free_gib": 80,
        },
        "result_sign_selection": "PROHIBITED",
        "permitted_terminal_states": list(_TERMINAL_STATES),
        "source_hashes": {
            "design_sha256": design_sha256,
            "code_sha256": code_sha256,
            "uv_lock_sha256": uv_lock_sha256,
        },
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def build_replication_provider_preflight_plan(
    preregistration: Mapping[str, Any],
) -> CandidatePreflightPlan:
    """Bind the frozen 30-session replication block to a provider preflight.

    Parameters
    ----------
    preregistration:
        Valid zero-provider-read, zero-target-read Phase 7 preregistration.

    Returns
    -------
    CandidatePreflightPlan
        Six-asset, 30-session, calendar-bound target-blind provider plan.

    Raises
    ------
    ValueError
        If self-hash, status, read counters, sessions, or calendar metadata fail.
    """
    stored_hash = preregistration.get("manifest_sha256")
    unsigned = {
        key: value for key, value in preregistration.items() if key != "manifest_sha256"
    }
    if (
        preregistration.get("status") != "FROZEN_BEFORE_PROVIDER_PAYLOAD"
        or preregistration.get("provider_payload_reads_at_freeze") != 0
        or preregistration.get("replication_target_reads") != 0
        or not _is_sha256(stored_hash)
        or stored_hash != canonical_sha256(unsigned)
    ):
        raise ValueError("REPLICATION_PROVIDER_PREREGISTRATION_INVALID")
    raw_sessions = preregistration.get("replication_sessions")
    if not isinstance(raw_sessions, list):
        raise ValueError("REPLICATION_PROVIDER_SESSION_INVALID")
    sessions = _validated_sessions(
        [str(value) for value in raw_sessions],
        expected=30,
        code="REPLICATION_PROVIDER_SESSION_INVALID",
    )
    calendar_rows = derive_xnys_calendar_sessions(sessions)
    candidates: list[CandidateSession] = []
    for raw in calendar_rows:
        values = (
            raw.get("date"),
            raw.get("open_utc"),
            raw.get("close_utc"),
            raw.get("forecast_origin_utc"),
        )
        forecast_ns = raw.get("forecast_origin_ns")
        expected_minutes = raw.get("expected_regular_minutes")
        if (
            not all(isinstance(value, str) for value in values)
            or isinstance(forecast_ns, bool)
            or not isinstance(forecast_ns, int)
            or isinstance(expected_minutes, bool)
            or not isinstance(expected_minutes, int)
        ):
            raise ValueError("REPLICATION_PROVIDER_CALENDAR_INVALID")
        candidates.append(
            CandidateSession(
                date=str(values[0]),
                role="confirmation",
                open_utc=str(values[1]),
                close_utc=str(values[2]),
                forecast_origin_utc=str(values[3]),
                forecast_origin_ns=forecast_ns,
                expected_regular_minutes=expected_minutes,
            )
        )
    base: dict[str, Any] = {
        "schema_version": "b1-independent-replication-provider-plan-1.0",
        "status": "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION",
        "target_blind": True,
        "outcome_read_count": 0,
        "assets": list(_REPLICATION_ASSETS),
        "sessions": [
            {
                "date": session.date,
                "role": session.role,
                "open_utc": session.open_utc,
                "close_utc": session.close_utc,
                "forecast_origin_utc": session.forecast_origin_utc,
                "forecast_origin_ns": session.forecast_origin_ns,
                "expected_regular_minutes": session.expected_regular_minutes,
            }
            for session in candidates
        ],
        "training_session_count": 0,
        "confirmation_session_count": 30,
        "source_confirmation_plan_sha256": stored_hash,
    }
    plan_sha256 = canonical_sha256(base)
    return CandidatePreflightPlan(
        schema_version=str(base["schema_version"]),
        status=str(base["status"]),
        target_blind=True,
        outcome_read_count=0,
        assets=_REPLICATION_ASSETS,
        sessions=tuple(candidates),
        training_session_count=0,
        confirmation_session_count=30,
        source_confirmation_plan_sha256=str(stored_hash),
        plan_sha256=plan_sha256,
    )
