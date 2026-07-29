"""Phase 5 session and canonical-hash contracts."""

from __future__ import annotations

import importlib
from datetime import date

import pytest

EXPECTED_HOLDOUT = [
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
]


def _study_design() -> object:
    return importlib.import_module("mds650.study_design")


def test_build_study_sessions_uses_exact_xnys_development_window() -> None:
    result = _study_design().build_study_sessions("XNYS", date(2026, 7, 17), 80, 10)

    assert len(result["development"]) == 80
    assert result["development"][0] == "2026-03-24"
    assert result["development"][-1] == "2026-07-17"
    assert "2026-06-19" not in result["development"]
    assert "2026-07-03" not in result["development"]


def test_build_study_sessions_reserves_exact_prospective_holdout() -> None:
    result = _study_design().build_study_sessions("XNYS", date(2026, 7, 17), 80, 10)

    assert result["holdout"] == EXPECTED_HOLDOUT


def test_build_study_sessions_returns_unique_disjoint_sets() -> None:
    result = _study_design().build_study_sessions("XNYS", date(2026, 7, 17), 80, 10)

    assert len(result["development"]) == len(set(result["development"]))
    assert len(result["holdout"]) == len(set(result["holdout"]))
    assert set(result["development"]).isdisjoint(result["holdout"])


def test_build_study_sessions_rejects_nonpositive_counts() -> None:
    with pytest.raises(ValueError, match="SESSION_COUNT_MUST_BE_POSITIVE"):
        _study_design().build_study_sessions("XNYS", date(2026, 7, 17), 0, 10)


def test_canonical_sha256_is_key_order_independent() -> None:
    left = {"b": [2, 1], "a": {"x": True}}
    right = {"a": {"x": True}, "b": [2, 1]}

    assert _study_design().canonical_sha256(left) == _study_design().canonical_sha256(right)
