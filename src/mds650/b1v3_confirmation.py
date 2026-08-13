"""Target-free B1v3 exposure ledger and deterministic 60/30 planner."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import exchange_calendars as xcals  # type: ignore[import-untyped]

_DATE_RE: Final[re.Pattern[str]] = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
_FORBIDDEN_SOURCE_TOKENS: Final[tuple[str, ...]] = (
    "result",
    "qlike",
    "prediction",
    "forecast",
    "rv30",
    "outcome",
)


@dataclass(frozen=True, slots=True)
class ExposureSource:
    """One date-only source used to establish prior analytical exposure.

    Parameters
    ----------
    logical_name:
        Sanitized stable role; never a personal absolute path.
    path:
        JSON source from which ISO dates are extracted recursively.
    """

    logical_name: str
    path: Path


@dataclass(frozen=True, slots=True)
class PristineSplit:
    """Deterministic disjoint training and confirmation session arrays."""

    training_sessions: tuple[str, ...]
    confirmation_sessions: tuple[str, ...]

    @property
    def all_sessions(self) -> tuple[str, ...]:
        """Return training followed by confirmation sessions."""
        return (*self.training_sessions, *self.confirmation_sessions)


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize JSON canonically for a semantic SHA-256."""
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Mapping[str, Any]) -> str:
    """Return the lower-case SHA-256 of canonical JSON."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash one source file without loading it into memory."""
    if chunk_size <= 0:
        raise ValueError("B1V3_CONFIRMATION_HASH_CHUNK_INVALID")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_dates(value: object) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        if _DATE_RE.fullmatch(value):
            values.append(value)
        elif re.fullmatch(r"20\d{2}-[^\s]*", value):
            raise ValueError("B1V3_EXPOSURE_DATE_INVALID")
    elif isinstance(value, list):
        for item in value:
            values.extend(_extract_dates(item))
    elif isinstance(value, dict):
        for item in value.values():
            values.extend(_extract_dates(item))
    return values


def _is_xnys_session(value: str) -> bool:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("B1V3_EXPOSURE_DATE_INVALID") from exc
    calendar = xcals.get_calendar("XNYS")
    return bool(calendar.is_session(parsed))


def build_session_exposure_ledger(
    sources: Sequence[ExposureSource],
) -> dict[str, Any]:
    """Build a source-bound date-only exposure ledger.

    Parameters
    ----------
    sources:
        Explicit allowlist of JSON manifests containing previously used dates.

    Returns
    -------
    dict[str, Any]
        Sanitized self-hashed ledger. File contents other than date strings are
        not retained or interpreted.

    Raises
    ------
    ValueError
        If a source is absent, outcome-like by filename, malformed, duplicated
        by logical identity, or contains a non-XNYS date.
    """
    if not sources:
        raise ValueError("B1V3_EXPOSURE_SOURCES_EMPTY")
    source_records: list[dict[str, Any]] = []
    session_sources: dict[str, set[str]] = defaultdict(set)
    seen_names: set[str] = set()
    for source in sources:
        if not source.logical_name.strip() or source.logical_name in seen_names:
            raise ValueError("B1V3_EXPOSURE_SOURCE_NAME_INVALID")
        seen_names.add(source.logical_name)
        if any(token in source.path.name.lower() for token in _FORBIDDEN_SOURCE_TOKENS):
            raise ValueError("B1V3_EXPOSURE_SOURCE_FORBIDDEN")
        if not source.path.is_file() or source.path.suffix.lower() != ".json":
            raise ValueError("B1V3_EXPOSURE_SOURCE_INVALID")
        decoded = json.loads(source.path.read_text(encoding="utf-8"))
        dates = sorted(set(_extract_dates(decoded)))
        if not dates:
            raise ValueError("B1V3_EXPOSURE_SOURCE_NO_DATES")
        for value in dates:
            if not _is_xnys_session(value):
                raise ValueError("B1V3_EXPOSURE_NOT_XNYS_SESSION")
            session_sources[value].add(source.logical_name)
        source_records.append(
            {
                "logical_name": source.logical_name,
                "filename": source.path.name,
                "sha256": sha256_file(source.path),
                "date_count": len(dates),
                "first_date": dates[0],
                "last_date": dates[-1],
            }
        )
    source_records.sort(key=lambda record: str(record["logical_name"]))
    exposed = sorted(session_sources)
    ledger: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "PASS_DATE_ONLY_EXPOSURE_LEDGER",
        "target_blind": True,
        "sources": source_records,
        "exposed_session_count": len(exposed),
        "first_exposed_session": exposed[0],
        "last_exposed_session": exposed[-1],
        "exposed_sessions": exposed,
        "sessions": [
            {
                "date": value,
                "source_logical_names": sorted(session_sources[value]),
            }
            for value in exposed
        ],
    }
    ledger["ledger_sha256"] = canonical_sha256(ledger)
    return ledger


def enumerate_xnys_sessions(start: date, end: date) -> tuple[str, ...]:
    """Enumerate official XNYS sessions inclusively between two dates."""
    if end < start:
        raise ValueError("B1V3_CONFIRMATION_DATE_RANGE_INVALID")
    calendar = xcals.get_calendar("XNYS")
    values = calendar.sessions_in_range(start, end)
    return tuple(value.date().isoformat() for value in values)


def _validated_sessions(values: Sequence[str], *, code: str) -> tuple[str, ...]:
    sessions = tuple(values)
    if not sessions or list(sessions) != sorted(set(sessions)):
        raise ValueError(code)
    if any(not _DATE_RE.fullmatch(value) or not _is_xnys_session(value) for value in sessions):
        raise ValueError(code)
    return sessions


