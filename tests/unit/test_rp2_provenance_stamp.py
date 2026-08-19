"""The provenance stamper: a sidecar that fails loudly when an input has moved.

A provenance record is only worth writing if something re-reads it. These pin the
re-reading path, including the JSON round trip that a naive `InputRecord(**record)` gets
wrong (a tuple of column names comes back as a list).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "rp2_provenance_stamp", REPO / "scripts" / "rp2_provenance_stamp.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAMP = _load()


def test_every_declared_input_names_a_known_provider() -> None:
    from mds650.rp2.provenance import KNOWN_PROVIDERS

    unknown = [
        (block, provider)
        for block, inputs in STAMP.BLOCK_INPUTS.items()
        for _, _, provider, _ in inputs
        if provider not in KNOWN_PROVIDERS
    ]
    assert not unknown, f"inputs claiming a provider the contract does not know: {unknown}"


def test_every_declared_input_path_is_under_artifacts() -> None:
    """A stamper pointed outside the artifact tree would record a file nobody can reproduce."""

    stray = [
        (block, relative)
        for block, inputs in STAMP.BLOCK_INPUTS.items()
        for _, relative, _, _ in inputs
        if not relative.startswith("artifacts/")
    ]
    assert not stray


def test_an_indirect_input_explains_why_it_is_not_content_hashed() -> None:
    """A weaker guarantee has to say it is weaker, or it reads as a byte hash."""

    for name, reason in STAMP.INDIRECT.items():
        assert name and len(reason) > 40, f"{name} is pinned indirectly with no stated reason"


def test_a_round_tripped_record_verifies_and_a_mutated_input_does_not(tmp_path: Path) -> None:
    from mds650.rp2.provenance import describe_input, provenance_block, verify_inputs

    panel = tmp_path / "panel.parquet"
    pl.DataFrame({"session_date": ["2025-01-02"], "value": [1.0]}).write_parquet(panel)
    record = describe_input(panel, provider="derived", time_column="session_date")
    payload = provenance_block({"panel": record}, run_id="r", code_commit=None)

    reread = STAMP._record(json.loads(json.dumps(payload))["inputs"]["panel"])
    assert reread.columns == ("session_date", "value")
    assert verify_inputs({"panel": reread}) == []

    pl.DataFrame({"session_date": ["2025-01-02"], "value": [2.0]}).write_parquet(panel)
    assert verify_inputs({"panel": reread}) == ["panel"]


def test_describing_a_panel_records_its_span_without_loading_it(tmp_path: Path) -> None:
    from mds650.rp2.provenance import describe_input

    panel = tmp_path / "panel.parquet"
    pl.DataFrame(
        {"session_date": ["2025-01-02", "2025-03-04", "2025-02-01"], "value": [1.0, 2.0, 3.0]}
    ).write_parquet(panel)
    record = describe_input(panel, provider="derived", time_column="session_date")
    assert record.rows == 3
    assert record.time_min == "2025-01-02" and record.time_max == "2025-03-04"


def test_an_unknown_block_is_refused_rather_than_silently_skipped() -> None:
    with pytest.raises(SystemExit, match="RP2_PROVENANCE_UNKNOWN_BLOCK"):
        STAMP.main(["--blocks", "rp2_block99_imaginary"])


def test_verifying_a_block_with_no_sidecar_reports_it_rather_than_passing() -> None:
    assert STAMP.verify("rp2_block99_missing") == ["rp2_block99_missing:NO_PROVENANCE"]
