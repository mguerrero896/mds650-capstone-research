"""Target-blind base-panel contracts for the independent replication."""

from __future__ import annotations

from datetime import date

import pytest

from mds650.b1_replication_build import (
    CANONICAL_ASSETS,
    build_replication_origin_grid,
)


def test_replication_origin_grid_is_early_close_aware_and_target_free() -> None:
    frame = build_replication_origin_grid((date(2024, 12, 23), date(2024, 12, 24)))

    counts = {
        str(row["session_date"]): int(row["len"])
        for row in frame.group_by("session_date").len().iter_rows(named=True)
    }
    assert counts == {"2024-12-23": 72 * 6, "2024-12-24": 36 * 6}
    assert tuple(sorted(frame["asset"].unique().to_list())) == CANONICAL_ASSETS
    assert frame["origin_id"].n_unique() == frame.height
    assert frame["role"].unique().to_list() == ["independent_replication"]
    assert not any(
        token in column.lower()
        for column in frame.columns
        for token in ("rv30", "qlike", "prediction", "outcome")
    )


def test_replication_origin_grid_rejects_non_session_or_unsorted_dates() -> None:
    with pytest.raises(ValueError, match="REPLICATION_ORIGIN_ALLOWLIST_INVALID"):
        build_replication_origin_grid((date(2024, 12, 24), date(2024, 12, 23)))
    with pytest.raises(ValueError, match="REPLICATION_ORIGIN_NOT_XNYS_SESSION"):
        build_replication_origin_grid((date(2024, 12, 25),))
