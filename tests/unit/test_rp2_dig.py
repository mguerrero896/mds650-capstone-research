"""A path into a document either exists or it is a mistake, and those are different.

`document.get("a", {}).get("b", {}).get("c")` returns `None` when `c` is absent and when
`b` never existed, which is how a renderer read `forecast.delta_b1.gamma_glm.D` out of a
document whose real path is `forecast.gamma_glm.D.delta_b1` and printed a table of `n/a`
without failing. The absent value is data. The wrong path is a bug, and it has to say so.
"""

from __future__ import annotations

import pytest

from mds650.rp2.lookup import dig, dig_optional

DOCUMENT = {
    "forecast": {"gamma_glm": {"D": {"delta_b1": 0.004, "mde": None}}},
    "data": {"sessions_by_role": {"D": 389}},
}


def test_a_wrong_path_is_a_mistake_and_says_so() -> None:
    with pytest.raises(KeyError) as raised:
        dig(DOCUMENT, "forecast", "delta_b1", "gamma_glm", "D")
    # The message names where it stopped and what was there, because a path is wrong at one
    # level and a reader needs to know which.
    message = str(raised.value)
    assert "forecast.delta_b1" in message
    assert "gamma_glm" in message, "the keys that do exist are the fix"


def test_a_present_value_is_returned_including_a_present_none() -> None:
    assert dig(DOCUMENT, "forecast", "gamma_glm", "D", "delta_b1") == 0.004
    # `mde` exists and is null: that is a measurement the run did not make, not a typo.
    assert dig(DOCUMENT, "forecast", "gamma_glm", "D", "mde") is None


def test_optional_distinguishes_a_missing_leaf_from_a_missing_branch() -> None:
    """The leaf may be absent. The branch above it may not."""

    assert dig_optional(DOCUMENT, "data", "sessions_by_role", "V") is None
    with pytest.raises(KeyError):
        dig_optional(DOCUMENT, "data", "sessions_by_ROLE", "D")


def test_it_refuses_to_walk_through_something_that_is_not_a_mapping() -> None:
    with pytest.raises(KeyError, match="is not a mapping"):
        dig(DOCUMENT, "forecast", "gamma_glm", "D", "delta_b1", "deeper")
