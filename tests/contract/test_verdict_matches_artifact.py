"""The published verdict must agree with the run it says it was measured on.

`docs/rp2_v3/VERDICT.md` states a run id in its own header and then reports twelve
contrasts, three counts and a family-by-family power table. Nothing recomputes those
figures when the run changes, so a rebuild that moves a number leaves the document
asserting the old one. This reads the run id out of the document, opens that run's
inference artifact, and checks every figure against it.

Both tables are parsed by splitting cells, and the parse is asserted to yield the
expected shape before any comparison runs. A parser that silently drops rows passes
vacuously: while writing this, one regex matched only the six `ΔB1` rows and the counts
computed from them disagreed with the document, which read as a defect in the document
and was a defect in the parser.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "rp2_v3" / "VERDICT.md"

#: `ΔB2\|B1` escapes the pipe so the cell survives the markdown table; mask it before
#: splitting on the column separator.
ESCAPED_PIPE = chr(92) + "|"
MASK = "\x00"

CONTRAST_KEY = {"B1": "b1_over_b0", "B2|B1": "b2_over_b1"}
#: Stated in the prose beneath the two tables. Changing a number without changing these
#: is the failure this guards against.
CLAIMED_INTERVALS_CONTAINING_ZERO = 8
CLAIMED_BELOW_OWN_MDE = 10
CLAIMED_POSITIVE_DELTAS = 5
#: "~33 sessions needed, 32 available" and "roughly 692 sessions would be needed".
CLAIMED_SESSIONS_NEEDED = {"gamma_glm": 33, "lightgbm_qlike": 692}

TOLERANCE = 6e-6


def _number(text: str) -> float:
    """Parse a table cell, accepting the document's typographic minus sign."""
    return float(text.replace("−", "-").replace("+", "").strip())


def _cells(line: str) -> list[str]:
    masked = line.strip().strip("|").replace(ESCAPED_PIPE, MASK)
    return [cell.replace(MASK, "|").strip() for cell in masked.split("|")]


@pytest.fixture(scope="module")
def document() -> str:
    if not DOC.is_file():
        pytest.fail(f"the published verdict is missing: {DOC}")
    return DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def inference(document: str) -> dict:
    """The inference artifact of the run the document names in its own header."""
    match = re.search(r"Measured on `(rp2-v3-[\w-]+)`", document)
    assert match, "the verdict no longer states the run it was measured on"
    run_id = match.group(1)
    path = REPO / "artifacts" / "rp2_v3" / run_id / "rp2_block10_inference" / "inference.json"
    if not path.is_file():
        pytest.skip(f"run {run_id} is not present in this checkout: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tables(document: str) -> tuple[list[tuple], list[tuple]]:
    contrasts: list[tuple] = []
    power: list[tuple] = []
    unparsed: list[tuple[str, int]] = []
    for line in document.splitlines():
        if not line.startswith("| `"):
            continue
        cells = _cells(line)
        if len(cells) == 6:
            family, role, contrast, delta, interval, contains = cells
            low, high = interval.strip("[]").split(",")
            contrasts.append(
                (family.strip("`"), role, contrast.replace("Δ", ""),
                 _number(delta), _number(low), _number(high), "yes" in contains)
            )
        elif len(cells) == 4:
            family, effect, mde, note = cells
            power.append((family.strip("`"), _number(effect), _number(mde), note))
        else:
            unparsed.append((line[:80], len(cells)))

    assert not unparsed, f"table rows the parser could not read: {unparsed}"
    assert len(contrasts) == 12, (
        f"expected the twelve-contrast table, parsed {len(contrasts)} rows; a parser that "
        "drops rows makes every count below pass vacuously"
    )
    assert len(power) == 3, f"expected three families in the power table, parsed {len(power)}"
    return contrasts, power


def test_every_contrast_matches_the_artifact(tables, inference) -> None:
    contrasts, _ = tables
    wrong: list[str] = []
    for family, role, contrast, delta, low, high, contains_zero in contrasts:
        measured = inference[role]["nested_tests"][family][CONTRAST_KEY[contrast]]
        actual_contains = measured["ci_low"] <= 0 <= measured["ci_high"]
        for field, published, value in (
            ("estimate", delta, measured["estimate"]),
            ("ci_low", low, measured["ci_low"]),
            ("ci_high", high, measured["ci_high"]),
        ):
            if abs(published - value) >= TOLERANCE:
                wrong.append(f"{family}/{role}/{contrast}.{field}: doc {published} vs {value}")
        if contains_zero != actual_contains:
            wrong.append(
                f"{family}/{role}/{contrast}.contains_0: doc {contains_zero} vs {actual_contains}"
            )
    assert not wrong, "the verdict disagrees with its own run:\n  " + "\n  ".join(wrong)


def test_the_three_counts_match_the_artifact(tables, inference) -> None:
    contrasts, _ = tables
    measured = [
        inference[role]["nested_tests"][family][CONTRAST_KEY[contrast]]
        for family, role, contrast, *_ in contrasts
    ]
    counts = {
        "intervals containing zero": (
            sum(1 for c in measured if c["ci_low"] <= 0 <= c["ci_high"]),
            CLAIMED_INTERVALS_CONTAINING_ZERO,
        ),
        "below own MDE": (
            sum(1 for c in measured if abs(c["estimate"]) < c["mde"]),
            CLAIMED_BELOW_OWN_MDE,
        ),
        "positive deltas": (
            sum(1 for c in measured if c["estimate"] > 0),
            CLAIMED_POSITIVE_DELTAS,
        ),
    }
    wrong = [f"{k}: measured {got}, document says {claimed}"
             for k, (got, claimed) in counts.items() if got != claimed]
    assert not wrong, "a stated count no longer matches:\n  " + "\n  ".join(wrong)


def test_power_table_and_its_detectability_verdicts(tables, inference) -> None:
    _, power = tables
    wrong: list[str] = []
    for family, effect, mde, note in power:
        development = inference["D"]["nested_tests"][family]["b1_over_b0"]
        validation = inference["V"]["nested_tests"][family]["b1_over_b0"]
        if abs(effect - development["estimate"]) >= TOLERANCE:
            wrong.append(f"{family}.effect_in_D: doc {effect} vs {development['estimate']}")
        if abs(mde - validation["mde"]) >= TOLERANCE:
            wrong.append(f"{family}.mde_in_V: doc {mde} vs {validation['mde']}")

        detectable = validation["mde"] < abs(development["estimate"])
        if detectable != note.lower().startswith("**yes"):
            wrong.append(f"{family}: the document's detectability verdict contradicts the numbers")

        if family in CLAIMED_SESSIONS_NEEDED:
            # The minimum detectable effect falls as one over the square root of the
            # sample, so reaching a development-sized effect needs n*(mde/effect)^2.
            needed = math.ceil(
                validation["sessions"] * (validation["mde"] / abs(development["estimate"])) ** 2
            )
            claimed = CLAIMED_SESSIONS_NEEDED[family]
            if abs(needed - claimed) > 1:
                wrong.append(
                    f"{family}: document says ~{claimed} sessions, "
                    f"arithmetic gives {needed}"
                )
    assert not wrong, "the power table no longer matches its run:\n  " + "\n  ".join(wrong)
