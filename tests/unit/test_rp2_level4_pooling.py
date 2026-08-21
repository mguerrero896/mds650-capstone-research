"""A session with no observable trades must not poison the trade-set encoder.

The masked max-pool fills padded positions with a large negative sentinel so they
lose the maximum. When a session has zero observable trades every position is
padding, the maximum is the sentinel itself, and it reaches the head as a feature
of magnitude 1e9. Measured on the RP2-v3 development panel this happened on 448
of 2,975,222 forward passes and drove the first training epoch to MSE 1.7e14
against the control's 43.5, so the arm spent a quarter of its budget recovering
and generalised twice as badly on the rows that stayed corrupt.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "rp2_ext12_level4_and_tensor.py"


def _forecaster(*, use_sequence: bool):
    spec = importlib.util.spec_from_file_location("rp2_level4_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.DeepSetsForecaster(4, 3, use_sequence=use_sequence)


def test_empty_trade_set_pools_to_a_bounded_value() -> None:
    model = _forecaster(use_sequence=True)
    tabular = torch.zeros(2, 4)
    sequence = torch.zeros(2, 6, 3)
    mask = torch.zeros(2, 6)
    mask[0] = 1.0  # first session observes trades, second observes none

    output = model(tabular, sequence, mask)

    assert torch.isfinite(output).all(), "an empty trade set produced a non-finite forecast"
    assert output.abs().max() < 1e3, (
        f"an empty trade set produced |forecast| = {output.abs().max():.3e}; the sentinel "
        "used to drop padded positions is reaching the head as a feature"
    )


def test_empty_trade_set_matches_a_zero_encoding() -> None:
    """Zero observable trades must contribute nothing, exactly as the mean pool does."""
    model = _forecaster(use_sequence=True)
    tabular = torch.randn(1, 4)
    sequence = torch.zeros(1, 6, 3)

    empty = model(tabular, sequence, torch.zeros(1, 6))
    # The mean pool divides by a count clamped to one, so an empty set yields zeros.
    # The max pool must agree rather than emit its padding sentinel.
    hidden = model.head[0].in_features - tabular.shape[1]
    expected = model.head(torch.cat([tabular, torch.zeros(1, hidden)], dim=1)).squeeze(-1)

    assert torch.allclose(empty, expected, atol=1e-5), (
        f"an empty trade set forecast {empty.item():.6g} where a zero encoding gives "
        f"{expected.item():.6g}"
    )
