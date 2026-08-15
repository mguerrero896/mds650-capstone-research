"""Contract tests for the sign-agnostic independent-replication method freeze."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.b1v3_evaluation import b1v3_information_sets, b1v3_method_contract

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import freeze_b1_independent_replication_method as freeze  # noqa: E402


def _dates(start: datetime, count: int) -> list[str]:
    return [(start + timedelta(days=offset)).date().isoformat() for offset in range(count)]


def _preregistration() -> dict[str, Any]:
    training = _dates(datetime(2024, 1, 1, tzinfo=UTC), 60)
    replication = _dates(datetime(2024, 4, 1, tzinfo=UTC), 30)
    document: dict[str, Any] = {
        "schema_version": "b1-independent-replication-preregistration-1.0",
        "status": "FROZEN_BEFORE_PROVIDER_PAYLOAD",
        "target_blind": True,
        "replication_target_reads": 0,
        "safe_to_access_replication_targets": "NO",
        "result_sign_selection": "PROHIBITED",
        "training_sessions": training,
        "replication_sessions": replication,
        "information_sets": {
            name: list(features) for name, features in b1v3_information_sets().items()
        },
        "method": b1v3_method_contract(),
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def _training_panel(document: dict[str, Any]) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    assets = ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA")
    for index, session in enumerate(document["training_sessions"]):
        for asset in assets:
            row: dict[str, Any] = {
                "origin_id": f"{asset}:{session}:001",
                "asset": asset,
                "session_date": session,
                "forecast_origin_utc": datetime(2024, 1, 1, 15, tzinfo=UTC)
                + timedelta(days=index),
                "session_tercile": "middle",
                "rv30": 0.001,
            }
            for feature in document["information_sets"]["B2"]:
                row[feature] = asset if feature == "b0v2_asset_identity" else 0.1
            rows.append(row)
    return pl.DataFrame(rows)


def _patch_training_algorithms(monkeypatch: Any) -> None:
    oof = pl.DataFrame(
        {
            "origin_id": ["AAPL:2024-01-01:001"],
            "information_set": ["B0"],
            "qlike_loss": [0.1],
        }
    )
    monkeypatch.setattr(
        freeze,
        "training_only_b1v3_oof_forecasts",
        lambda _panel, _adapter: (oof, [{"variant_id": "oof"}]),
    )
    selected = {
        role: {
            information_set: {"alpha": 0.1}
            for information_set in ("B0", "B1v3a", "B2")
        }
        for role in ("gamma_glm_confirmatory", "lightgbm_robustness")
    }
    monkeypatch.setattr(
        freeze,
        "select_b1v3_final_parameters",
        lambda _panel, _adapter: (selected, [{"variant_id": "final"}]),
    )
    monkeypatch.setattr(
        freeze,
        "training_mde_from_b1v3_forecasts",
        lambda _frame, *, draws, seed: {"delta_b1v3": 0.01, "delta_b2": 0.02},
    )
    monkeypatch.setattr(
        freeze,
        "training_volatility_regime_cutpoints",
        lambda _panel: {"lower": 0.1, "upper": 0.2},
    )


def test_freeze_is_target_blind_sign_agnostic_and_idempotent(
    tmp_path: Path, monkeypatch: Any
) -> None:
    document = _preregistration()
    preregistration = tmp_path / "preregistration.json"
    preregistration.write_text(json.dumps(document), encoding="utf-8")
    panel = tmp_path / "training.parquet"
    _training_panel(document).write_parquet(panel)
    _patch_training_algorithms(monkeypatch)

    arguments = {
        "preregistration_path": preregistration,
        "training_panel_path": panel,
        "output_root": tmp_path / "method",
        "artifact_root": tmp_path / "artifacts",
        "schema_path": ROOT
        / "specs/001-pit-options-rv30/contracts/"
        "b1-independent-replication-method-freeze-v1.schema.json",
    }
    first = freeze.freeze_method(**arguments)
    second = freeze.freeze_method(**arguments)

    assert first == second
    assert first["status"] == "FROZEN_AFTER_TRAINING_BEFORE_REPLICATION"
    assert first["replication_target_read_count"] == 0
    assert first["result_sign_selection"] == "PROHIBITED"
    assert first["training_mde"] == {"delta_b1v3": 0.01, "delta_b2": 0.02}
    assert first["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in first.items() if key != "manifest_sha256"}
    )


def test_freeze_rejects_sign_selection(tmp_path: Path) -> None:
    document = _preregistration()
    document["result_sign_selection"] = "POSITIVE_ONLY"
    document["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    )
    preregistration = tmp_path / "preregistration.json"
    preregistration.write_text(json.dumps(document), encoding="utf-8")

    try:
        freeze.freeze_method(
            preregistration_path=preregistration,
            training_panel_path=tmp_path / "missing.parquet",
            output_root=tmp_path / "method",
            artifact_root=tmp_path / "artifacts",
            schema_path=tmp_path / "schema.json",
        )
    except ValueError as exc:
        assert str(exc) == "B1_REPLICATION_METHOD_PREREGISTRATION_INVALID"
    else:
        raise AssertionError("sign-selective preregistration was accepted")
