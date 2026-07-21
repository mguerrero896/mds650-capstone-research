"""Export a deterministic, fixture-only preview of the pilot dataset.

This script deliberately never calls a provider.  It exercises the same local
pilot builder used by the planned pipeline so the resulting table shapes and
RV30 trace can be inspected while provider gates remain closed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from mds650.contracts import (
    CorporateEvent,
    OptionQuote,
    OptionStateSnapshot,
    OptionTrade,
    UnusualOptionEvent,
)
from mds650.pilot import PilotResult, build_pilot

ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
RUN_ID = "fixture-preview-20260721"


def _raw_bars(asset_index: int) -> list[dict[str, object]]:
    start = datetime(2026, 7, 16, 9, 30)
    return [
        {
            "date": (start + timedelta(minutes=index)).strftime("%Y-%m-%d %H:%M:%S"),
            "open": 100.0 + asset_index + index * 0.01,
            "high": 101.0 + asset_index + index * 0.01,
            "low": 99.5 + asset_index + index * 0.01,
            "close": 100.0 + asset_index + index * 0.01,
            "volume": 1000 + index,
        }
        for index in range(40)
    ]


def _event(asset: str, index: int) -> UnusualOptionEvent:
    timestamp = datetime(2026, 7, 16, 13, 34, tzinfo=UTC)
    return UnusualOptionEvent(
        run_id=RUN_ID,
        source_provider="unusual_whales",
        source_response_id=f"uw-{asset}",
        observed_at_utc=timestamp,
        event_id=f"event-{asset}",
        asset=asset,
        contract_id=f"{asset}-CONTRACT",
        event_time_utc=timestamp,
        available_at_utc=timestamp,
        premium=1000.0 + index,
        size=10,
        volume=20,
        open_interest=30,
        volume_oi_ratio=2 / 3,
        option_type="call",
        strike=100,
        expiry=date(2026, 8, 21),
    )


def _components() -> tuple[
    list[CorporateEvent],
    list[UnusualOptionEvent],
    list[OptionStateSnapshot],
    list[OptionTrade],
    list[OptionQuote],
]:
    observed = datetime(2026, 7, 16, 13, 35, tzinfo=UTC)
    earnings = [
        CorporateEvent(
            run_id=RUN_ID,
            source_provider="fmp",
            source_response_id=f"earnings-{asset}",
            observed_at_utc=datetime(2026, 7, 16, 0, 0, tzinfo=UTC),
            asset=asset,
            event_type="earnings",
            event_date_ny=date(2026, 7, 16),
            timestamp_quality="date_only",
        )
        for asset in ASSETS
    ]
    events = [_event(asset, index) for index, asset in enumerate(ASSETS)]
    states = [
        OptionStateSnapshot(
            run_id=RUN_ID,
            source_provider="unusual_whales",
            source_response_id=f"state-{asset}",
            observed_at_utc=observed,
            asset=asset,
            contract_or_surface_key=f"{asset}:ATM",
            available_at_utc=observed,
            coverage_flag="observed",
            iv=0.2,
        )
        for asset in ASSETS
    ]
    trades = [
        OptionTrade(
            run_id=RUN_ID,
            source_provider="massive",
            source_response_id=f"trade-{asset}",
            observed_at_utc=observed,
            contract_id=f"{asset}-CONTRACT",
            trade_time_utc=observed,
            price=1.0,
            size=1.0,
        )
        for asset in ASSETS
    ]
    quotes = [
        OptionQuote(
            run_id=RUN_ID,
            source_provider="massive",
            source_response_id=f"quote-{asset}",
            observed_at_utc=observed,
            contract_id=f"{asset}-CONTRACT",
            quote_time_utc=observed,
            bid=0.9,
            ask=1.1,
        )
        for asset in ASSETS
    ]
    return earnings, events, states, trades, quotes


def _rows(items: Any) -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in items]


def _write_table(output_dir: Path, name: str, rows: list[dict[str, object]]) -> int:
    frame = pl.DataFrame(rows)
    frame.write_parquet(output_dir / f"{name}.parquet")
    return frame.height


def _build() -> PilotResult:
    earnings, events, states, trades, quotes = _components()
    return build_pilot(
        raw_underlying={asset: _raw_bars(index) for index, asset in enumerate(ASSETS)},
        corporate_events=earnings,
        unusual_events=events,
        option_states=states,
        option_trades=trades,
        option_quotes=quotes,
        run_id=RUN_ID,
        source_timezone="America/New_York",
        expected_rows_per_asset=40,
    )


def main() -> None:
    """Build the preview and write auditable Parquet/JSON artifacts."""
    output_dir = Path("artifacts/pilot_preview/fixture_20260721")
    output_dir.mkdir(parents=True, exist_ok=True)
    result = _build()
    earnings, events, states, trades, quotes = _components()
    tables = {
        "underlying_1min": [bar.model_dump(mode="json") for bar in result.underlying_bars],
        "corporate_events": _rows(earnings),
        "unusual_option_events": _rows(events),
        "option_state_snapshots": _rows(states),
        "option_trades": _rows(trades),
        "option_quotes": _rows(quotes),
        "forecast_origins": _rows(result.origins),
        "rv30_targets": _rows(result.targets),
        "row_trace": list(result.row_trace),
    }
    row_counts = {name: _write_table(output_dir, name, rows) for name, rows in tables.items()}
    recipe_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest = {
        "manifest_schema_version": "fixture-preview-1.0",
        "run_id": RUN_ID,
        "mode": "fixture_preview",
        "fixture_data_only": True,
        "synthetic_data_used": True,
        "historical_provider_backfill": False,
        "authorized_for_backfill": False,
        "source_recipe_sha256": recipe_hash,
        "candidate_assets": list(ASSETS),
        "covered_assets": list(result.covered_assets),
        "frozen_assets": list(result.frozen_assets.assets),
        "frozen_by": "coverage_and_quality_fixture_only",
        "b1_status": "BLOCKED",
        "common_history_status": "NOT_ESTABLISHED",
        "blockers": [
            "B1_NOT_AUTHORIZED",
            "COMMON_HISTORY_NOT_ESTABLISHED",
            "PROVIDER_FAILURES_PRESENT",
        ],
        "target_contract": {
            "anchor_plus_future_closes": 31,
            "future_log_returns": 30,
            "formula_version": "rv30-v1",
        },
        "row_counts": row_counts,
        "target_exclusions": list(result.target_exclusions),
        "event_no_event_counts": {
            asset: {"event": pair[0], "no_event": pair[1]}
            for asset, pair in result.event_no_event_counts.items()
        },
        "warning": (
            "Not historical provider data, not a pilot acceptance, and not authorized for modeling."
        ),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    report_lines = [
        "# Fixture-only dataset preview",
        "",
        "This artifact is deterministic fixture data, not historical provider data.",
        "It is not a pilot acceptance and is not authorized for modeling or evaluation.",
        "",
        f"- Run: `{RUN_ID}`",
        f"- Candidates covered: {len(result.covered_assets)}",
        "- Frozen assets (quality/coverage fixture gate): "
        f"{', '.join(result.frozen_assets.assets)}",
        f"- Valid RV30 targets: {len(result.targets)}",
        f"- Excluded origins with missing future bars: {len(result.target_exclusions)}",
        "- RV30 contract: one fully observed anchor close plus 30 future closes = 30 log returns",
        "",
        "## Table row counts",
        "",
        "| table | rows |",
        "|---|---:|",
    ]
    report_lines.extend(f"| `{name}` | {count} |" for name, count in row_counts.items())
    report_lines.extend(
        [
            "",
            "## Gate status",
            "",
            "- `B1_NOT_AUTHORIZED`",
            "- `COMMON_HISTORY_NOT_ESTABLISHED`",
            "- `PROVIDER_FAILURES_PRESENT`",
            "- `authorized_for_backfill=false`",
        ]
    )
    (output_dir / "README.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
