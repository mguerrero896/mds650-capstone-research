"""Unit coverage for the prospective Unusual Whales receipt logger."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from mds650.provider_timing import build_uw_receipt_record, reconcile_uw_replay_records

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
receipt_script = importlib.import_module("log_uw_option_trade_receipts")
reconcile_script = importlib.import_module("reconcile_uw_live_vs_full_tape")


def test_receipt_logger_keeps_required_timing_fields_and_hashes_raw_message() -> None:
    """A replay record is sanitized while retaining a deterministic content hash."""
    message = {
        "id": "event-1",
        "trade_id": "trade-1",
        "aggregated_trade_id": "aggregate-1",
        "executed_at": "2026-08-11T14:30:00Z",
        "created_at": "2026-08-11T14:30:00.250000Z",
        "apiKey": "must-not-appear",
    }

    record = build_uw_receipt_record(
        message,
        received_at_utc="2026-08-11T14:30:00.500000Z",
        source="unusual_whales_full_tape_replay",
        connection_type="replay",
        local_clock_offset="+00:00",
    )

    assert record["event_id"] == "event-1"
    assert record["trade_id"] == "trade-1"
    assert record["aggregated_trade_id"] == "aggregate-1"
    assert (
        record["raw_message_hash"]
        == build_uw_receipt_record(
            message,
            received_at_utc="2026-08-11T14:30:01Z",
            source="other",
            connection_type="replay",
            local_clock_offset="+00:00",
        )["raw_message_hash"]
    )
    assert len(str(record["raw_message_hash"])) == 64
    assert "must-not-appear" not in json.dumps(record, sort_keys=True)


def test_reconciliation_uses_identifier_keys_and_is_replay_only() -> None:
    """Replay reconciliation declares no live receipt or publication proof."""
    receipts = [
        {
            "event_id": "event-1",
            "trade_id": "trade-1",
            "aggregated_trade_id": None,
            "received_at_utc": "2026-08-11T14:30:00.500000Z",
        }
    ]
    full_tape = [
        {
            "id": "event-1",
            "trade_id": "trade-1",
            "aggregated_trade_id": None,
            "created_at": "2026-08-11T14:30:00.250000Z",
        }
    ]

    reconciliation = reconcile_uw_replay_records(receipts, full_tape)

    assert reconciliation["status"] == "REPLAY_ONLY_NOT_LIVE"
    assert reconciliation["matched_count"] == 1
    assert reconciliation["unmatched_receipt_count"] == 0
    assert reconciliation["publication_time_proven"] is False


def test_receipt_and_reconciliation_clis_use_only_local_replay(tmp_path: Path) -> None:
    """Both prospective utilities operate on fixtures without a provider request."""
    source_replay = tmp_path / "uw_source.jsonl"
    source_replay.write_text(
        json.dumps(
            {
                "id": "event-1",
                "trade_id": "trade-1",
                "created_at": "2026-08-11T14:30:00.100000Z",
                "executed_at": "2026-08-11T14:30:00Z",
                "received_at_utc": "2026-08-11T14:30:00.200000Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_output = tmp_path / "receipts.jsonl"
    assert (
        receipt_script.main(["--replay", str(source_replay), "--output", str(receipt_output)]) == 0
    )

    reconciliation_output = tmp_path / "reconciliation.json"
    assert (
        reconcile_script.main(
            [
                "--receipt-replay",
                str(receipt_output),
                "--full-tape-replay",
                str(source_replay),
                "--output",
                str(reconciliation_output),
            ]
        )
        == 0
    )
    result = json.loads(reconciliation_output.read_text(encoding="utf-8"))
    assert result["status"] == "REPLAY_ONLY_NOT_LIVE"
    assert result["matched_count"] == 1
