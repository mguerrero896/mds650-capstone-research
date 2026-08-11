from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from mds650.canonical_validation import (
    assert_causal_audit,
    assert_identical_origin_sets,
    build_causal_audit,
)
from mds650.temporal_validation import FoldDefinition


def _frame(origin_ids: tuple[str, ...]) -> pl.DataFrame:
    return pl.DataFrame({"origin_id": origin_ids})


def _valid_panel() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "origin_id": ["AAPL:train", "AAPL:test"],
            "session_date": ["2025-01-02", "2025-01-03"],
            "forecast_origin_utc": [
                datetime(2025, 1, 2, 20, 0, tzinfo=UTC),
                datetime(2025, 1, 3, 14, 35, tzinfo=UTC),
            ],
        }
    )


def _fold() -> FoldDefinition:
    return FoldDefinition(
        fold=1,
        train_end=date(2025, 1, 2),
        test_start=date(2025, 1, 3),
        test_end=date(2025, 1, 3),
    )


def test_build_causal_audit_records_strict_gap_for_every_role() -> None:
    audit = build_causal_audit(
        _valid_panel(),
        (_fold(),),
        model_roles=("gamma_glm_confirmatory", "ridge_fixed_extension"),
        target_horizon_minutes=30,
        embargo_minutes=30,
        block="fixture",
    )

    assert audit.height == 2
    assert audit["causal_pass"].to_list() == [True, True]
    assert audit["observed_gap_minutes"].min() >= 60.0
    assert_causal_audit(audit)


def test_assert_causal_audit_rejects_training_after_test_start() -> None:
    audit = pl.DataFrame(
        {
            "block": ["fixture"],
            "fold": [1],
            "model_role": ["ridge_fixed_extension"],
            "observed_gap_minutes": [29.0],
            "required_protected_minutes": [60],
            "causal_pass": [False],
        }
    )

    with pytest.raises(ValueError, match="CANONICAL_CAUSALITY_VIOLATION"):
        assert_causal_audit(audit)


def test_identical_origins_rejects_one_missing_b2_row() -> None:
    with pytest.raises(ValueError, match="CANONICAL_ORIGIN_SET_MISMATCH"):
        assert_identical_origin_sets(
            {
                "B0v2": _frame(("a", "b")),
                "B1v2a": _frame(("a", "b")),
                "B2v2": _frame(("a",)),
            }
        )


def test_identical_origins_rejects_duplicate_key() -> None:
    with pytest.raises(ValueError, match="CANONICAL_ORIGIN_KEY_INVALID"):
        assert_identical_origin_sets(
            {
                "B0v2": _frame(("a", "a")),
                "B1v2a": _frame(("a", "a")),
                "B2v2": _frame(("a", "a")),
            }
        )
