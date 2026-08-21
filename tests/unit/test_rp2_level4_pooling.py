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


def _module():
    spec = importlib.util.spec_from_file_location("rp2_level4_normalisation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sequence_normalisation_ignores_the_evaluation_fold() -> None:
    """The scale of the trade channels must not be learned from rows being scored.

    The tabular block is standardised with `standardise(design, train)`, on the training
    fold only. The sequence block was normalised from every row, so the two halves of the
    same network disagreed about which rows they were allowed to see, and a comment
    asserting both used the training fold sat directly above.
    """
    import numpy as np

    module = _module()
    channels = 8
    train = np.array([True, True, False, False])
    block = np.zeros((4, 3, channels), dtype=np.float64)
    block[:2] = 1.0          # training rows: every channel is one
    block[2:] = 1_000.0      # evaluation rows: wildly different scale

    centre, spread = module.sequence_normalisation(block, train)

    assert np.allclose(centre, 1.0), (
        f"the centre is {centre[:3]}, so rows outside the training fold reached it"
    )
    assert np.all(np.isfinite(spread)) and np.all(spread > 0.0)


def test_sequence_normalisation_excludes_padded_positions() -> None:
    """Padding carries a zero size in channel 2 and is not a market observation."""
    import numpy as np

    module = _module()
    channels = 8
    train = np.array([True, True])
    block = np.zeros((2, 4, channels), dtype=np.float64)
    block[:, :2, :] = 5.0    # two real trades per row
    block[:, :2, 2] = 3.0    # non-zero size marks them observed
    # positions 2 and 3 stay all-zero: padding

    centre, _ = module.sequence_normalisation(block, train)

    assert np.isclose(centre[0], 5.0), (
        f"channel 0 centred at {centre[0]}, so padded positions entered the mean"
    )


def test_sequence_normalisation_refuses_an_empty_training_fold() -> None:
    import numpy as np

    module = _module()
    block = np.ones((2, 3, 8), dtype=np.float64)
    with pytest.raises(ValueError, match="RP2_LEVEL4_SEQUENCE_EMPTY_TRAIN"):
        module.sequence_normalisation(block, np.array([False, False]))


def test_the_torch_script_carries_no_type_suppression() -> None:
    """A suppression here fires by wheel rather than by content.

    torch is the one dependency in this repository whose type stubs differ between
    distributions: the CUDA build annotates `Tensor.backward` and `Sequential.__getitem__`
    differently from the CPU build. A `# type: ignore` that one requires, the other reports
    as unused, so the tree was clean locally and mypy failed in CI on both the `quality` and
    `hermetic` jobs. Either spelling is wrong on one of the two platforms, so the file
    carries none: the output layer is held by name and the backward call goes through `Any`.

    This is the only module that imports torch. If that stops being true, this test should
    grow to cover the others rather than be relaxed.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "type: ignore" not in source, (
        "a type suppression in the torch script fires by installed wheel, not by content"
    )

    importers = [
        path
        for path in sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py"))
        if "import torch" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert importers == [SCRIPT], (
        f"torch is now imported by {[str(p.relative_to(ROOT)) for p in importers]}; "
        "extend this check to cover them"
    )
