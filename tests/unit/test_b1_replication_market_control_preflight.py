"""Contracts for the target-blind SPY/QQQ provider-plan supplement."""

from __future__ import annotations

import sys
from pathlib import Path

from mds650.b1v3_confirmation import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_b1_replication_market_control_preflight as supplement  # noqa: E402


def test_market_control_plan_preserves_dates_and_only_adds_spy_qqq() -> None:
    source: dict[str, object] = {
        "schema_version": "b1-independent-replication-provider-plan-1.0",
        "status": "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION",
        "target_blind": True,
        "outcome_read_count": 0,
        "assets": ["AAPL"],
        "sessions": [
            {
                "date": "2024-12-10",
                "role": "confirmation",
                "open_utc": "2024-12-10T14:30:00+00:00",
                "close_utc": "2024-12-10T21:00:00+00:00",
                "forecast_origin_utc": "2024-12-10T17:45:00+00:00",
                "forecast_origin_ns": 1733852700000000000,
                "expected_regular_minutes": 390,
            }
        ],
        "training_session_count": 0,
        "confirmation_session_count": 1,
        "source_confirmation_plan_sha256": "a" * 64,
    }
    source["plan_sha256"] = canonical_sha256(source)

    plan = supplement.build_market_control_plan(source)
    mapping = plan.to_mapping()

    assert plan.assets == ("SPY", "QQQ")
    assert [item.date for item in plan.sessions] == ["2024-12-10"]
    assert plan.outcome_read_count == 0
    assert plan.source_confirmation_plan_sha256 == "a" * 64
    unsigned = {key: value for key, value in mapping.items() if key != "plan_sha256"}
    assert mapping["plan_sha256"] == canonical_sha256(unsigned)
