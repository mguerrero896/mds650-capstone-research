"""The before/after table is read off both scorecards, not written by hand.

Two columns typed by a person can come from different runs, different fields or different
roundings and still look like a comparison. This reads both files and reports every
comparable field, including the ones that did not move, so an unchanged number is evidence
rather than an omission.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "rp2_v3_scorecard_diff", REPO / "scripts" / "rp2_v3_scorecard_diff.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rp2_v3_scorecard_diff"] = module
    spec.loader.exec_module(module)
    return module


def test_it_reports_what_moved_and_what_did_not() -> None:
    module = _load()
    before = {
        "data": {"b0_rows": 184632, "sessions_by_role": {"D": 389, "V": 80}},
        "b2": {"b2_p95_provider_latency_s": 0.122, "b2_mean_provider_latency_s": 1.221},
        "engineering": {"runtime_seconds": 3600.0, "code_commit": "aaa"},
    }
    after = {
        "data": {"b0_rows": 184632, "sessions_by_role": {"D": 389, "V": 80}},
        "b2": {"b2_p95_provider_latency_s": 4.5, "b2_mean_provider_latency_s": 1.221},
        "engineering": {"runtime_seconds": 99.0, "code_commit": "bbb"},
    }
    rows = {row["field"]: row for row in module.compare(before, after)}

    assert rows["b2.b2_p95_provider_latency_s"]["moved"] is True
    assert rows["b2.b2_p95_provider_latency_s"]["before"] == 0.122
    assert rows["b2.b2_p95_provider_latency_s"]["after"] == 4.5
    # An unchanged number is reported as unchanged rather than omitted: that a rebuild left
    # the sample alone is exactly the kind of claim the table has to support.
    assert rows["data.b0_rows"]["moved"] is False
    assert rows["data.sessions_by_role.D"]["before"] == 389
    assert rows["engineering.code_commit"]["moved"] is True
    # And the fields that say when rather than what are not compared at all.
    assert "engineering.runtime_seconds" not in rows


def test_a_field_present_in_only_one_scorecard_is_still_reported() -> None:
    """A field that appeared or vanished is a change, and the harder one to notice."""

    module = _load()
    rows = {row["field"]: row for row in module.compare({"b2": {}}, {"b2": {"new": 1}})}
    assert rows["b2.new"] == {"field": "b2.new", "before": None, "after": 1, "moved": True}
