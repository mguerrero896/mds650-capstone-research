"""Bounded authenticated smoke test for the Phase 6 continuity probe."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from probe_phase6_continuity import probe_asset_day  # noqa: E402

pytestmark = pytest.mark.live


def test_one_asset_day_is_sanitized_and_point_in_time() -> None:
    required = ("FMP_API_KEY", "UNUSUALWHALES_API_KEY", "MASSIVE_API_KEY")
    if not all(os.environ.get(name) for name in required):
        pytest.skip("authenticated provider secrets are absent")

    row = asyncio.run(probe_asset_day(date(2025, 7, 7), "AAPL"))
    serialized = json.dumps(row, sort_keys=True)

    assert row["fmp_session_pass"] is True
    assert row["uw_file_metadata_pass"] is True
    assert row["massive_quote_pass"] is True
    assert row["massive_sip_le_origin"] is True
    assert not any(os.environ[name] in serialized for name in required)