def _contiguous_xnys(values: Sequence[str]) -> bool:
    if not values:
        return False
    expected = enumerate_xnys_sessions(
        date.fromisoformat(values[0]),
        date.fromisoformat(values[-1]),
    )
    return tuple(values) == expected


def select_pristine_split(
    *,
    eligible_sessions: Sequence[str],
    exposed_sessions: Iterable[str],
    training_count: int = 60,
    confirmation_count: int = 30,
) -> PristineSplit:
    """Select the earliest contiguous unexposed training/confirmation block.

    Parameters
    ----------
    eligible_sessions:
        Ordered provider-eligible XNYS sessions.
    exposed_sessions:
        Dates forbidden because any prior analytical workflow used them.
    training_count, confirmation_count:
        Frozen sizes. The confirmation count must remain thirty.

    Returns
    -------
    PristineSplit
        Earliest deterministic contiguous block.

    Raises
    ------
    ValueError
        If inputs are invalid or no pristine 30-session block exists.
    """
    if training_count <= 0 or confirmation_count != 30:
        raise ValueError("B1V3_CONFIRMATION_COUNTS_INVALID")
    eligible = _validated_sessions(
        eligible_sessions,
        code="B1V3_ELIGIBLE_SESSIONS_INVALID",
    )
    exposed = set(exposed_sessions)
    required = training_count + confirmation_count
    for start in range(0, len(eligible) - required + 1):
        candidate = eligible[start : start + required]
        if exposed.intersection(candidate):
            continue
        if not _contiguous_xnys(candidate):
            continue
        return PristineSplit(
            training_sessions=candidate[:training_count],
            confirmation_sessions=candidate[training_count:],
        )
    raise ValueError("NO_PRISTINE_30_SESSION_BLOCK")


def build_confirmation_plan(
    *,
    exposure_ledger: Mapping[str, Any],
    candidate_sessions: Sequence[str],
    provider_passed_sessions: Sequence[str] | None,
) -> dict[str, Any]:
    """Build a target-free plan, pending or frozen according to provider evidence.

    Provider evidence is never inferred from historical documentation. When no
    daily preflight result is supplied, dates are provisional and acquisition
    remains blocked.
    """
    expected_hash = canonical_sha256(
        {key: value for key, value in exposure_ledger.items() if key != "ledger_sha256"}
    )
    if exposure_ledger.get("ledger_sha256") != expected_hash:
        raise ValueError("B1V3_EXPOSURE_LEDGER_HASH_INVALID")
    exposed_value = exposure_ledger.get("exposed_sessions")
    if not isinstance(exposed_value, list) or not all(
        isinstance(value, str) for value in exposed_value
    ):
        raise ValueError("B1V3_EXPOSURE_LEDGER_SCHEMA_INVALID")
    candidates = _validated_sessions(
        candidate_sessions,
        code="B1V3_CANDIDATE_SESSIONS_INVALID",
    )
    exposed = tuple(exposed_value)
    provider_passed: tuple[str, ...] = ()
    if provider_passed_sessions is None:
        selection_source = candidates
        status = "PENDING_DATE_LEVEL_PROVIDER_PREFLIGHT"
        safe_to_acquire = False
    else:
        provider_passed = _validated_sessions(
            provider_passed_sessions,
            code="B1V3_PROVIDER_PASSED_SESSIONS_INVALID",
        )
        if not set(provider_passed).issubset(candidates):
            raise ValueError("B1V3_PROVIDER_SESSIONS_OUTSIDE_CANDIDATES")
        selection_source = provider_passed
        status = "PASS_PRISTINE_60_30_FROZEN"
        safe_to_acquire = True
    try:
        split = select_pristine_split(
            eligible_sessions=selection_source,
            exposed_sessions=exposed,
        )
    except ValueError as exc:
        if str(exc) != "NO_PRISTINE_30_SESSION_BLOCK":
            raise
        split = PristineSplit((), ())
        status = "NO_PRISTINE_30_SESSION_BLOCK"
        safe_to_acquire = False
    overlap = sorted(set(split.all_sessions) & set(exposed))
    if overlap:
        raise ValueError("B1V3_CONFIRMATION_EXPOSED_OVERLAP")
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "status": status,
        "target_blind": True,
        "safe_to_acquire": safe_to_acquire,
        "safe_to_read_outcomes": False,
        "calendar": "XNYS",
        "selection_rule": "EARLIEST_CONTIGUOUS_PRISTINE_60_TRAINING_30_CONFIRMATION",
        "exposure_ledger_sha256": expected_hash,
        "candidate_session_count": len(candidates),
        "candidate_first_session": candidates[0],
        "candidate_last_session": candidates[-1],
        "provider_preflight": {
            "required_providers": ["fmp", "massive", "unusual_whales"],
            "required_session_count": 90,
            "passed_session_count": len(provider_passed),
            "status": (
                "PASS_DAILY_CONTINUITY_90_OF_90"
                if len(provider_passed) >= 90 and status == "PASS_PRISTINE_60_30_FROZEN"
                else "NOT_ESTABLISHED"
            ),
        },
        "training_session_count": len(split.training_sessions),
        "confirmation_session_count": len(split.confirmation_sessions),
        "training_sessions": list(split.training_sessions),
        "confirmation_sessions": list(split.confirmation_sessions),
        "exposed_overlap": overlap,
        "outcome_read_count": 0,
    }
    plan["plan_sha256"] = canonical_sha256(plan)
    return plan


def write_json_if_identical(path: Path, payload: bytes) -> str:
    """Create an immutable JSON file or confirm byte identity."""
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("B1V3_CONFIRMATION_OUTPUT_CONFLICT")
        return "IDENTICAL"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(payload)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return "CREATED"
