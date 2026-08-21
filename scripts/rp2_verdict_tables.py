"""Emit the verdict's tables and counts from a run, so nobody transcribes them.

`docs/rp2_v3/VERDICT.md` states twelve contrasts, three counts and a family-by-family
power table. Every one of those figures was typed in by hand against an artifact, and the
same practice on `README.md` left two RP2-v2 measurements standing under an RP2-v3 heading
for a full rebuild — one of them overstating a joint test by thirty-seven orders of
magnitude.

This prints exactly the markdown those sections need, read from the run's own inference
artifact. The prose around them is still written by a person; the numbers are not.
`tests/contract/test_verdict_matches_artifact.py` then checks the document that results,
so a table pasted from the wrong run fails rather than publishes.

Usage:

    uv run python scripts/rp2_verdict_tables.py --run-id rp2-v3-YYYYMMDD-HHMMSS
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRASTS = (("B1", "b1_over_b0"), ("B2|B1", "b2_over_b1"))
FAMILIES = ("gamma_glm", "ridge_log", "lightgbm_qlike")
#: The document writes a minus as U+2212 so the columns align in a proportional font.
MINUS = "−"


def _signed(value: float) -> str:
    return f"{'+' if value >= 0 else MINUS}{abs(value):.5f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "rp2_v3")
    arguments = parser.parse_args(argv)

    path = (
        arguments.output_root
        / arguments.run_id
        / "rp2_block10_inference"
        / "inference.json"
    )
    if not path.is_file():
        raise SystemExit(f"RP2_VERDICT_TABLES_RUN_MISSING:{path}")
    inference = json.loads(path.read_text(encoding="utf-8"))

    rows = [
        (family, role, label, inference[role]["nested_tests"][family][key])
        for family in FAMILIES
        for role in ("D", "V")
        for label, key in CONTRASTS
    ]
    # The document orders by family, then role, then contrast, which is the order a reader
    # compares them in: each family's development row above its validation row.
    print("| Family | Role | Contrast | Δ | 95% CI | Contains 0 |")
    print("| --- | --- | --- | ---: | ---: | :---: |")
    for family, role, label, record in rows:
        contains = record["ci_low"] <= 0 <= record["ci_high"]
        marker = "yes" if contains else ("**no**" if role == "V" else "no")
        escaped = label.replace("|", "\\|")
        print(
            f"| `{family}` | {role} | Δ{escaped} | {_signed(record['estimate'])} | "
            f"[{_signed(record['ci_low'])}, {_signed(record['ci_high'])}] | {marker} |"
        )

    measured = [record for *_, record in rows]
    zero = sum(1 for r in measured if r["ci_low"] <= 0 <= r["ci_high"])
    below = sum(1 for r in measured if abs(r["estimate"]) < r["mde"])
    positive = sum(1 for r in measured if r["estimate"] > 0)
    print()
    print(f"counts: positive {positive}/12, contains zero {zero}/12, below own MDE {below}/12")

    print()
    print("| Family | Effect in D | MDE in V | Could V have detected it? |")
    print("| --- | ---: | ---: | --- |")
    for family in FAMILIES:
        development = inference["D"]["nested_tests"][family]["b1_over_b0"]
        validation = inference["V"]["nested_tests"][family]["b1_over_b0"]
        effect = development["estimate"]
        mde, sessions = validation["mde"], validation["sessions"]
        needed = math.ceil(sessions * (mde / abs(effect)) ** 2) if effect else None
        if mde < abs(effect):
            note = f"**Yes** — and it measured {_signed(validation['estimate'])}"
        elif needed is not None and needed <= sessions * 1.25:
            note = f"Marginally not: ~{needed} sessions needed, {int(sessions)} available"
        else:
            note = f"No — roughly {needed} sessions would be needed"
        print(f"| `{family}` | {_signed(effect)} | {mde:.5f} | {note} |")

    print()
    print("power detail, for the prose:")
    for family in FAMILIES:
        development = inference["D"]["nested_tests"][family]["b1_over_b0"]
        validation = inference["V"]["nested_tests"][family]["b1_over_b0"]
        ratio = validation["mde"] / abs(development["estimate"])
        effect, in_validation = development["estimate"], validation["estimate"]
        print(
            f"  {family:<16} effect D {effect:+.5f}  V {in_validation:+.5f}"
            f"  MDE V {validation['mde']:.5f}  ratio {ratio:.2f}  "
            f"V interval [{validation['ci_low']:+.5f}, {validation['ci_high']:+.5f}]"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - a thin console entry point
    raise SystemExit(main())
