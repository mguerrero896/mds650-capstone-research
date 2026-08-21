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


def test_the_histogram_reader_covers_every_bin_the_producer_wrote(tmp_path: Path) -> None:
    """A reader that stops early drops the tail and reports a shorter one than exists.

    `duration_histogram` sized its loop from `DURATION_BIN_EDGES`, which is the latency
    scale. Quote age uses `QUOTE_AGE_BIN_EDGES`, which is uniform over the 1800-second
    cutoff and has thirteen more bins. Block 5 wrote all 74 and the scorecard summed the
    first 61, so 16,497,996 of 144,587,810 quotes went uncounted -- every one of them in
    the oldest bins -- and the published 95th percentile read 1350 s where the whole
    histogram gives 1725 s. Truncating a histogram from the top always makes a tail look
    shorter, which is the direction that flatters the measurement.
    """
    from mds650.rp2.scorecard import QUOTE_AGE_BIN_EDGES, duration_histogram

    # Mass in the last bin the quote-age scale has, which the latency-sized loop misses.
    written = len(QUOTE_AGE_BIN_EDGES) + 1
    frame = pl.DataFrame(
        {f"age_bin_{index}": [1 if index in (0, written - 1) else 0] for index in range(written)}
    )
    path = _panel(tmp_path, frame)

    counts = duration_histogram(path, "age_bin_", QUOTE_AGE_BIN_EDGES)

    assert len(counts) == written, (
        f"the reader returned {len(counts)} bins for a producer that wrote {written}"
    )
    assert int(counts.sum()) == 2, (
        f"the reader counted {int(counts.sum())} of the 2 observations written; the one in "
        "the last bin was dropped"
    )
    assert counts[written - 1] == 1


def test_a_producer_that_wrote_more_bins_than_the_reader_expects_is_refused(
    tmp_path: Path,
) -> None:
    """Silently ignoring extra columns is how the tail went missing. Fail instead."""
    from mds650.rp2.scorecard import DURATION_BIN_EDGES, duration_histogram

    written = len(DURATION_BIN_EDGES) + 1
    frame = pl.DataFrame({f"lag_bin_{index}": [1] for index in range(written + 5)})
    path = _panel(tmp_path, frame)

    with pytest.raises(ValueError, match="RP2_SCORECARD_HISTOGRAM_BINS_UNREAD"):
        duration_histogram(path, "lag_bin_", DURATION_BIN_EDGES)
