"""Every tracked SQL file is structurally whole.

A migration is verified by running it, and running it means sending its text somewhere. A
dry run performed on a retyped copy verifies the copy: this file was committed with a
duplicated `),` that made the whole transaction invalid, while a hand-pasted rendition of it
had passed the section 17 acceptance minutes earlier.

These checks read the file. They do not prove the SQL is correct, which needs a database;
they prove it is not the kind of broken that a copy would not have shared.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _sql_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.sql"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    files = [REPO / name for name in listed]
    assert files, "no SQL files found, so this test proves nothing"
    return files


def _strip(text: str) -> str:
    """The statement text, without comments or string bodies that would skew the counts."""

    # Comments and string bodies only. The dollar-quoted body of a function is SQL too,
    # and stripping it removed the very lines the duplicated parenthesis was on: the
    # first version of this check passed while carrying the defect it exists for.
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"E?'(?:[^']|'')*'", "''", text)
    return text.replace("$$", "")


def test_parentheses_balance_in_every_sql_file() -> None:
    offenders = []
    for path in _sql_files():
        body = _strip(path.read_text(encoding="utf-8"))
        depth = 0
        for line_number, line in enumerate(body.splitlines(), 1):
            depth += line.count("(") - line.count(")")
            if depth < 0:
                offenders.append(f"{path.relative_to(REPO)}:{line_number} closes what is open")
                break
        else:
            if depth:
                offenders.append(f"{path.relative_to(REPO)} ends {depth:+d} parentheses open")
    assert not offenders, "unbalanced parentheses:\n" + "\n".join(offenders)


def test_no_assignment_is_followed_by_a_bare_closing_group() -> None:
    """`x = f(...)` then `),` on its own line is the shape the duplicated paren took.

    A `SET` clause whose next non-blank line closes a group nothing opened is invalid, and it
    reads as ordinary formatting in a diff.
    """

    offenders = []
    for path in _sql_files():
        lines = _strip(path.read_text(encoding="utf-8")).splitlines()
        for number, line in enumerate(lines[1:], start=2):
            previous = lines[number - 2].strip()
            if line.strip() in {"),", ")"} and previous in {"),", ")"}:
                offenders.append(f"{path.relative_to(REPO)}:{number} closes a group twice")
    assert not offenders, "duplicated closing groups:\n" + "\n".join(offenders)


def test_dollar_quoted_bodies_are_paired() -> None:
    for path in _sql_files():
        text = path.read_text(encoding="utf-8")
        assert text.count("$$") % 2 == 0, f"{path.relative_to(REPO)} has an odd number of $$"
