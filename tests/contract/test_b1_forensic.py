"""Acceptance tests for the fail-closed B1 forensic artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _nested() -> dict:
    path = ROOT / "artifacts/b1_forensic/b1_nested_coverage.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_nested_benchmarks_are_monotone_at_all_reported_levels() -> None:
    data = _nested()
    assert data["invariants"] == {
        "b1c_implies_b1b": True,
        "b1b_implies_b1a": True,
        "coverage_b1c_le_b1b": True,
        "coverage_b1b_le_b1a": True,
    }
    for scope in ("global", "by_asset", "by_date", "by_session_segment"):
        values = [data[scope]] if scope == "global" else data[scope].values()
        for group in values:
            q = group["B1Q"]
            assert q["b1c_complete"] <= q["b1b_complete"] <= q["b1a_complete"]


def test_failure_waterfall_has_all_stages_for_each_origin() -> None:
    path = ROOT / "artifacts/b1_forensic/failure_waterfall.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 2_840 * 17
    by_origin: dict[str, set[str]] = {}
    for row in rows:
        by_origin.setdefault(row["origin_id"], set()).add(row["stage"])
    assert len(by_origin) == 2_840
    assert all(len(stages) == 17 for stages in by_origin.values())


def test_controlled_zero_coverage_trace_is_explicit_and_reproducible() -> None:
    path = ROOT / "artifacts/b1_forensic/zero_coverage_controlled.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["assets"] == ["SPY", "QQQ", "META", "TSLA"]
    assert data["origins"] == 12
    assert len(data["cases"]) == 72
    assert data["secret_values_emitted"] is False
    allowed_failures = {None, "NO_QUOTE_BEFORE_ORIGIN", "STALE_QUOTE", "INVALID_SPREAD"}
    assert all(row["failure_code"] in allowed_failures for row in data["cases"])


def test_full_tape_route_remains_diagnostic_only() -> None:
    data = _nested()
    assert data["global"]["B1T"]["b1a_complete"] == 1.0
    assert data["global"]["B1T"]["b1b_complete"] == 1.0
    assert data["global"]["B1T"]["b1c_complete"] == 1.0
    selection = (ROOT / "docs/b1_benchmark_selection.md").read_text(encoding="utf-8")
    assert "diagnostic" in selection.lower()


def test_literature_ledger_uses_conservative_status_vocabulary() -> None:
    allowed = {
        "VERIFIED_FULL_TEXT",
        "VERIFIED_ABSTRACT_ONLY",
        "VERIFIED_PUBLISHER_METADATA_ONLY",
        "UNRESOLVED",
    }
    path = ROOT / "docs/literature_evidence_ledger.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 10
    assert {row["full_text_status"] for row in rows} <= allowed
    strengths = {row["claim_strength_allowed"] for row in rows}
    assert strengths <= {
        "STRONG_FULL_TEXT",
        "LIMITED_ABSTRACT",
        "METADATA_ONLY",
        "EXCLUDE_FROM_ARGUMENT",
    }
    assert all(row["page"] and row["section"] and row["table_or_figure"] for row in rows)


def test_twenty_session_probe_is_metadata_only() -> None:
    path = ROOT / "artifacts/api_audit/twenty_session_availability_probe.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["count"] == 20
    assert len(data["records"]) == 20
    assert data["full_tape_downloaded"] is False
    assert data["pit_claim"] is False
    assert all(
        row["full_tape_downloaded"] is False and row["uw_pit_claim"] is False
        for row in data["records"]
    )


def test_repair_waterfall_and_controlled_reconciliation_are_closed() -> None:
    waterfall_path = ROOT / "artifacts/b1_repair/first_failure_waterfall.csv"
    waterfall = list(csv.DictReader(waterfall_path.open(encoding="utf-8")))
    assert len(waterfall) == 2_840
    assert sum(int(row["origin_count"]) for row in waterfall) == 2_840
    assert len({row["origin_id"] for row in waterfall}) == 2_840
    diff_path = ROOT / "artifacts/b1_repair/controlled_vs_pipeline_diff.csv"
    diff = list(csv.DictReader(diff_path.open(encoding="utf-8")))
    assert len(diff) == 4
    assert all(row["first_divergent_stage"] == "none" for row in diff)
    cache_path = ROOT / "artifacts/b1_repair/cache_key_audit.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["duplicate_active_cache_keys"] == 0
    assert cache["active_cache_keys"] == cache["unique_active_cache_keys"]
