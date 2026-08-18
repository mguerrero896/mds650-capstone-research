"""Extension 4 - power for BOTH contrasts, so the prospective bullet is aimed, not spent.

Block 12 sized only the variance contrast. The exploratory battery then found that the
one thing surviving Holm in validation is the **signed forward return** at 60-120 minutes,
which is a different estimand with a different noise scale - and therefore a different
power curve. Comparing the two is what decides where a one-read cohort is worth spending.

Variance power comes from the measured session-level dispersion of the QLIKE contrast.
Direction power comes from the measured cluster-robust t-statistic of the DML coefficient,
whose non-centrality scales as sqrt(n) in the number of sessions.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from scipy import stats

from mds650.b1v3_confirmation import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_ext4_power"
BLOCK12 = ROOT / "artifacts" / "rp2_block12_prospective" / "design.json"
EXT1 = ROOT / "artifacts" / "rp2_ext1_mechanism_utility" / "mechanism_utility.json"
SESSION_COUNTS: tuple[int, ...] = (30, 60, 90, 120, 180, 240, 537)
POWER_TARGET = 0.80


def power_from_effect(effect: float, sigma: float, sessions: int, alpha: float) -> float:
    """Power of a one-sided session-clustered mean test."""

    if sigma <= 0.0 or sessions < 2:
        return float("nan")
    critical = float(stats.norm.ppf(1.0 - alpha))
    non_centrality = effect / (sigma / math.sqrt(sessions))
    return float(1.0 - stats.norm.cdf(critical - non_centrality))


def power_from_t(observed_t: float, observed_clusters: int, sessions: int, alpha: float
                 ) -> float:
    """Power implied by an observed t-statistic, rescaled to a new cluster count.

    A t-statistic already is effect/standard-error, and the standard error shrinks as
    ``sqrt(n)``, so the non-centrality at ``sessions`` is ``t * sqrt(sessions/observed)``.
    """

    if observed_clusters < 2 or sessions < 2:
        return float("nan")
    critical = float(stats.norm.ppf(1.0 - alpha))
    non_centrality = abs(observed_t) * math.sqrt(sessions / observed_clusters)
    return float(1.0 - stats.norm.cdf(critical - non_centrality))


def sessions_for_power(non_centrality_at_one: float, alpha: float,
                       target: float = POWER_TARGET) -> float:
    """Sessions needed to reach ``target`` power, given the per-session non-centrality."""

    if non_centrality_at_one <= 0.0:
        return float("nan")
    critical = float(stats.norm.ppf(1.0 - alpha))
    detect = float(stats.norm.ppf(target))
    return ((critical + detect) / non_centrality_at_one) ** 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--alpha", type=float, default=0.05 / (4 * 5))
    args = parser.parse_args(argv)

    design = json.loads(BLOCK12.read_text(encoding="utf-8"))
    battery = json.loads(EXT1.read_text(encoding="utf-8"))

    rows: list[dict[str, object]] = []

    # --- variance contrast, from the measured QLIKE dispersion -----------------------
    for role in ("D", "V"):
        for family, block in design["measured_dispersion"][role].items():
            for label in ("delta_b1", "delta_b2_given_b1"):
                effect = float(block[f"{label}_observed_mean"])
                sigma = float(block[f"{label}_session_sigma"])
                rows.append(
                    {
                        "contrast": "variance",
                        "role": role,
                        "detail": f"{family} {label}",
                        "effect": effect,
                        "sigma": sigma,
                        "power": {
                            str(n): power_from_effect(effect, sigma, n, args.alpha)
                            for n in SESSION_COUNTS
                        },
                        "sessions_for_80pct": sessions_for_power(
                            effect / sigma if sigma > 0 else 0.0, args.alpha
                        )
                        if effect > 0.0
                        else None,
                    }
                )

    # --- direction contrast, from the measured DML t-statistics ----------------------
    for role in ("D", "V"):
        block = battery[role]["a_other_targets"]
        for target_name, stats_block in block.items():
            if not isinstance(stats_block, dict) or "signed_return" not in target_name:
                continue
            if float(stats_block.get("holm_p", 1.0)) >= 0.05:
                continue
            clusters = int(stats_block["clusters"])
            strongest = max(
                stats_block["coefficients"].items(), key=lambda kv: abs(kv[1]["t"])
            )
            observed_t = float(strongest[1]["t"])
            rows.append(
                {
                    "contrast": "direction",
                    "role": role,
                    "detail": f"{target_name} via {strongest[0]}",
                    "observed_t": observed_t,
                    "observed_clusters": clusters,
                    "power": {
                        str(n): power_from_t(observed_t, clusters, n, args.alpha)
                        for n in SESSION_COUNTS
                    },
                    "sessions_for_80pct": sessions_for_power(
                        abs(observed_t) / math.sqrt(clusters), args.alpha
                    ),
                }
            )

    document: dict[str, object] = {
        "extension": 4,
        "label": "PROSPECTIVE_DESIGN",
        "alpha_one_sided": args.alpha,
        "alpha_note": "decision-64 spending at look 4 = 0.05/(4*5)",
        "power_target": POWER_TARGET,
        "session_counts": list(SESSION_COUNTS),
        "caveat": (
            "Direction power is computed from a t-statistic found by searching a family of "
            "36 targets after the variance nulls were known. It is an upper bound on what a "
            "pre-registered test would achieve, not an unbiased estimate."
        ),
        "rows": rows,
    }
    document["power_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "power.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"alpha={args.alpha:.5f}  target power={POWER_TARGET}\n")
    header = f"{'contrast':<10} {'role':<5} {'detail':<44} " + " ".join(
        f"n={n:<5}" for n in SESSION_COUNTS
    )
    print(header)
    for row in sorted(rows, key=lambda r: (str(r["contrast"]), str(r["role"]))):
        power = row["power"]
        assert isinstance(power, dict)
        cells = " ".join(f"{power[str(n)]*100:5.1f}%" for n in SESSION_COUNTS)
        needed = row["sessions_for_80pct"]
        tail = f"  n80={needed:.0f}" if isinstance(needed, float) and math.isfinite(needed) else ""
        print(f"{row['contrast']:<10} {row['role']:<5} {str(row['detail']):<44} {cells}{tail}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
