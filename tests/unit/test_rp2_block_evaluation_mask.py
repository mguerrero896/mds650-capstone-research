"""The recorded evaluation mask must be the rows a run actually scored.

Hashing the pre-split mask makes two runs that evaluate different sessions emit the same
`evaluation_mask_sha256`, which is exactly the claim the hash exists to support. The
pre-split mask stays right for an early exit, where nothing was evaluated at all.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import polars as pl
import pytest

from mds650.rp2.panel import B0_FEATURES, B1_FEATURES, B2_FEATURES, lift_mask, mask_sha256

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_lift_mask_maps_a_selection_back_onto_the_original_rows() -> None:
    base = np.array([True, False, True, True, False])
    selected = np.array([True, False, True])
    assert lift_mask(base, selected).tolist() == [True, False, False, True, False]
    assert lift_mask(base, np.ones(3, dtype=bool)).tolist() == base.tolist()
    assert not lift_mask(base, np.zeros(3, dtype=bool)).any()
    with pytest.raises(ValueError, match="RP2_PANEL_MASK_LIFT_SHAPE"):
        lift_mask(base, np.ones(4, dtype=bool))


def _synthetic_panel(sessions: int = 40, origins: int = 40) -> pl.DataFrame:
    rng = np.random.default_rng(650)
    assets = ("AAA", "BBB")
    rows = sessions * origins * len(assets)
    frame = pl.DataFrame(
        {
            "asset": [a for _ in range(sessions * origins) for a in assets],
            "session_date": [
                f"2026-01-{1 + index // origins:02d}"
                for index in range(sessions * origins)
                for _ in assets
            ],
            "origin_minute": [
                30 + index % origins for index in range(sessions * origins) for _ in assets
            ],
            "role": ["D"] * rows,
            "rv30": rng.lognormal(-11.0, 0.4, rows),
        }
    )
    registered = {**B0_FEATURES, **B1_FEATURES, **B2_FEATURES}
    return frame.with_columns(
        **{name: pl.Series(rng.lognormal(0.0, 0.3, rows)) for name in registered}
    )


def test_two_train_shares_evaluate_different_rows_and_say_so() -> None:
    """Same panel, same mask before the split, different sessions scored."""

    ladder = _load("rp2_block8_ladder")
    panel = _synthetic_panel()
    left = ladder.run_role(panel, role="D", train_share=0.5, models=("log_ols",))
    right = ladder.run_role(panel, role="D", train_share=0.8, models=("log_ols",))
    assert left["status"] == right["status"] == "MEASURED"
    assert left["test_rows"] != right["test_rows"]

    left_hash = left["information_sets"]["B0"]["evaluation_mask_sha256"]
    right_hash = right["information_sets"]["B0"]["evaluation_mask_sha256"]
    assert left_hash != right_hash, (
        "two runs that scored different sessions recorded the same evaluation mask"
    )
    # Within one run, every nested set shares the mask: that is what the contrast requires.
    hashes = {
        record["evaluation_mask_sha256"]
        for record in left["information_sets"].values()  # type: ignore[union-attr]
    }
    assert len(hashes) == 1


def test_an_early_exit_records_the_pre_split_mask() -> None:
    """Nothing was evaluated, so the usable rows are the honest thing to hash."""

    ladder = _load("rp2_block8_ladder")
    panel = _synthetic_panel(sessions=4, origins=4)
    result = ladder.run_role(panel, role="D", train_share=0.6, models=("log_ols",))
    assert result["status"] == "INSUFFICIENT_ROWS"
    record = result["information_sets"]["B0"]  # type: ignore[index]
    assert record["evaluation_mask_sha256"] == mask_sha256(np.ones(panel.height, dtype=bool))


def test_each_alternative_target_records_the_rows_it_was_actually_fitted_on() -> None:
    """Two targets with different availability are two different evaluation samples."""

    ext1 = _load("rp2_ext1_mechanism_utility")
    rng = np.random.default_rng(7)
    rows, sessions_count = 4000, 40
    base = np.ones(rows, dtype=bool)
    sessions = np.repeat(np.arange(sessions_count, dtype=np.int64), rows // sessions_count)
    nuisance = np.column_stack([np.ones(rows), rng.normal(size=(rows, 3))])
    treatment = rng.normal(size=(rows, 2))

    dense = rng.normal(size=rows)
    sparse = dense.copy()
    sparse[:1000] = np.nan

    left = ext1._dml_on_target(
        nuisance, treatment, dense, sessions, ("a", "b"), folds=3, evaluation_base=base
    )
    right = ext1._dml_on_target(
        nuisance, treatment, sparse, sessions, ("a", "b"), folds=3, evaluation_base=base
    )
    assert left is not None and right is not None
    assert left["evaluation_mask_sha256"] != right["evaluation_mask_sha256"], (
        "targets fitted on different rows recorded the same evaluation mask"
    )
    assert left["evaluation_mask_sha256"] == mask_sha256(base)


def test_the_tensor_and_sequence_arms_each_declare_their_own_information_set() -> None:
    """A published arm whose inputs no record describes is an unauditable result."""

    source = (REPO / "scripts" / "rp2_ext12_level4_and_tensor.py").read_text(encoding="utf-8")
    for arm in ("B0+B1+B2+tensor", "B0+B1+B2+sequence"):
        assert arm in source, f"extension arm {arm} publishes results with no information set"


def test_a_stopped_forward_economics_run_keeps_its_usable_mask() -> None:
    """Nothing was traded, so the scored mask does not exist yet and must not be invented.

    The convention is one way round: a run that reached its results hashes the rows it
    scored, and a run that stopped hashes the rows it could have used.
    """

    source = (REPO / "scripts" / "rp2_block11b_forward_economics.py").read_text(
        encoding="utf-8"
    )
    split = source.index("chronological_split(sessions_rank")
    sparse_exit = source.index('"INSUFFICIENT_LEGS"')
    scored = source.index("scored[rows] = True")
    between = source[split:sparse_exit]
    assert "describe_information_set(" not in between, (
        "the pre-split provenance is overwritten before the sparse-leg exits can use it"
    )
    assert scored > sparse_exit, "the scored mask is only known after the tradeable filter"
