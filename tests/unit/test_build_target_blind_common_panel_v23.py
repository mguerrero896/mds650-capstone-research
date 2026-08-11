"""Tests for the hardened v2.3 target-blind panel builder shell."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
builder = importlib.import_module("build_target_blind_common_panel_v23")


def test_v23_defaults_bind_promoted_evidence_records() -> None:
    """The command defaults must use the promoted Massive artifact and both gates."""
    args = builder.parse_args([])

    assert args.massive_reselection.name == (
        "massive_reselection_sensitivity_v21_recomputed_20260812.json"
    )
    assert args.availability_manifest.name == "b2_availability_manifest_v22.json"
    assert args.reconciliation_gate.name == "pit_reconciliation_gate_v21_20260812.json"
    assert args.output_root.as_posix().endswith("target_blind_v23_sourcebound_20260812")


def test_v23_writer_retains_identical_bytes_and_rejects_drift(tmp_path: Path) -> None:
    """Derived files are immutable: identical replays pass and drift fails closed."""
    path = tmp_path / "derived.bin"

    builder.write_if_new_or_identical(path, lambda temporary: temporary.write_bytes(b"same"))
    builder.write_if_new_or_identical(path, lambda temporary: temporary.write_bytes(b"same"))

    with pytest.raises(
        FileExistsError, match="TARGET_BLIND_V23_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"
    ):
        builder.write_if_new_or_identical(path, lambda temporary: temporary.write_bytes(b"drift"))
    assert path.read_bytes() == b"same"
    assert not list(tmp_path.glob("*.part"))


def test_v23_refuses_to_build_from_uncommitted_builder_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manifest must not name a clean commit while its builder is dirty."""

    class Completed:
        """Minimum completed-process record for the local Git status call."""

        stdout = " M src/mds650/target_blind_panel_v22.py\n"

    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: Completed())

    with pytest.raises(ValueError, match="TARGET_BLIND_V23_BUILDER_SOURCE_UNCOMMITTED"):
        builder.require_committed_builder_source()


def test_v23_accepts_clean_builder_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unrelated worktree changes do not prevent a committed builder replay."""

    class Completed:
        """Minimum completed-process record for a clean scoped Git status call."""

        stdout = ""

    monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: Completed())

    builder.require_committed_builder_source()


def test_v23_committed_source_guard_covers_transitive_runtime_dependencies() -> None:
    """Every local module or lockfile used by the v2.3 execution is guarded."""
    expected = {
        "scripts/build_target_blind_common_panel_v22.py",
        "src/mds650/phase6.py",
        "src/mds650/provider_timing_v21.py",
        "pyproject.toml",
        "uv.lock",
    }

    assert expected <= set(builder._BUILDER_SOURCE_PATHS)


def test_v23_source_commit_is_pinned_to_runtime_source_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Artefact commits cannot change the commit identity of an unchanged builder."""
    calls: list[list[str]] = []

    class Completed:
        """Minimum completed-process record for the local Git history call."""

        stdout = "a" * 40 + "\n"

    def fake_run(args: list[str], **_: object) -> Completed:
        calls.append(args)
        return Completed()

    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    assert builder._source_commit() == "a" * 40
    assert calls == [["git", "log", "-1", "--format=%H", "--", *builder._BUILDER_SOURCE_PATHS]]


def test_v23_manifest_schema_preserves_closed_evaluation_boundary(tmp_path: Path) -> None:
    """A generated v2.3 manifest must retain its no-OOS and no-reconciliation gates."""
    panel_path = tmp_path / "panel.parquet"
    common_path = tmp_path / "common.parquet"
    panel_path.write_bytes(b"panel")
    common_path.write_bytes(b"common")
    summary = {
        "schema_version": "target-blind-common-predictor-panel-v2.2",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "scope": "offline_target_blind_predictor_construction_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "row_count": 1,
        "completion_counts": {"common_predictor_complete": 1},
        "completion_rates": {"common_predictor_complete": 1.0},
    }
    provenance_hashes = {
        "origins_sha256": "0" * 64,
        "b2_availability_sidecar_sha256": "1" * 64,
        "massive_reselection_recomputed_v21_sha256": "2" * 64,
        "b2_availability_manifest_v22_sha256": "3" * 64,
        "pit_reconciliation_gate_v21_sha256": "4" * 64,
    }
    source_hashes = {
        "fmp_bars_sha256": "5" * 64,
        "b1q_source_sha256": "6" * 64,
        "b2_primary_inputs_sha256": "7" * 64,
    }
    manifest = builder._build_manifest(
        panel=pl.DataFrame({"origin_id": ["AAPL-1"]}),
        common=pl.DataFrame({"origin_id": ["AAPL-1"]}),
        panel_path=panel_path,
        common_path=common_path,
        provenance_hashes=provenance_hashes,
        source_hashes=source_hashes,
        summary=summary,
    )
    manifest["output_locations"] = {
        "panel": "D:/MDS650/test/panel.parquet",
        "common_complete": "D:/MDS650/test/common.parquet",
    }

    builder._validate_output_manifest(manifest, builder.OUTPUT_MANIFEST_SCHEMA)
    manifest["SAFE_TO_OPEN_OR_EVALUATE_OOS"] = "YES"

    with pytest.raises(ValueError, match="TARGET_BLIND_V23_OUTPUT_MANIFEST_SCHEMA_VIOLATION"):
        builder._validate_output_manifest(manifest, builder.OUTPUT_MANIFEST_SCHEMA)
