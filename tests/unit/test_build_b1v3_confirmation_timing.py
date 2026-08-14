"""Source-binding and idempotence tests for B1v3 timing predictors."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import polars as pl

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_b1v3_confirmation_timing as timing_script  # noqa: E402
from build_b1v3_confirmation_timing import (  # noqa: E402
    _arguments,
    build_timing_predictor_package,
)


def test_cli_defaults_keep_heavy_outputs_on_b1v3_data_root() -> None:
    args = _arguments([])

    assert args.primary_attempts.name == "b1_iv_attempts_20d.parquet"
    assert args.output_root == Path("D:/MDS650/b1v3_confirmation/predictors/timing")
    assert args.timing_schema.name == (
        "b1v3-confirmation-timing-predictors-v1.schema.json"
    )
    assert args.minimum_free_gib == 80.0


def test_timing_package_is_source_bound_schema_valid_and_idempotent(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    primary = tmp_path / "primary.parquet"
    inventory = tmp_path / "inventory.parquet"
    origins = tmp_path / "origins.parquet"
    bars = tmp_path / "bars.parquet"
    design = tmp_path / "design.md"
    source_manifest = tmp_path / "source.json"
    base_manifest = tmp_path / "base.json"
    for path in (primary, inventory, design, source_manifest, base_manifest):
        path.write_bytes(b"source")
    pl.DataFrame({"origin_id": ["AAPL:1"]}).write_parquet(origins)
    pl.DataFrame({"asset": ["AAPL"]}).write_parquet(bars)
    fake_source = {
        "plan_sha256": "1" * 64,
        "manifest_sha256": "2" * 64,
    }
    fake_base = {
        "plan_sha256": "1" * 64,
        "manifest_sha256": "3" * 64,
    }
    monkeypatch.setattr(
        timing_script,
        "_validate_sources",
        lambda **_kwargs: (fake_source, fake_base),
    )
    monkeypatch.setattr(
        timing_script,
        "build_spot_frame",
        lambda *_args, **_kwargs: pl.DataFrame(
            {"origin_id": ["AAPL:1"], "spot": [100.0], "spot_available": [True]}
        ),
    )
    monkeypatch.setattr(
        timing_script,
        "build_b0_target_blind",
        lambda *_args, **_kwargs: pl.DataFrame(
            {"origin_id": ["AAPL:1"], "b0_complete": [True]}
        ),
    )
    writer_calls = {"fmp": 0, "massive": 0}

    def fake_fmp_writer(*, output_path: Path, **_kwargs: object) -> dict[str, object]:
        writer_calls["fmp"] += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fmp-attempts")
        return {
            "status": "PASS_TARGET_BLIND_FMP_DELAY_REPRICING",
            "attempt_count": 2,
            "origin_count": 1,
        }

    def fake_massive_writer(
        *, output_paths: dict[int, Path], **_kwargs: object
    ) -> dict[str, object]:
        writer_calls["massive"] += 1
        for cutoff, path in output_paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"massive-{cutoff}".encode())
        return {
            "status": "PASS_TARGET_BLIND_MASSIVE_MULTI_RESELECTION",
            "attempt_count": 2,
            "cache_decode_count": 1,
            "variants": {"60": {"cutoff_seconds": 60}, "300": {"cutoff_seconds": 300}},
        }

    def fake_build(*, output_root: Path, **_kwargs: object) -> Any:
        output_root.mkdir(parents=True, exist_ok=True)
        features = output_root / "b1v3_features.parquet"
        coverage = output_root / "b1v3_coverage.json"
        manifest = output_root / "b1v3_manifest.json"
        features.write_bytes(b"features")
        coverage.write_bytes(b"coverage")
        manifest.write_bytes(b"manifest")
        return timing_script.BuildArtifacts(
            features_path=features,
            coverage_path=coverage,
            manifest_path=manifest,
            features_sha256="4" * 64,
            coverage_sha256="5" * 64,
            manifest_sha256="6" * 64,
        )

    monkeypatch.setattr(timing_script, "write_fmp_delayed_attempts", fake_fmp_writer)
    monkeypatch.setattr(
        timing_script,
        "write_massive_reselected_attempt_variants",
        fake_massive_writer,
    )
    monkeypatch.setattr(timing_script, "build_target_blind_package", fake_build)
    output_root = tmp_path / "timing"
    manifest = tmp_path / "artifacts" / "timing.json"
    schema = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "001-pit-options-rv30"
        / "contracts"
        / "b1v3-confirmation-timing-predictors-v1.schema.json"
    )
    kwargs = {
        "primary_attempts_path": primary,
        "cache_root": tmp_path,
        "source_manifest_path": source_manifest,
        "source_manifest_schema_path": tmp_path / "source-schema.json",
        "source_inventory_path": inventory,
        "base_manifest_path": base_manifest,
        "base_manifest_schema_path": tmp_path / "base-schema.json",
        "origins_path": origins,
        "fmp_bars_path": bars,
        "design_path": design,
        "target_blind_manifest_schema_path": tmp_path / "technical-schema.json",
        "timing_manifest_schema_path": schema,
        "output_root": output_root,
        "manifest_path": manifest,
        "minimum_free_gib": 0.0,
        "batch_size": 1,
    }

    first = build_timing_predictor_package(**kwargs)
    first_bytes = manifest.read_bytes()
    second = build_timing_predictor_package(**kwargs)

    assert first == second
    assert manifest.read_bytes() == first_bytes
    assert writer_calls == {"fmp": 1, "massive": 1}
    assert first["status"] == "PASS_TARGET_BLIND_TIMING_PREDICTORS"
    assert first["outcome_read_count"] == 0
    assert first["safe_to_read_outcomes"] is False
    assert set(first["variants"]) == {
        "FMP_DELAY_2_MINUTES",
        "MASSIVE_CUTOFF_60_SECONDS",
        "MASSIVE_CUTOFF_300_SECONDS",
    }
    assert "C:\\Users\\" not in json.dumps(first)
    assert "D:\\MDS650" not in json.dumps(first)
