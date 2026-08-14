"""CLI defaults for the source-bound B1v3 confirmation feature build."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from build_b1v3_confirmation_b1 import _arguments  # noqa: E402


def test_cli_uses_exact_source_binding_and_new_output_root() -> None:
    args = _arguments([])

    assert args.input.name == "b1_iv_attempts_20d.parquet"
    assert args.source_binding_manifest.name == "b1q_source_manifest.json"
    assert args.source_binding_schema.name == (
        "b1v3-confirmation-b1q-source-v1.schema.json"
    )
    assert args.source_inventory.name == "b1q_raw_payload_inventory.parquet"
    assert args.output_root == Path(
        "D:/MDS650/b1v3_confirmation/predictors/b1v3_source_bound"
    )
    assert args.manifest_schema.name == (
        "b1v3-target-blind-source-bound-manifest-v2.schema.json"
    )
