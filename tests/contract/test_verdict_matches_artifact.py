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
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "rp2_v3" / "VERDICT.md"

#: `ΔB2\|B1` escapes the pipe so the cell survives the markdown table; mask it before
#: splitting on the column separator.
ESCAPED_PIPE = chr(92) + "|"
MASK = "\x00"

CONTRAST_KEY = {"B1": "b1_over_b0", "B2|B1": "b2_over_b1"}

#: The three counts are stated in the prose as English words. They were pinned here as
#: literals, so a rebuild that moved a count needed this file edited alongside the
#: document — and a test you have to edit to keep a document honest will eventually be
#: edited to agree with it. They are read out of the document instead, which is what this
#: file is for: checking that the document agrees with the run it names.
WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
#: Each stated count, and how the same thing is counted from the artifact. "intervals
#: contain zero" appears twice in the document, so every occurrence is collected and they
#: must agree with each other as well as with the run.
CLAIMS: tuple[tuple[str, str, Callable[[dict], bool]], ...] = (
    ("positive deltas", r"(\w+) of twelve deltas are positive", lambda c: c["estimate"] > 0),
    (
        "intervals containing zero",
        r"(\w+) of twelve intervals contain zero",
        lambda c: c["ci_low"] <= 0 <= c["ci_high"],
    ),
    (
        "below own MDE",
        r"(\w+) of the twelve contrasts sit below their own",
        lambda c: abs(c["estimate"]) < c["mde"],
    ),
)
#: The "Not A" argument counts the sign of the six B2-over-B1 pairs separately, over a
#: different denominator, so it needs its own entry. It read "four of the six" against a
#: true five in every run this repository holds - wrong before the rebuild and carried
#: through the rewrite - while README.md stated five, so two published documents disagreed.
#: None of the three patterns above matches its phrasing, which is why nothing caught it.
SIX_PAIRS: Final = (
    "negative B2-over-B1 pairs",
    r"(\w+) of the six family-role pairs",
    "b2_over_b1",
)
#: The two sizing figures the power table's prose states, read from the document so the
#: same rule applies to them.
SESSIONS_NEEDED = r"~(\d+) sessions needed|roughly (\d+) sessions would be needed"

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
def tables(document: str) -> tuple[list[tuple], list[tuple], list[tuple]]:
    contrasts: list[tuple] = []
    power: list[tuple] = []
    movement: list[tuple] = []
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
        elif len(cells) == 3 and "→" in cells[1]:
            # The rebuild's before/after table. Its "unchanged" column is a claim about
            # validation, so it is parsed and checked rather than skipped.
            family, moved, in_validation = cells
            before, after = (part.strip(" *") for part in moved.split("→"))
            movement.append(
                (family.strip("`"), _number(before), _number(after),
                 _number(in_validation.split(",")[0]), "unchanged" in in_validation)
            )
        else:
            unparsed.append((line[:80], len(cells)))

    assert not unparsed, f"table rows the parser could not read: {unparsed}"
    assert len(contrasts) == 12, (
        f"expected the twelve-contrast table, parsed {len(contrasts)} rows; a parser that "
        "drops rows makes every count below pass vacuously"
    )
    assert len(power) == 3, f"expected three families in the power table, parsed {len(power)}"
    return contrasts, power, movement


def test_every_contrast_matches_the_artifact(tables, inference) -> None:
    contrasts, _, _ = tables
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


def test_the_three_counts_match_the_artifact(document, tables, inference) -> None:
    contrasts, _, _ = tables
    measured = [
        inference[role]["nested_tests"][family][CONTRAST_KEY[contrast]]
        for family, role, contrast, *_ in contrasts
    ]
    wrong: list[str] = []
    for label, pattern, predicate in CLAIMS:
        stated = re.findall(pattern, document, flags=re.IGNORECASE)
        if not stated:
            wrong.append(f"{label}: the document no longer states this count")
            continue
        claimed = {WORDS.get(word.lower()) for word in stated}
        if None in claimed:
            wrong.append(f"{label}: {stated} is not a number word this test can read")
        elif len(claimed) > 1:
            wrong.append(
                f"{label}: the document states it {len(stated)} times and they disagree: {stated}"
            )
        else:
            got = sum(1 for c in measured if predicate(c))
            if got != claimed.pop():
                wrong.append(f"{label}: measured {got}, document says {stated[0]}")
    assert not wrong, "a stated count no longer matches:\n  " + "\n  ".join(wrong)


