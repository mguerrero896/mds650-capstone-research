"""Smoke tests for Phase 7 diagnostic and preregistration CLIs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_b1_independent_replication_timing as timing_cli  # noqa: E402
import prepare_b1_independent_replication_access as access_cli  # noqa: E402


@pytest.mark.parametrize(
    "script_name",
    [
        "plan_b1_independent_replication.py",
        "run_b1_diagnostics.py",
        "run_b1_independent_replication_provider_preflight.py",
        "run_b1_replication_market_control_preflight.py",
        "build_b1_independent_replication_base.py",
        "build_b1_replication_fmp_delay2.py",
        "acquire_b1_independent_replication_b1q.py",
        "seal_b1_independent_replication_b1q_source.py",
        "build_b1_independent_replication_b1v3.py",
        "build_b1_independent_replication_b2.py",
        "build_b1_independent_replication_common_panel.py",
        "build_b1_independent_replication_timing.py",
        "prepare_b1_independent_replication_access.py",
        "run_b1_independent_replication_once.py",
        "freeze_b1_independent_replication_method.py",
    ],
)
def test_phase7_cli_help_is_executable(script_name: str) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script_name), "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--output-root" in completed.stdout


def test_access_cli_consumes_the_acquisition_manifest_at_its_canonical_path() -> None:
    args = access_cli._arguments([])

    assert args.full_tape_manifest == (
        ROOT / "artifacts/b1_diagnostic_replication/acquisition/full_tape_acquisition_manifest.json"
    )


def test_timing_cli_can_resume_from_sealed_predictors(tmp_path: Path) -> None:
    roots = (
        tmp_path / "fmp_delay_2",
        tmp_path / "massive/cutoff_60",
        tmp_path / "massive/cutoff_300",
    )
    for root in roots:
        for relative in (
            "attempts.parquet",
            "derived_source_manifest.json",
            "features/b1v3_features.parquet",
            "features/b1v3_coverage.json",
            "features/b1v3_manifest.json",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"sealed")

    variants = timing_cli._existing_variant_paths(tmp_path)

    assert set(variants) == {
        "FMP_DELAY_2_MINUTES",
        "MASSIVE_CUTOFF_60_SECONDS",
        "MASSIVE_CUTOFF_300_SECONDS",
    }
    assert timing_cli._arguments(["--resume-from-timing-predictors"]).resume_from_timing_predictors
