"""Unit contracts for target-blind B1v3 B2 confirmation construction."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema
import polars as pl
import pytest

import mds650.b1v3_b2_confirmation as b2_module
from mds650.b1v3_b2_confirmation import (
    B2_CONFIRMATION_VARIANTS,
    FullTapeContract,
    _build_raw_matrices,
    _combine_variant,
    _load_event_partition,
    _partition_index,
    _safe_partition_path,
    build_b2_confirmation_artifacts,
    load_full_tape_contract,
)
from mds650.b1v3_confirmation import canonical_sha256, sha256_file
from mds650.b1v3_confirmation_build import B1V3_CANONICAL_ASSETS, FrozenBuildInputs

ROOT = Path(__file__).resolve().parents[2]
ACQUISITION_SCHEMA = (
    ROOT
    / "specs/001-pit-options-rv30/contracts/"
    "b1v3-full-tape-acquisition-manifest-v1.schema.json"
)
B2_SCHEMA = (
    ROOT
    / "specs/001-pit-options-rv30/contracts/"
    "b1v3-confirmation-b2-predictors-v1.schema.json"
)


def _sessions() -> tuple[str, ...]:
    first = date(2024, 1, 1)
    return tuple((first + timedelta(days=offset)).isoformat() for offset in range(90))


def _frozen_inputs() -> FrozenBuildInputs:
    sessions = _sessions()
    return FrozenBuildInputs(
        plan_sha256="a" * 64,
        report_sha256="b" * 64,
        provider_candidate_plan_sha256="c" * 64,
        source_confirmation_plan_sha256="d" * 64,
        training_sessions=sessions[:60],
        confirmation_sessions=sessions[60:],
        fmp_records=(),
    )


def _session_record(session_date: str, plan_sha256: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "status": "PASS",
        "session_date": session_date,
        "source_kind": "AUTHENTICATED_DOWNLOAD",
        "completed_at_utc": "2026-08-14T00:00:00Z",
        "confirmation_plan_sha256": plan_sha256,
        "session_contract_sha256": canonical_sha256(
            {
                "session_date": session_date,
                "confirmation_plan_sha256": plan_sha256,
            }
        ),
        "raw_sha256": "e" * 64,
        "raw_bytes": 1,
        "http_status": 200,
        "request_id": None,
        "request_endpoint": "/api/option-trades/full-tape/{date}",
        "download_attempts": 1,
        "download_seconds": 0.1,
        "reused_raw_archive": False,
        "schema_fields": ["created_at", "executed_at"],
        "schema_fingerprint": "f" * 64,
        "rows_seen": 1,
        "rows_retained": 1,
        "duplicate_event_ids": 0,
        "parquet_bytes": 1,
        "filter_seconds": 0.1,
        "parquet_files": [
            {
                "relative_path": (
                    f"data/option_events/date={session_date}/asset=AAPL/events.parquet"
                ),
                "bytes": 1,
                "sha256": "1" * 64,
            }
        ],
        "raw_location": "MDS650_B1V3_DATA_ROOT/raw/full_tape",
        "derived_location": "MDS650_B1V3_DATA_ROOT/data/option_events",
        "target_outcome_read": False,
        "oos_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    record["checkpoint_sha256"] = canonical_sha256(record)
    return record


def _acquisition_manifest(inputs: FrozenBuildInputs) -> dict[str, Any]:
    records = [_session_record(day, inputs.plan_sha256) for day in inputs.all_sessions]
    document: dict[str, Any] = {
        "schema_version": "b1v3-full-tape-acquisition-1.0",
        "status": "PASS",
        "target_blind": True,
        "confirmation_plan_sha256": inputs.plan_sha256,
        "authorized_session_count": 90,
        "completed_session_count": 90,
        "pending_session_count": 0,
        "pending_sessions": [],
        "sessions": records,
        "raw_location": "MDS650_B1V3_DATA_ROOT/raw/full_tape",
        "derived_location": "MDS650_B1V3_DATA_ROOT/data/option_events",
        "target_outcome_read": False,
        "oos_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    document["manifest_sha256"] = canonical_sha256(document)
    return document


def test_load_full_tape_contract_requires_schema_hash_and_complete_scope(tmp_path: Path) -> None:
    inputs = _frozen_inputs()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_acquisition_manifest(inputs)), encoding="utf-8")

    contract = load_full_tape_contract(
        path,
        frozen_inputs=inputs,
        manifest_schema_path=ACQUISITION_SCHEMA,
    )

    assert contract.manifest_sha256
    assert tuple(sorted(contract.session_records)) == inputs.all_sessions

    tampered = _acquisition_manifest(inputs)
    tampered["manifest_sha256"] = "2" * 64
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="B1V3_B2_ACQUISITION_MANIFEST_HASH_INVALID"):
        load_full_tape_contract(
            path,
            frozen_inputs=inputs,
            manifest_schema_path=ACQUISITION_SCHEMA,
        )


def test_load_full_tape_contract_rejects_tampered_session_checkpoint(tmp_path: Path) -> None:
    inputs = _frozen_inputs()
    document = _acquisition_manifest(inputs)
    document["sessions"][0]["raw_sha256"] = "3" * 64
    document["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="B1V3_B2_ACQUISITION_SESSION_INVALID"):
        load_full_tape_contract(
            path,
            frozen_inputs=inputs,
            manifest_schema_path=ACQUISITION_SCHEMA,
        )


def test_load_full_tape_contract_rejects_wrong_session_contract(tmp_path: Path) -> None:
    inputs = _frozen_inputs()
    document = _acquisition_manifest(inputs)
    document["sessions"][0]["session_contract_sha256"] = "4" * 64
    row = document["sessions"][0]
    row["checkpoint_sha256"] = canonical_sha256(
        {key: value for key, value in row.items() if key != "checkpoint_sha256"}
    )
    document["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="B1V3_B2_ACQUISITION_SESSION_INVALID"):
        load_full_tape_contract(
            path,
            frozen_inputs=inputs,
            manifest_schema_path=ACQUISITION_SCHEMA,
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        "events.parquet",
        "../events.parquet",
        "data/other/date=2024-01-02/asset=AAPL/events.parquet",
        "data/option_events/date=2024-01-02/asset=AAPL/not-events.parquet",
    ],
)
def test_partition_path_guard_rejects_ambiguous_or_escaping_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    with pytest.raises(ValueError, match="B1V3_B2_PARTITION_PATH_INVALID"):
        _safe_partition_path(tmp_path, relative_path)


def _event_frame(asset: str, origin: datetime) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "underlying_symbol": [asset, asset],
            "option_chain_id": [f"{asset}-OLD", f"{asset}-RECENT"],
            "executed_at": [
                origin - timedelta(minutes=5, seconds=30),
                origin - timedelta(minutes=2),
            ],
            "created_at": [
                origin - timedelta(minutes=5, seconds=20),
                origin - timedelta(minutes=1, seconds=30),
            ],
            "premium": [1000.0, 2000.0],
            "option_type": ["call", "put"],
            "tags": ["ask_side", "bid_side"],
            "strike": [100.0, 101.0],
            "expiry": ["2024-02-16", "2024-02-16"],
        }
    )


def test_raw_b2_builder_preserves_origins_and_applies_each_frozen_cutoff(
    tmp_path: Path,
) -> None:
    day = "2024-01-02"
    origin = datetime(2024, 1, 2, 14, 40, tzinfo=UTC)
    origins = pl.DataFrame(
        {
            "origin_id": [f"{asset}:{day}:14:40" for asset in B1V3_CANONICAL_ASSETS],
            "asset": list(B1V3_CANONICAL_ASSETS),
            "session_date": [day] * len(B1V3_CANONICAL_ASSETS),
            "forecast_origin_utc": [origin] * len(B1V3_CANONICAL_ASSETS),
        }
    )
    index: dict[tuple[str, str], tuple[Path, str]] = {}
    for asset in B1V3_CANONICAL_ASSETS:
        path = tmp_path / f"{asset}.parquet"
        _event_frame(asset, origin).write_parquet(path)
        index[(day, asset)] = (path, sha256_file(path))

    outputs = _build_raw_matrices(
        origins=origins,
        partition_index=index,
        output_root=tmp_path / "raw",
        sessions=(day,),
    )

    assert set(outputs) == set(B2_CONFIRMATION_VARIANTS)
    counts: dict[str, set[float]] = {}
    for variant, paths in outputs.items():
        assert len(paths) == 1
        frame = pl.read_parquet(paths[0])
        assert frame.height == len(B1V3_CANONICAL_ASSETS)
        assert frame["origin_id"].n_unique() == frame.height
        assert not frame.filter(
            pl.col("b2v2_max_created_at_utc") > pl.col("b2v2_cutoff_utc")
        ).height
        counts[variant] = set(frame["option_trade_count_5m"].to_list())
    assert counts == {
        "primary_5m_60s": {2.0},
        "latency_5m_120s": {1.0},
        "latency_5m_300s": {1.0},
    }


def test_event_partition_rejects_symbol_mismatch(tmp_path: Path) -> None:
    origin = datetime(2024, 1, 2, 14, 40, tzinfo=UTC)
    path = tmp_path / "events.parquet"
    _event_frame("MSFT", origin).write_parquet(path)

    with pytest.raises(ValueError, match="B1V3_B2_PARTITION_CONTENT_INVALID"):
        _load_event_partition(
            path,
            asset="AAPL",
            session_date="2024-01-02",
            expected_hash=sha256_file(path),
        )


def test_partition_index_requires_all_six_canonical_assets(tmp_path: Path) -> None:
    day = "2024-01-02"
    files: list[dict[str, Any]] = []
    for asset in B1V3_CANONICAL_ASSETS:
        relative = f"data/option_events/date={day}/asset={asset}/events.parquet"
        path = tmp_path / Path(*Path(relative).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(asset.encode())
        files.append(
            {
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": "a" * 64,
            }
        )
    contract = FullTapeContract("b" * 64, {day: {"parquet_files": files}})

    index = _partition_index(contract, data_root=tmp_path)

    assert set(index) == {(day, asset) for asset in B1V3_CANONICAL_ASSETS}

    contract_missing = FullTapeContract(
        "b" * 64,
        {day: {"parquet_files": files[:-1]}},
    )
    with pytest.raises(ValueError, match="B1V3_B2_PARTITION_SCOPE_INVALID"):
        _partition_index(contract_missing, data_root=tmp_path)


def test_corrected_variant_masks_ineligible_feature_values_and_is_idempotent(
    tmp_path: Path,
) -> None:
    origin = datetime(2024, 1, 2, 14, 40, tzinfo=UTC)
    canonical = pl.DataFrame(
        {
            "origin_id": ["AAPL:1"],
            "asset": ["AAPL"],
            "session_date": ["2024-01-02"],
            "forecast_origin_utc": [origin],
            "b2v2_max_created_at_utc": [origin - timedelta(seconds=61)],
            "b2v2_cutoff_utc": [origin - timedelta(seconds=60)],
            **{name: [1.0] for name in b2_module.B2_FEATURE_NAMES},
        }
    )
    raw_path = tmp_path / "raw.parquet"
    canonical.write_parquet(raw_path)
    sidecar = pl.DataFrame(
        {
            "canonical_variant": ["primary_5m_60s"],
            "origin_id": ["AAPL:1"],
            "row_status": ["PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES"],
            "eligible_for_corrected_pit_panel": [False],
            "source_temporal_state": ["RECORD_CREATION_DELAY_OBSERVED"],
        }
    )
    destination = tmp_path / "corrected.parquet"

    first, first_hash = _combine_variant(
        [raw_path],
        sidecar=sidecar,
        variant="primary_5m_60s",
        destination=destination,
    )
    second, second_hash = _combine_variant(
        [raw_path],
        sidecar=sidecar,
        variant="primary_5m_60s",
        destination=destination,
    )

    assert first.equals(second, null_equal=True)
    assert first_hash == second_hash
    assert all(first[name].null_count() == 1 for name in b2_module.B2_FEATURE_NAMES)
    assert first["b2v2_availability_eligible"].to_list() == [False]


def test_target_blind_b2_artifact_build_seals_exact_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _frozen_inputs()
    origin_ids = [f"origin-{index:05d}" for index in range(38_664)]
    origins = pl.DataFrame({"origin_id": origin_ids})
    origins_path = tmp_path / "origins.parquet"
    origins.write_parquet(origins_path)
    base: dict[str, Any] = {
        "status": "PASS_TARGET_BLIND_BASE_PREDICTORS",
        "plan_sha256": inputs.plan_sha256,
        "outcome_read_count": 0,
        "safe_to_read_outcomes": False,
        "outputs": {"origins": {"sha256": sha256_file(origins_path)}},
    }
    base["manifest_sha256"] = canonical_sha256(base)
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(base), encoding="utf-8")
    raw_paths = {
        variant: (tmp_path / f"{variant}.parquet",)
        for variant in B2_CONFIRMATION_VARIANTS
    }
    corrected = pl.DataFrame(
        {
            "origin_id": origin_ids,
            "b2v2_availability_eligible": [True] * len(origin_ids),
        }
    )
    sidecar = pl.DataFrame(
        {"eligible_for_corrected_pit_panel": [True] * (38_664 * 3)}
    )
    variant_totals = [
        {
            "canonical_variant": variant,
            "row_count": 38_664,
            "eligible_row_count": 38_664,
            "excluded_row_count": 0,
        }
        for variant in sorted(B2_CONFIRMATION_VARIANTS)
    ]
    availability = {
        "schema_version": "2.2",
        "row_count": 115_992,
        "eligible_row_count": 115_992,
        "excluded_row_count": 0,
        "primary_delayed_raw_zero_exclusion_count": 0,
        "canonical_raw_count_mismatch_count": 0,
        "row_status_counts": {"PIT_USABLE_ELIGIBLE_ACTIVITY": 115_992},
        "variant_totals": variant_totals,
    }
    monkeypatch.setattr(b2_module, "_partition_index", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        b2_module,
        "_build_raw_matrices",
        lambda **_kwargs: raw_paths,
    )
    monkeypatch.setattr(
        b2_module,
        "audit_uw_session_asset_incidents",
        lambda **_kwargs: [{"incident": "none"}],
    )
    monkeypatch.setattr(
        b2_module,
        "audit_b2_canonical_traceability",
        lambda **_kwargs: ([{"trace": "bound"}], "PASS_NO_CONFOUNDED_ZERO_OBSERVED"),
    )
    monkeypatch.setattr(
        b2_module,
        "build_b2_availability_sidecar",
        lambda **_kwargs: (sidecar, availability),
    )

    def fake_combine(
        _paths: object,
        *,
        sidecar: pl.DataFrame,
        variant: str,
        destination: Path,
    ) -> tuple[pl.DataFrame, str]:
        del sidecar, variant
        return corrected, b2_module._write_parquet_if_identical(corrected, destination)

    monkeypatch.setattr(b2_module, "_combine_variant", fake_combine)
    output_root = tmp_path / "outputs"
    manifest_path = tmp_path / "b2_manifest.json"
    contract = FullTapeContract("e" * 64, {})

    first = build_b2_confirmation_artifacts(
        frozen_inputs=inputs,
        full_tape_contract=contract,
        base_manifest_path=base_path,
        origins_path=origins_path,
        data_root=tmp_path,
        event_root=tmp_path,
        output_root=output_root,
        manifest_path=manifest_path,
        manifest_schema_path=B2_SCHEMA,
    )
    second = build_b2_confirmation_artifacts(
        frozen_inputs=inputs,
        full_tape_contract=contract,
        base_manifest_path=base_path,
        origins_path=origins_path,
        data_root=tmp_path,
        event_root=tmp_path,
        output_root=output_root,
        manifest_path=manifest_path,
        manifest_schema_path=B2_SCHEMA,
    )

    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(B2_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)
    stored_hash = document.pop("manifest_sha256")
    assert stored_hash == canonical_sha256(document)
    assert first.manifest_file_sha256 == second.manifest_file_sha256
    assert document["outcome_read_count"] == 0
    assert document["safe_to_read_outcomes"] is False
    assert all(
        row["eligible_row_count"] + row["excluded_row_count"] == row["row_count"]
        for row in document["variants"].values()
    )


def test_b2_manifest_schema_is_valid_and_freezes_three_variants() -> None:
    schema = json.loads(B2_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    assert set(schema["properties"]["variants"]["required"]) == set(
        B2_CONFIRMATION_VARIANTS
    )
    assert len(schema["properties"]["features"]["prefixItems"]) == 9
    assert b2_module.B2_CONFIRMATION_VARIANTS["primary_5m_60s"] == 60
