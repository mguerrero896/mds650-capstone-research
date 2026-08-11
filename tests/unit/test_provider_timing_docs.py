"""Regression coverage for deterministic provider-timing documentation rendering."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
renderer = importlib.import_module("render_provider_timing_docs")


def test_renderer_writes_required_documents_from_sanitized_evidence(tmp_path: Path) -> None:
    """Rendered documentation keeps gate semantics and excludes physical paths."""
    manifest = tmp_path / "evidence.json"
    manifest.write_text(json.dumps(_fixture_manifest()), encoding="utf-8")
    docs = tmp_path / "docs"

    assert renderer.main(["--manifest", str(manifest), "--docs-dir", str(docs)]) == 0

    semantics = (docs / "provider_timing_semantics_audit_v1.md").read_text(encoding="utf-8")
    gates = (docs / "provider_timing_gate_amendment_v1.md").read_text(encoding="utf-8")
    guide = (docs / "provider_timing_future_execution_guide.md").read_text(encoding="utf-8")
    assert "PROXY_ONLY" in semantics
    assert "CONDITIONAL_GO_NOW" in gates
    assert "PENDING_PROSPECTIVE_MEASUREMENT_NOT_BLOCKING" in guide
    assert str(tmp_path) not in semantics + gates + guide


def _fixture_manifest() -> dict[str, object]:
    """Return a minimal schema-compatible sanitized timing manifest."""
    global_summary: dict[str, object] = {
        "row_count": 1,
        "created_at_completeness": 1.0,
        "executed_at_completeness": 1.0,
        "negative_latency_count": 0,
        "latency_p1_seconds": 0.1,
        "latency_p5_seconds": 0.1,
        "latency_p50_seconds": 0.1,
        "latency_p90_seconds": 0.1,
        "latency_p95_seconds": 0.1,
        "latency_p99_seconds": 0.1,
        "latency_max_seconds": 0.1,
        "latency_within_60_seconds_share": 1.0,
        "latency_within_120_seconds_share": 1.0,
        "latency_within_300_seconds_share": 1.0,
    }
    return {
        "fmp": {
            "retrieved_on": "2026-08-11",
            "fmp_bar_label_semantics": "UNVERIFIED",
            "fmp_provider_confirmed_latency": "NOT_SUPPORTED",
            "fmp_research_availability_rule": "SUPPORTED_CONSERVATIVE_ASSUMPTION",
            "live_probe_status": "PENDING_PROSPECTIVE_MEASUREMENT_NOT_BLOCKING",
            "official_sources": [
                {
                    "title": "Official FMP",
                    "url": "https://example.test/fmp",
                    "observed_statement": "One minute endpoint.",
                }
            ],
        },
        "unusual_whales": {
            "historical_uw_classification": "PROXY_ONLY",
            "global": global_summary,
            "cohort_stability": {
                "comparisons": [],
                "interpretation": "Fixture comparison boundary.",
            },
        },
        "gates": {
            "EXISTING_CANONICAL_EVIDENCE": "VALID_UNDER_REGISTERED_TIMING_ASSUMPTIONS",
            "EXISTING_SCIENTIFIC_RECONCILIATION": "CONDITIONAL_GO_NOW",
            "NEW_HISTORICAL_SAMPLE": "GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT",
            "NEW_PROSPECTIVE_SAMPLE": "GO_AFTER_RECEIPT_LOGGER_VALIDATED",
            "UNIVERSAL_PROVIDER_LATENCY_CLAIM": "NOT_SUPPORTED",
        },
    }
