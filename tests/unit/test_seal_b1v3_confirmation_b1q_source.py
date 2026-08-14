"""CLI contract for sealing the canonical B1v3 Massive source."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from seal_b1v3_confirmation_b1q_source import _arguments  # noqa: E402


def test_cli_defaults_are_confirmation_scoped_and_target_free() -> None:
    args = _arguments([])

    assert args.attempts == Path(
        "D:/MDS650/b1v3_confirmation/tmp/b1q_acquisition_v1/b1_iv_attempts_20d.parquet"
    )
    assert args.contract_grid.name == "resolved_contracts_b1v3_canonical_spot_v1.json"
    assert args.inventory == Path(
        "D:/MDS650/b1v3_confirmation/evidence/b1q_raw_payload_inventory.parquet"
    )
    assert args.manifest.name == "b1q_source_manifest.json"
    assert args.schema.name == "b1v3-confirmation-b1q-source-v1.schema.json"
