"""Block 9 - generalization validation: does the contrast survive slicing the sample?

An aggregate walk-forward is not enough.  This runs the leave-one-out and regime analyses
the program requires and applies its minimum criterion, which is deliberately not "every
subgroup positive" but "no systematic inversion, no single slice carrying the result".

Refitting happens only for leave-one-asset-out, which genuinely asks whether the mechanism
transfers across the cross-section.  The month, era and regime analyses are evaluation-side
jackknives on the same frozen forecasts, which is what "does one month explain the result"
actually means.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.metrics import qlike_losses
from mds650.rp2.ladder import LADDER
from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    build_design,
    chronological_split,
    common_usable_rows,
    describe_information_set,
    load_merged_panel,
    session_rank,
    standardise,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block9_generalization"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"

INFORMATION_SETS: dict[str, list[dict[str, str]]] = {
    "B0": [B0_FEATURES],
    "B0+B1": [B0_FEATURES, B1_FEATURES],
    "B0+B2": [B0_FEATURES, B2_FEATURES],
    "B0+B1+B2": [B0_FEATURES, B1_FEATURES, B2_FEATURES],
}
CONTRASTS: dict[str, tuple[str, str]] = {
    "delta_b1": ("B0", "B0+B1"),
    "delta_b2_given_b1": ("B0+B1", "B0+B1+B2"),
    "delta_b2_given_b0": ("B0", "B0+B2"),
    "delta_total": ("B0", "B0+B1+B2"),
}
DEFAULT_MODELS: tuple[str, ...] = ("log_ols", "gamma_glm", "lightgbm")
NON_OVERLAPPING_STEP = 30

type FloatArray = npt.NDArray[np.float64]


def _third_friday(year: int, month: int) -> date:
    """The monthly option expiration date."""

    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def _is_expiration_week(session: str) -> bool:
    """True inside the week of the monthly (third-Friday) expiration."""

    day = date.fromisoformat(session)
    return abs((day - _third_friday(day.year, day.month)).days) <= 4


def _subgroups(frame: pl.DataFrame, test: npt.NDArray[np.bool_]) -> dict[str, np.ndarray]:
    """Label every test row with the slices the program asks to check."""

    sessions = frame["session_date"].to_numpy()[test]
    assets = frame["asset"].to_numpy()[test]
    minutes = frame["origin_minute"].to_numpy()[test].astype(np.int64)
    volatility = np.asarray(frame["rv_back_30"].to_numpy()[test], dtype=np.float64)
    liquidity = np.asarray(frame["dollar_volume_30"].to_numpy()[test], dtype=np.float64)
    market = np.asarray(frame["ret_30"].to_numpy()[test], dtype=np.float64)
    source = frame["source"].to_numpy()[test]

    def tercile(values: FloatArray, low: str, mid: str, high: str) -> np.ndarray:
        cuts = np.nanquantile(values, [1 / 3, 2 / 3])
        return np.where(values <= cuts[0], low, np.where(values <= cuts[1], mid, high))

    return {
        "asset": assets,
        "month": np.array([str(s)[:7] for s in sessions]),
        "era": source,
        "volatility_regime": tercile(volatility, "vol_low", "vol_mid", "vol_high"),
        "liquidity_regime": tercile(liquidity, "liq_low", "liq_mid", "liq_high"),
        "session_period": np.where(
            minutes < 120, "open", np.where(minutes < 240, "midday", "close")
        ),
        "market_direction": np.where(market >= 0.0, "market_up", "market_down"),
        "expiration_week": np.array(
            ["expiry_week" if _is_expiration_week(str(s)) else "ordinary_week" for s in sessions]
        ),
    }


def _delta(losses: dict[str, FloatArray], base: str, expanded: str) -> FloatArray:
    return losses[base] - losses[expanded]


def _summarise(values: FloatArray, labels: np.ndarray) -> dict[str, object]:
    """Per-slice mean plus the program's minimum-criterion diagnostics.

    Dominance is measured on **absolute** contributions and by a leave-one-group-out
    jackknife.  A share-of-signed-total metric is meaningless here: the totals are close to
    zero, so dividing by them produces arbitrarily large numbers rather than information.
    """

    groups = sorted({str(label) for label in labels})
    if not groups:
        return {"overall": float("nan"), "groups": 0}
    masks = {group: labels == group for group in groups}
    per_group = {group: float(np.mean(values[mask])) for group, mask in masks.items()}
    total = float(np.mean(values))
    positives = sum(1 for value in per_group.values() if value > 0.0)
    sums = {group: float(np.sum(values[mask])) for group, mask in masks.items()}
    absolute = sum(abs(value) for value in sums.values())
    dominance = (
        max(abs(value) for value in sums.values()) / absolute if absolute > 0.0 else None
    )
    # A single-group slice has nothing to leave out; emit null rather than NaN so the
    # artifact stays JSON-compliant and hashable.
    jackknife: dict[str, float | None] = {
        group: float(np.mean(values[~mask])) if (~mask).any() else None
        for group, mask in masks.items()
    }
    flips = sum(
        1 for value in jackknife.values()
        if value is not None and np.sign(value) != np.sign(total) and total != 0.0
    )
    return {
        "overall": total,
        "per_group": per_group,
        "groups": len(groups),
        "positive_groups": positives,
        "sign_stability": positives / len(groups),
        "max_absolute_contribution_share": dominance,
        "leave_one_group_out": jackknife,
        "groups_whose_removal_flips_the_sign": flips,
        "systematic_inversion": bool(total > 0.0 and positives < len(groups) / 2),
    }


def run_role(
    panel: pl.DataFrame, *, role: str, train_share: float, models: Sequence[str]
) -> dict[str, object]:
    frame = panel.filter(pl.col("role") == role).sort(
        ["session_date", "asset", "origin_minute"]
    )
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    designs: dict[str, FloatArray] = {}
    resolved: dict[str, tuple[str, ...]] = {}
    for name, maps in INFORMATION_SETS.items():
        designs[name], resolved[name] = build_design(frame, maps)
    keep = common_usable_rows(designs, target)
    information_sets = {
        name: describe_information_set((name,), resolved[name], keep)
        for name in INFORMATION_SETS
    }
    if int(keep.sum()) < 2000:
        return {
            "status": "INSUFFICIENT_ROWS",
            "rows": int(keep.sum()),
            "information_sets": information_sets,
        }

    frame = frame.filter(pl.Series(keep))
    target = target[keep]
    designs = {name: design[keep] for name, design in designs.items()}
    sessions_rank = session_rank(frame["session_date"].to_numpy())
    train, test = chronological_split(sessions_rank, train_share=train_share)
    assets = frame["asset"].to_numpy()
    minutes = frame["origin_minute"].to_numpy().astype(np.int64)
    labels = _subgroups(frame, test)

    results: dict[str, object] = {
        "status": "MEASURED",
        "rows": int(keep.sum()),
        "train_rows": int(train.sum()),
        "test_rows": int(test.sum()),
        "information_sets": information_sets,
    }
    per_model: dict[str, object] = {}
    for model_name in models:
        fitter = LADDER[model_name]
        losses: dict[str, FloatArray] = {}
        for set_name in INFORMATION_SETS:
            forecast = fitter(standardise(designs[set_name], train), target, train)
            losses[set_name] = qlike_losses(target[test], forecast[test])

        contrast_blocks: dict[str, object] = {}
        for label, (base, expanded) in CONTRASTS.items():
            difference = _delta(losses, base, expanded)
            slices = {
                name: _summarise(difference, values) for name, values in labels.items()
            }
            # Non-overlapping origins: 30-minute spacing removes target overlap.
            spaced = (minutes[test] % NON_OVERLAPPING_STEP) == 0
            slices["non_overlapping_origins"] = {
                "overall": float(np.mean(difference[spaced])),
                "rows": int(spaced.sum()),
            }
            contrast_blocks[label] = slices
        # Leave-one-asset-out needs a genuine refit per held-out asset.
        loao: dict[str, dict[str, float]] = {}
        for asset in sorted({str(a) for a in assets}):
            held = assets == asset
            asset_train = train & ~held
            asset_test = test & held
            if asset_train.sum() < 1000 or asset_test.sum() < 200:
                continue
            asset_losses: dict[str, FloatArray] = {}
            for set_name in INFORMATION_SETS:
                forecast = fitter(
                    standardise(designs[set_name], asset_train), target, asset_train
                )
                asset_losses[set_name] = qlike_losses(target[asset_test], forecast[asset_test])
            loao[asset] = {
                label: float(np.mean(_delta(asset_losses, base, expanded)))
                for label, (base, expanded) in CONTRASTS.items()
            }
        contrast_blocks["leave_one_asset_out"] = loao
        per_model[model_name] = contrast_blocks
    results["models"] = per_model
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-share", type=float, default=0.6)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    args = parser.parse_args(argv)

    models = tuple(name.strip() for name in str(args.models).split(",") if name.strip())
    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL)
    document: dict[str, object] = {
        "block": 9,
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "models": list(models),
        "non_overlapping_step_minutes": NON_OVERLAPPING_STEP,
    }
    for role in ("D", "V"):
        document[role] = run_role(
            panel, role=role, train_share=args.train_share, models=models
        )
    document["generalization_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "generalization.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for role in ("D", "V"):
        block = document[role]
        assert isinstance(block, dict)
        print(f"=== role {role}: {block.get('status')} ===")
        per_model = block.get("models")
        if not isinstance(per_model, dict):
            continue
        for model_name, contrasts in per_model.items():
            assert isinstance(contrasts, dict)
            for label in CONTRASTS:
                slices = contrasts.get(label)
                if not isinstance(slices, dict):
                    continue
                asset_block = slices.get("asset")
                assert isinstance(asset_block, dict)
                dominance = asset_block["max_absolute_contribution_share"] or float("nan")
                print(
                    f"  {model_name:<12} {label:<20} overall={asset_block['overall']:+.5f} "
                    f"assets+={asset_block['positive_groups']}/{asset_block['groups']} "
                    f"dominance={dominance:.2f} "
                    f"flips={asset_block['groups_whose_removal_flips_the_sign']}"
                )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
