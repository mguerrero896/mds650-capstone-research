"""Quality-only asset freezing and common-history calculation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from mds650.errors import OverlapError, QualityGateError


@dataclass(frozen=True, slots=True)
class AssetQuality:
    """Audited coverage and data-quality measurements for one candidate asset."""

    asset: str
    completeness_ratio: float
    duplicate_rate: float
    critical_null_rate: float
    history_start: date
    history_end: date

    def __post_init__(self) -> None:
        """Reject impossible rates and inverted history ranges."""
        if not self.asset or not 0 <= self.completeness_ratio <= 1:
            raise ValueError("ASSET_QUALITY_MEASURE_INVALID")
        if not 0 <= self.duplicate_rate <= 1 or not 0 <= self.critical_null_rate <= 1:
            raise ValueError("ASSET_QUALITY_MEASURE_INVALID")
        if self.history_end < self.history_start:
            raise ValueError("ASSET_HISTORY_RANGE_INVALID")


@dataclass(frozen=True, slots=True)
class FrozenAssetSet:
    """Deterministic frozen assets and their maximum common history."""

    assets: tuple[str, ...]
    common_start: date
    common_end: date


def freeze_assets(
    candidates: Sequence[AssetQuality],
    *,
    minimum_assets: int = 4,
    maximum_assets: int = 6,
    minimum_completeness: float = 0.95,
    maximum_duplicate_rate: float = 0.0,
    maximum_critical_null_rate: float = 0.0,
) -> FrozenAssetSet:
    """Freeze 4--6 assets using coverage and quality gates only.

    Parameters
    ----------
    candidates:
        Audited candidate metrics. No model score or preliminary performance is
        accepted by this interface.
    minimum_assets, maximum_assets:
        Inclusive frozen-set cardinality bounds.
    minimum_completeness, maximum_duplicate_rate, maximum_critical_null_rate:
        Configurable quality thresholds.

    Returns
    -------
    FrozenAssetSet
        Alphabetically stable assets and their maximum common date interval.

    Raises
    ------
    QualityGateError
        If candidates duplicate, fail quality, or fewer than the minimum pass.
    OverlapError
        If passing assets have no common history interval.
    """
    if minimum_assets < 1 or maximum_assets < minimum_assets:
        raise ValueError("ASSET_FREEZE_CONFIGURATION_INVALID")
    names = [candidate.asset for candidate in candidates]
    if len(names) != len(set(names)):
        raise QualityGateError("ASSET_QUALITY_GATE_FAILED")
    passing = [
        candidate
        for candidate in candidates
        if candidate.completeness_ratio >= minimum_completeness
        and candidate.duplicate_rate <= maximum_duplicate_rate
        and candidate.critical_null_rate <= maximum_critical_null_rate
    ]
    if len(passing) < minimum_assets:
        raise QualityGateError("QUALITY_ASSET_COUNT_BELOW_MINIMUM")
    selected = sorted(
        passing,
        key=lambda item: (
            -item.completeness_ratio,
            item.duplicate_rate,
            item.critical_null_rate,
            -(item.history_end - item.history_start).days,
            item.asset,
        ),
    )[:maximum_assets]
    common_start = max(item.history_start for item in selected)
    common_end = min(item.history_end for item in selected)
    if common_start > common_end:
        raise OverlapError("COMMON_HISTORY_OVERLAP_INSUFFICIENT")
    return FrozenAssetSet(tuple(sorted(item.asset for item in selected)), common_start, common_end)
