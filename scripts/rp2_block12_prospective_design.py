"""Block 12 - size the definitive prospective test from measured dispersion.

The minimum detectable effect is derived from the **observed** session-level dispersion of
each contrast in the validation universe, not from an assumed variance.  Sessions are the
independent unit because five-minute origins share overlapping thirty-minute targets.

Reads no sealed cohort: the design is sized on D and V only.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl
from scipy import stats

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
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block12_prospective"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"

INFORMATION_SETS: dict[str, list[dict[str, str]]] = {
    "B0": [B0_FEATURES],
    "B0+B1": [B0_FEATURES, B1_FEATURES],
    "B0+B1+B2": [B0_FEATURES, B1_FEATURES, B2_FEATURES],
}
CONTRASTS: dict[str, tuple[str, str]] = {
    "delta_b1": ("B0", "B0+B1"),
    "delta_b2_given_b1": ("B0+B1", "B0+B1+B2"),
}
#: The two genuinely independent families the protocol admits.
FAMILIES: tuple[str, ...] = ("gamma_glm", "lightgbm")
SESSION_COUNTS: tuple[int, ...] = (60, 90, 120, 180)
POWER: float = 0.80

type FloatArray = npt.NDArray[np.float64]


def minimum_detectable_effect(
    session_sigma: float, *, sessions: int, alpha: float, power: float = POWER
) -> float:
    """One-sided MDE for a session-clustered mean at the given alpha and power."""

    if session_sigma <= 0.0 or sessions < 2:
        raise ValueError("RP2_MDE_INPUT_INVALID")
    critical = float(stats.norm.ppf(1.0 - alpha))
    detect = float(stats.norm.ppf(power))
    return (critical + detect) * session_sigma / math.sqrt(sessions)


def required_sessions(
    session_sigma: float, target_effect: float, *, alpha: float, power: float = POWER
) -> float:
    """Sessions needed to detect ``target_effect`` - the inverse of the MDE formula.

    Returns NaN for a non-positive target: an effect that is zero or adverse cannot be
    detected at any sample size.  NaN rather than infinity because the artifact must stay
    JSON-compliant, and the caller maps it to an explicit null.
    """

    if session_sigma <= 0.0:
        raise ValueError("RP2_MDE_INPUT_INVALID")
    if target_effect <= 0.0:
        return math.nan
    critical = float(stats.norm.ppf(1.0 - alpha))
    detect = float(stats.norm.ppf(power))
    return ((critical + detect) * session_sigma / target_effect) ** 2


def measure_dispersion(panel: pl.DataFrame, *, role: str, train_share: float
                       ) -> tuple[dict[str, dict[str, float]], dict[str, object]]:
    """Session-level standard deviation of each contrast, per family."""

    frame = panel.filter(pl.col("role") == role).sort(
        ["session_date", "asset", "origin_minute"]
    )
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    designs: dict[str, FloatArray] = {}
    resolved: dict[str, tuple[str, ...]] = {}
    for name, maps in INFORMATION_SETS.items():
        designs[name], resolved[name] = build_design(frame, maps)
    keep = common_usable_rows(designs, target)
    information_sets: dict[str, object] = {
        name: describe_information_set((name,), resolved[name], keep)
        for name in INFORMATION_SETS
    }
    frame = frame.filter(pl.Series(keep))
    target = target[keep]
    designs = {name: design[keep] for name, design in designs.items()}
    ranks = session_rank(frame["session_date"].to_numpy())
    train, test = chronological_split(ranks, train_share=train_share)
    session_labels = ranks[test]

    out: dict[str, dict[str, float]] = {}
    for family in FAMILIES:
        fitter = LADDER[family]
        losses = {
            name: qlike_losses(
                target[test],
                fitter(standardise(designs[name], train), target, train)[test],
            )
            for name in INFORMATION_SETS
        }
        block: dict[str, float] = {}
        for label, (base, expanded) in CONTRASTS.items():
            difference = losses[base] - losses[expanded]
            per_session = np.array(
                [
                    float(np.mean(difference[session_labels == session]))
                    for session in np.unique(session_labels)
                ]
            )
            block[f"{label}_session_sigma"] = float(np.std(per_session, ddof=1))
            block[f"{label}_observed_mean"] = float(np.mean(per_session))
        block["evaluation_sessions"] = float(np.unique(session_labels).size)
        out[family] = block
    return out, dict(information_sets)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-share", type=float, default=0.6)
    parser.add_argument("--alpha", type=float, default=0.05 / (4 * 5))
    args = parser.parse_args(argv)

    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL)
    measured = {
        role: measure_dispersion(panel, role=role, train_share=args.train_share)
        for role in ("D", "V")
    }
    dispersion = {role: block for role, (block, _) in measured.items()}
    information_sets = {role: record for role, (_, record) in measured.items()}

    power_table: dict[str, dict[str, dict[str, float]]] = {}
    for role, families in dispersion.items():
        power_table[role] = {}
        for family, stats_block in families.items():
            entry: dict[str, float] = {}
            for label in CONTRASTS:
                sigma = stats_block[f"{label}_session_sigma"]
                for sessions in SESSION_COUNTS:
                    entry[f"{label}_mde_n{sessions}"] = minimum_detectable_effect(
                        sigma, sessions=sessions, alpha=args.alpha
                    )
            for label in CONTRASTS:
                needed = required_sessions(
                    stats_block[f"{label}_session_sigma"],
                    stats_block[f"{label}_observed_mean"],
                    alpha=args.alpha,
                )
                entry[f"{label}_sessions_for_observed_effect"] = (
                    needed if math.isfinite(needed) else None  # type: ignore[assignment]
                )
            power_table[role][family] = entry

    document: dict[str, object] = {
        "block": 12,
        "program": "docs/research_program_v2.md",
        "label": "PROSPECTIVE_DESIGN",
        "alpha_one_sided": args.alpha,
        "alpha_note": "decision-64 spending at look 4 = 0.05/(4*5)",
        "power": POWER,
        "families": list(FAMILIES),
        "session_counts": list(SESSION_COUNTS),
        "measured_dispersion": dispersion,
        "information_sets": information_sets,
        "minimum_detectable_effects": power_table,
        "note": (
            "sessions_for_observed_effect is null when the observed effect is zero or "
            "adverse: no sample size detects a non-positive effect."
        ),
        "sealed_cohorts_read": 0,
    }
    document["design_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "design.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"alpha (one-sided) {args.alpha:.5f}   power {POWER}")
    for role, families in dispersion.items():
        for family, stats_block in families.items():
            for label in CONTRASTS:
                sigma = stats_block[f"{label}_session_sigma"]
                observed = stats_block[f"{label}_observed_mean"]
                mdes = " ".join(
                    f"n{n}={power_table[role][family][f'{label}_mde_n{n}']:.5f}"
                    for n in SESSION_COUNTS
                )
                required = power_table[role][family][f"{label}_sessions_for_observed_effect"]
                needed_text = "unreachable" if required is None else f"{required:.0f}"
                print(
                    f"  {role} {family:<10} {label:<18} sigma={sigma:.5f} "
                    f"observed={observed:+.5f}  {mdes}  n_required={needed_text}"
                )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
