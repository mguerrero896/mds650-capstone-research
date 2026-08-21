"""A statistic computed per origin is not the same statistic computed over the run.

Two families of this mistake were already found and fixed here once each, and each time
the identical mistake was left standing a few lines away:

  - `b2_p95_provider_latency_s` was a median across windows of each window's own 95th
    percentile. It was replaced by a quantile read off summed histogram bins, while
    `b1_p95_quote_age_s` next to it kept doing exactly the same thing.
  - `b2_multileg_share` averages per-origin premium shares with an unweighted mean. The
    denominators differ by a factor of fourteen between the median origin and the 99th
    percentile, so an origin holding thirty million dollars of premium counted as much as
    one holding four hundred million.

These tests pin the pooled forms so the class cannot come back quietly.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from mds650.rp2.scorecard import weighted_share


def _panel(tmp_path: Path, frame: pl.DataFrame) -> Path:
    path = tmp_path / "panel.parquet"
    frame.write_parquet(path)
    return path


def test_weighted_share_is_the_pooled_ratio_not_the_average_ratio(tmp_path: Path) -> None:
    # One tiny origin that is entirely multileg, one large origin that is barely any.
    # The unweighted mean says 50 %; the pooled share says 1.1 %, and the pooled share is
    # the fraction of premium that was actually multileg.
    frame = pl.DataFrame({"share": [1.0, 0.01], "premium": [1_000.0, 99_000.0]})
    path = _panel(tmp_path, frame)

    pooled = weighted_share(path, "share", "premium")

    naive = float(np.mean(frame["share"].to_numpy()))
    assert naive == pytest.approx(0.505)
    assert pooled == pytest.approx((1.0 * 1_000.0 + 0.01 * 99_000.0) / 100_000.0)
    assert pooled == pytest.approx(0.0199)
    assert pooled != pytest.approx(naive)


def test_weighted_share_ignores_origins_with_no_weight(tmp_path: Path) -> None:
    """An origin that saw no premium has no share to contribute, not a share of zero."""
    frame = pl.DataFrame({"share": [0.5, 0.0, 0.5], "premium": [100.0, 0.0, 100.0]})
    path = _panel(tmp_path, frame)

    assert weighted_share(path, "share", "premium") == pytest.approx(0.5)


def test_weighted_share_ignores_nulls_in_either_column(tmp_path: Path) -> None:
    frame = pl.DataFrame({"share": [0.5, None, 0.5], "premium": [100.0, 100.0, None]})
    path = _panel(tmp_path, frame)

    assert weighted_share(path, "share", "premium") == pytest.approx(0.5)


def test_weighted_share_reports_absence_rather_than_zero(tmp_path: Path) -> None:
    """No weight anywhere means the share is unmeasured; zero would be a claim."""
    frame = pl.DataFrame({"share": [0.5, 0.5], "premium": [0.0, 0.0]})
    path = _panel(tmp_path, frame)

    assert weighted_share(path, "share", "premium") is None
    assert weighted_share(path, "share", "absent_column") is None
    assert weighted_share(tmp_path / "missing.parquet", "share", "premium") is None
