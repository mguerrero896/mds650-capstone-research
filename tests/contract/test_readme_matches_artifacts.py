"""The README's front page must agree with the run it says it reports.

`README.md` scopes its findings list with "Measured on `rp2-v3-...`", and then states
figures nothing recomputes. Two of them were RP2-v2 measurements that survived the rebuild
underneath that heading: the DML joint test as `p = 3e-46` on 383 sessions where the run
gives `p = 3.9e-09` on 389, and Hansen's SPA as `p = 0.0070, above the project's own
sequential budget of 0.00417` where the rebuilt within-family race gives `p = 0.0010`,
which clears that budget instead of failing it. A reader had no way to tell, because the
heading said the numbers came from the run.

This reads the run id out of the README and checks each stated figure against that run's
artifacts, the same way `test_verdict_matches_artifact.py` does for the verdict.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
README = REPO / "README.md"


#: The document writes exponents with superscript characters. Those are Unicode category
#: No, not Nd, so `\d` does not match them and a pattern written against them silently
#: finds nothing - which is how a test can pass while checking no figure at all.
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


@pytest.fixture(scope="module")
def readme() -> str:
    if not README.is_file():
        pytest.fail(f"the README is missing: {README}")
    return README.read_text(encoding="utf-8").translate(SUPERSCRIPTS)


@pytest.fixture(scope="module")
def run_directory(readme: str) -> Path:
    match = re.search(r"Measured on `(rp2-v3-[\w-]+)`", readme)
    assert match, "the README no longer states the run its findings were measured on"
    path = REPO / "artifacts" / "rp2_v3" / match.group(1)
    if not path.is_dir():
        pytest.skip(f"run {match.group(1)} is not present in this checkout: {path}")
    return path


def _artifact(run_directory: Path, block: str, name: str) -> dict:
    path = run_directory / block / name
    if not path.is_file():
        pytest.skip(f"{path} is not present in this checkout")
    return json.loads(path.read_text(encoding="utf-8"))


def _stated(readme: str, pattern: str) -> str:
    match = re.search(pattern, readme)
    assert match, f"the README no longer states the figure matched by {pattern!r}"
    return match.group(1)


def test_the_dml_headline_matches_the_run(readme: str, run_directory: Path) -> None:
    measured = _artifact(run_directory, "rp2_block7_dml", "dml.json")["core_D"]["delta_log_rv30"]

    exponent = int(_stated(readme, r"rejected in discovery at\s+\*\*p = [\d.]+ . 10-(\d+)\*\*"))
    mantissa = float(_stated(readme, r"\*\*p = ([\d.]+) . 10-\d+\*\*, Wald"))
    wald = float(_stated(readme, r"Wald ([\d.]+) on"))
    clusters = int(_stated(readme, r"on ([\d,]+) session clusters").replace(",", ""))
    rows = int(_stated(readme, r"session clusters and ([\d,]+) rows").replace(",", ""))

    stated_p = mantissa * 10.0**-exponent
    assert stated_p == pytest.approx(measured["joint_p_value"], rel=0.02), (
        f"README states p = {stated_p:g}, the run gives {measured['joint_p_value']:g}"
    )
    assert wald == pytest.approx(measured["joint_wald"], abs=0.01)
    assert clusters == measured["clusters"]
    assert rows == measured["rows"]


def test_the_spa_headline_matches_the_run(readme: str, run_directory: Path) -> None:
    inference = _artifact(run_directory, "rp2_block10_inference", "inference.json")
    measured = inference["D"]["superior_predictive_ability"]["ridge_log"]["B0"]

    best = _stated(readme, r"picks `([\w|+]+)` over")
    benchmark = _stated(readme, r"picks `[\w|+]+` over `([\w|+]+)`")
    candidates = int(_stated(readme, r"out of (\w+) candidates").replace("three", "3"))
    spa = float(_stated(readme, r"at \*\*p = ([\d.]+)\*\* on [\d,]+ evaluated sessions"))
    sessions = int(_stated(readme, r"on ([\d,]+) evaluated sessions").replace(",", ""))
    reality = float(_stated(readme, r"rejects nothing \(p = ([\d.]+)\)"))

    assert best == measured["best_model"]
    assert benchmark == measured["benchmark"]
    assert candidates == measured["candidates"]
    assert sessions == measured["sessions"]
    assert spa == pytest.approx(measured["spa_p_value"], abs=5e-5), (
        f"README states SPA p = {spa}, the run gives {measured['spa_p_value']}"
    )
    assert reality == pytest.approx(measured["reality_check_p_value"], abs=5e-5)


def test_the_superseded_figures_are_recorded_rather_than_deleted(readme: str) -> None:
    """A reader who followed a citation to the old number must still find it."""
    for withdrawn in ("3 × 10-46", "383 sessions", "p = 0.0070", "0.00417"):
        assert withdrawn in readme, (
            f"{withdrawn!r} was removed rather than marked as superseded; a number this "
            "project published has to remain findable with the record that replaced it"
        )