def test_power_table_and_its_detectability_verdicts(tables, inference) -> None:
    _, power, _ = tables
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

        # The sizing figure, when the row states one, is read out of that row rather than
        # pinned in this file: the minimum detectable effect falls as one over the square
        # root of the sample, so reaching a development-sized effect needs n*(mde/effect)^2.
        sizing = re.search(SESSIONS_NEEDED, note)
        if sizing:
            claimed = int(next(group for group in sizing.groups() if group))
            needed = math.ceil(
                validation["sessions"] * (validation["mde"] / abs(development["estimate"])) ** 2
            )
            if abs(needed - claimed) > 1:
                wrong.append(
                    f"{family}: document says ~{claimed} sessions, arithmetic gives {needed}"
                )
        elif not detectable:
            wrong.append(
                f"{family}: the row says validation could not detect the effect but states "
                "no sample size that could, so a reader cannot tell how far short it fell"
            )
    assert not wrong, "the power table no longer matches its run:\n  " + "\n  ".join(wrong)


def test_the_rebuild_table_matches_both_runs(document, tables, inference) -> None:
    """The before/after table states that validation did not move. That is checkable.

    The page argues the development effect fell because the baseline was repaired, and
    points at validation as the control: no deficient bar store supplied it, so nothing
    there should have changed. Each row's "after" is checked against the run this document
    names, and each row's "before" against the run it says it supersedes, so the claim of
    an unchanged control is verified rather than asserted.
    """
    _, _, movement = tables
    assert len(movement) == 3, (
        f"expected three families in the rebuild table, parsed {len(movement)}"
    )

    superseded = re.search(r"supersedes `(rp2-v3-[\w-]+)`", document)
    assert superseded, "the page no longer names the run it supersedes"
    older_path = (
        REPO / "artifacts" / "rp2_v3" / superseded.group(1)
        / "rp2_block10_inference" / "inference.json"
    )
    older = json.loads(older_path.read_text(encoding="utf-8")) if older_path.is_file() else None

    wrong: list[str] = []
    for family, before, after, in_validation, claims_unchanged in movement:
        current_d = inference["D"]["nested_tests"][family]["b1_over_b0"]["estimate"]
        current_v = inference["V"]["nested_tests"][family]["b1_over_b0"]["estimate"]
        if abs(after - current_d) >= TOLERANCE:
            wrong.append(f"{family}: table says the rebuild gives {after}, run gives {current_d}")
        if abs(in_validation - current_v) >= TOLERANCE:
            wrong.append(f"{family}: table says V is {in_validation}, run gives {current_v}")
        if older is None:
            continue
        previous_d = older["D"]["nested_tests"][family]["b1_over_b0"]["estimate"]
        previous_v = older["V"]["nested_tests"][family]["b1_over_b0"]["estimate"]
        if abs(before - previous_d) >= TOLERANCE:
            wrong.append(f"{family}: table says the old run gave {before}, it gave {previous_d}")
        if claims_unchanged and abs(previous_v - current_v) >= TOLERANCE:
            wrong.append(
                f"{family}: the table calls validation unchanged, but it moved from "
                f"{previous_v} to {current_v}"
            )
    joined = "\n  ".join(wrong)
    assert not wrong, f"the rebuild table does not match the runs:\n  {joined}"


def test_the_six_pair_count_matches_the_artifact(document, inference) -> None:
    """The Not-A argument's own count, over the six B2-over-B1 pairs rather than twelve."""
    label, pattern, key = SIX_PAIRS
    stated = re.findall(pattern, document, flags=re.IGNORECASE)
    assert stated, f"{label}: the document no longer states this count"
    claimed = {WORDS.get(word.lower()) for word in stated}
    assert None not in claimed, f"{label}: {stated} is not a number word this test can read"
    assert len(claimed) == 1, f"{label}: stated {len(stated)} times and they disagree: {stated}"

    negative = sum(
        1
        for role in ("D", "V")
        for family in inference[role]["nested_tests"]
        if inference[role]["nested_tests"][family][key]["estimate"] < 0
    )
    assert negative == claimed.pop(), (
        f"{label}: measured {negative} of six, document says {stated[0]}"
    )
