"""Render the README's findings table from a scorecard, rather than typing it.

The README states, as a headline, a B2-over-B1 improvement that the corrected pipeline
reverses. Rewriting such a section by hand is how a number outlives the run that refuted it,
so the table is generated from `scorecard.json` and the generated text is what gets pasted.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: The families the research contract decides on, in the order the ladder reports them.
FAMILIES = ("gamma_glm", "ridge_log", "lightgbm_qlike")


def _delta(scorecard: dict[str, Any], field: str, family: str, role: str) -> float | None:
    value = scorecard.get("forecast", {}).get(family, {}).get(role, {}).get(field)
    return float(value) if isinstance(value, (int, float)) else None


def render(scorecard: dict[str, Any]) -> str:
    """A findings table nobody types: every number is read off the scorecard."""

    data = scorecard.get("data", {})
    sessions = data.get("sessions_by_role", {})
    header = "| Family | dB1 (D) | dB2 given B1 (D) | dB1 (V) | dB2 given B1 (V) |"
    lines = [
        f"## Findings at a glance (RP2-v3, run `{scorecard.get('run_id')}`)",
        "",
        "Measured on the rebuilt pipeline. A positive delta is an improvement in QLIKE: the",
        "smaller information set's loss minus the larger one's.",
        "",
        f"Development sessions: {sessions.get('D')}. Validation sessions: {sessions.get('V')}.",
        "",
        header,
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for family in FAMILIES:
        cells = [
            _delta(scorecard, "delta_b1", family, "D"),
            _delta(scorecard, "delta_b2_given_b1", family, "D"),
            _delta(scorecard, "delta_b1", family, "V"),
            _delta(scorecard, "delta_b2_given_b1", family, "V"),
        ]
        rendered = " | ".join("n/a" if c is None else f"{c:+.5f}" for c in cells)
        lines.append(f"| `{family}` | {rendered} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scorecard", type=Path, required=True)
    args = parser.parse_args(argv)
    print(render(json.loads(args.scorecard.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
