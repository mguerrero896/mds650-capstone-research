"""Fail-closed access control for the prospective Phase 5 holdout."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from mds650.study_design import canonical_sha256

EXPECTED_HOLDOUT_SESSIONS = (
    "2026-07-20",
    "2026-07-21",
    "2026-07-22",
    "2026-07-23",
    "2026-07-24",
    "2026-07-27",
    "2026-07-28",
    "2026-07-29",
    "2026-07-30",
    "2026-07-31",
)
HOLDOUT_PERIOD_COMPLETE_UTC = datetime(2026, 7, 31, 20, 0, tzinfo=UTC)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_GATES = frozenset(
    {
        "provider_source_hashes_valid",
        "common_panel_valid",
        "leakage_tests_passed",
        "full_test_suite_green",
    }
)
FROZEN_PHASE5_SOURCE_PATHS = (
    "scripts/acquire_phase5_holdout.py",
    "scripts/build_b2_calibration_20d.py",
    "scripts/build_phase5_common_panel.py",
    "scripts/build_phase5_stability_inputs.py",
    "scripts/download_calibration_20d.py",
    "scripts/phase4a_common.py",
    "scripts/phase4b_common.py",
    "scripts/run_b1_calibration_20d.py",
    "scripts/run_b1_closure.py",
    "scripts/run_phase4b.py",
    "scripts/run_phase5_development_evaluation.py",
    "scripts/run_phase5_holdout.py",
    "src/mds650/contracts.py",
    "src/mds650/holdout.py",
    "src/mds650/metrics.py",
    "src/mds650/modeling.py",
    "src/mds650/phase5_features.py",
    "src/mds650/phase5_panel.py",
    "src/mds650/phase5_storage.py",
    "src/mds650/stability.py",
    "src/mds650/study_design.py",
    "src/mds650/targets.py",
    "src/mds650/temporal_validation.py",
)


def _valid_self_hash(payload: Mapping[str, Any]) -> bool:
    manifest_hash = payload.get("manifest_sha256")
    unsigned = {
        key: value for key, value in payload.items() if key != "manifest_sha256"
    }
    return isinstance(manifest_hash, str) and manifest_hash == canonical_sha256(
        unsigned
    )


def authorize_holdout_read(
    holdout: Mapping[str, Any],
    method_freeze: Mapping[str, Any],
    now_utc: datetime,
) -> dict[str, Any]:
    """Authorize and consume the sole analytical holdout read.

    Parameters
    ----------
    holdout:
        Acquired, unread access ledger with ten complete session records.
    method_freeze:
        Self-hashed development method frozen before the holdout.
    now_utc:
        Aware current timestamp used to enforce period completion.

    Returns
    -------
    dict[str, Any]
        New self-hashed ledger with the irreversible ``0 -> 1`` transition.

    Raises
    ------
    ValueError
        If ``now_utc`` is naive.
    PermissionError
        If any timing, evidence, hash, method or one-read gate fails.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("HOLDOUT_NOW_MUST_BE_TIMEZONE_AWARE")
    if holdout.get("holdout_reads") != 0:
        raise PermissionError("HOLDOUT_ALREADY_READ")
    if now_utc.astimezone(UTC) < HOLDOUT_PERIOD_COMPLETE_UTC:
        raise PermissionError("HOLDOUT_PERIOD_INCOMPLETE")
    if not _valid_self_hash(holdout):
        raise PermissionError("HOLDOUT_LEDGER_HASH_MISMATCH")
    if not _valid_self_hash(method_freeze):
        raise PermissionError("METHOD_FREEZE_SELF_HASH_INVALID")
    if (
        method_freeze.get("status")
        != "FROZEN_AFTER_DEVELOPMENT_BEFORE_HOLDOUT"
        or method_freeze.get("holdout_reads") != 0
        or not method_freeze.get("holdout_hyperparameters")
    ):
        raise PermissionError("METHOD_FREEZE_INVALID")
    if (
        holdout.get("method_freeze_sha256")
        != method_freeze.get("manifest_sha256")
    ):
        raise PermissionError("METHOD_FREEZE_HASH_MISMATCH")
    if holdout.get("preregistration_sha256") != method_freeze.get(
        "input_hashes", {}
    ).get("preregistration.json"):
        raise PermissionError("PREREGISTRATION_HASH_MISMATCH")
    if holdout.get("status") != "ACQUIRED_NOT_READ":
        raise PermissionError("HOLDOUT_NOT_ACQUIRED")
    if holdout.get("last_session_complete") is not True:
        raise PermissionError("HOLDOUT_PERIOD_INCOMPLETE")
    if holdout.get("holdout_sessions") != list(EXPECTED_HOLDOUT_SESSIONS):
        raise PermissionError("HOLDOUT_SESSION_SET_MISMATCH")
    session_statuses = holdout.get("session_statuses")
    if not isinstance(session_statuses, list) or [
        row.get("session_date") for row in session_statuses if isinstance(row, dict)
    ] != list(EXPECTED_HOLDOUT_SESSIONS) or any(
        not isinstance(row, dict) or row.get("status") != "PASS"
        for row in session_statuses
    ):
        raise PermissionError("HOLDOUT_SESSION_EVIDENCE_INCOMPLETE")
    gates = holdout.get("release_gates")
    if (
        not isinstance(gates, dict)
        or set(gates) != _RELEASE_GATES
        or not all(gates.values())
    ):
        raise PermissionError("HOLDOUT_RELEASE_GATES_FAILED")
    panel_hash = holdout.get("panel_sha256")
    if not isinstance(panel_hash, str) or not _SHA256.fullmatch(panel_hash):
        raise PermissionError("HOLDOUT_PANEL_HASH_INVALID")

    result = copy.deepcopy(dict(holdout))
    previous_hash = result.pop("manifest_sha256")
    result.update(
        {
            "status": "READ_ONCE",
            "holdout_reads": 1,
            "authorized_at_utc": now_utc.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "previous_manifest_sha256": previous_hash,
        }
    )
    result["manifest_sha256"] = canonical_sha256(result)
    return result
