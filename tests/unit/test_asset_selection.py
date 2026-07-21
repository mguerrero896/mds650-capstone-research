from __future__ import annotations

from datetime import date

import pytest

from mds650.asset_selection import AssetQuality, freeze_assets
from mds650.errors import QualityGateError


def _quality(asset: str, completeness: float = 1.0) -> AssetQuality:
    return AssetQuality(
        asset=asset,
        completeness_ratio=completeness,
        duplicate_rate=0.0,
        critical_null_rate=0.0,
        history_start=date(2020, 1, 2),
        history_end=date(2026, 7, 17),
    )


def test_freeze_assets_selects_four_to_six_by_quality_only() -> None:
    frozen = freeze_assets([_quality(asset) for asset in ("SPY", "QQQ", "AAPL", "MSFT", "NVDA")])

    assert len(frozen.assets) == 5
    assert frozen.assets == ("AAPL", "MSFT", "NVDA", "QQQ", "SPY")
    assert frozen.common_start == date(2020, 1, 2)
    assert frozen.common_end == date(2026, 7, 17)


def test_freeze_assets_fails_when_fewer_than_four_pass_quality_gate() -> None:
    with pytest.raises(QualityGateError, match="QUALITY_ASSET_COUNT_BELOW_MINIMUM"):
        freeze_assets([_quality(asset) for asset in ("SPY", "QQQ", "AAPL")])


def test_freeze_assets_rejects_duplicate_or_incomplete_candidates() -> None:
    with pytest.raises(QualityGateError, match="ASSET_QUALITY_GATE_FAILED"):
        freeze_assets(
            [_quality("SPY"), _quality("SPY")]
            + [_quality(a) for a in ("QQQ", "AAPL", "MSFT")]
        )
