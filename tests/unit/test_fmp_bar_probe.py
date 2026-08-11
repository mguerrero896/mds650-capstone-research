"""Unit coverage for the non-blocking FMP bar-availability replay probe."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from mds650.provider_timing import (
    FMP_BAR_LABEL_SEMANTICS,
    FMP_LIVE_PROBE_STATUS,
    FMP_PROVIDER_CONFIRMED_LATENCY,
    FMP_RESEARCH_AVAILABILITY_RULE,
    summarize_fmp_bar_replay,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
probe_script = importlib.import_module("probe_fmp_bar_availability")


def test_fmp_replay_keeps_live_measurement_pending_and_non_blocking() -> None:
    """A replay validates the schema but does not claim live-provider latency."""
    summary = summarize_fmp_bar_replay(
        [
            {
                "bar_timestamp": "2026-08-11T14:30:00Z",
                "request_started_at_utc": "2026-08-11T14:31:00.100000Z",
                "request_completed_at_utc": "2026-08-11T14:31:00.350000Z",
                "received_at_utc": "2026-08-11T14:31:00.350000Z",
            }
        ]
    )

    assert summary["status"] == FMP_LIVE_PROBE_STATUS
    assert summary["fmp_bar_label_semantics"] == FMP_BAR_LABEL_SEMANTICS
    assert summary["fmp_provider_confirmed_latency"] == FMP_PROVIDER_CONFIRMED_LATENCY
    assert summary["fmp_research_availability_rule"] == FMP_RESEARCH_AVAILABILITY_RULE
    assert summary["replay_record_count"] == 1
    assert summary["publication_latency_proven"] is False


def test_fmp_replay_output_is_sanitized_and_deterministic(tmp_path: Path) -> None:
    """The serialized replay result contains neither secrets nor local paths."""
    summary = summarize_fmp_bar_replay(
        [
            {
                "bar_timestamp": "2026-08-11T14:30:00Z",
                "request_started_at_utc": "2026-08-11T14:31:00Z",
                "request_completed_at_utc": "2026-08-11T14:31:00.100000Z",
                "received_at_utc": "2026-08-11T14:31:00.100000Z",
                "apikey": "must-not-appear",
            }
        ]
    )
    output = tmp_path / "probe.json"
    output.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")

    rendered = output.read_text(encoding="utf-8")
    assert "must-not-appear" not in rendered
    assert str(tmp_path) not in rendered


def test_fmp_probe_cli_only_replays_local_fixture(tmp_path: Path) -> None:
    """The probe command writes a non-blocking replay result without networking."""
    replay = tmp_path / "fmp_replay.jsonl"
    replay.write_text(
        json.dumps(
            {
                "bar_timestamp": "2026-08-11T14:30:00Z",
                "request_started_at_utc": "2026-08-11T14:31:00Z",
                "request_completed_at_utc": "2026-08-11T14:31:00.100000Z",
                "received_at_utc": "2026-08-11T14:31:00.100000Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "fmp_result.json"

    assert probe_script.main(["--replay", str(replay), "--output", str(output)]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == FMP_LIVE_PROBE_STATUS
