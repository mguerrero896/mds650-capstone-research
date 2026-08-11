"""TDD coverage for the v2.4 source-bound, target-blind panel guard."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator

from mds650.target_blind_panel_v22 import (
    B0V2_FEATURES,
    B1V2A_FEATURES,
    B1V2B_FEATURES,
    B1V2C_FEATURES,
    B2V2_FEATURES,
    KEY_COLUMNS,
)
from mds650.target_blind_sourcebound_v24 import (
    B0_ALLOWED_COLUMNS,
    B1_ALLOWED_COLUMNS,
    B2_ALLOWED_COLUMNS,
    PANEL_ALLOWED_COLUMNS,
    assert_preflight_hashes_unchanged_v24,
    assert_safe_target_blind_paths_v24,
    build_sourcebound_manifest_v24,
    validate_sourcebound_panel_v24,
    write_if_new_or_identical_v24,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT
    / "specs"
    / "001-pit-options-rv30"
    / "contracts"
    / "target-blind-common-predictor-manifest-v24.schema.json"
)


def test_v24_explicit_allowlists_cover_only_registered_b0_b1_b2_and_panel_columns() -> None:
    """The successor declares separate B0/B1/B2 allowlists rather than a deny-list."""
    assert set(KEY_COLUMNS) <= B0_ALLOWED_COLUMNS
    assert set(KEY_COLUMNS) <= B1_ALLOWED_COLUMNS
    assert set(KEY_COLUMNS) <= B2_ALLOWED_COLUMNS
    assert B0_ALLOWED_COLUMNS | B1_ALLOWED_COLUMNS | B2_ALLOWED_COLUMNS <= PANEL_ALLOWED_COLUMNS
    assert "target" not in PANEL_ALLOWED_COLUMNS
    assert "prediction" not in PANEL_ALLOWED_COLUMNS
    assert "metric" not in PANEL_ALLOWED_COLUMNS
    assert "model" not in PANEL_ALLOWED_COLUMNS


def test_v24_panel_preserves_every_origin_and_keeps_excluded_b2_features_null() -> None:
    """An excluded B2 row remains present, flagged, reason-coded, and fully null."""
    origins, panel, common = _valid_frames()

    validate_sourcebound_panel_v24(origins=origins, panel=panel, common=common)

    assert panel.height == origins.height == 2
    excluded = panel.filter(~pl.col("b2v2_availability_eligible"))
    assert excluded.height == 1
    assert all(excluded.get_column(column).null_count() == 1 for column in B2V2_FEATURES)
    assert excluded.get_column("b2v2_predictor_missing_reason").to_list() == [
        "B2V2_DELAYED_OR_UNAVAILABLE_ACTIVITY"
    ]


def test_v24_panel_rejects_forbidden_output_column() -> None:
    """A target/metric-like field cannot bypass the explicit output allowlist."""
    origins, panel, common = _valid_frames()
    panel = panel.with_columns(pl.lit(1.0).alias("metric_payload"))

    with pytest.raises(ValueError, match="TARGET_BLIND_V24_FORBIDDEN_COLUMN"):
        validate_sourcebound_panel_v24(origins=origins, panel=panel, common=common)


def test_v24_panel_rejects_duplicate_origin() -> None:
    """A duplicate cannot silently turn an origin-preserving panel into a many-to-one join."""
    origins, panel, common = _valid_frames()
    duplicated = pl.concat([panel, panel.head(1)])

    with pytest.raises(ValueError, match="TARGET_BLIND_V24_DUPLICATE_ORIGIN:panel"):
        validate_sourcebound_panel_v24(origins=origins, panel=duplicated, common=common)


def test_v24_panel_rejects_zero_or_value_in_an_excluded_b2_row() -> None:
    """The repaired path rejects zero coding just as it rejects any non-null B2 value."""
    origins, panel, common = _valid_frames()
    invalid = panel.with_columns(
        pl.when(pl.col("origin_id") == "origin-b")
        .then(pl.lit(0.0))
        .otherwise(pl.col(B2V2_FEATURES[0]))
        .alias(B2V2_FEATURES[0])
    )

    with pytest.raises(ValueError, match="TARGET_BLIND_V24_B2_EXCLUDED_FEATURE_NOT_NULL"):
        validate_sourcebound_panel_v24(origins=origins, panel=invalid, common=common)


def test_v24_preflight_bindings_reject_a_sidecar_changed_after_preflight() -> None:
    """A sidecar byte change after schema/hash preflight must abort the build."""
    before = _provenance_hashes()
    after = dict(before)
    after["b2_availability_sidecar_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="TARGET_BLIND_V24_SIDECAR_CHANGED_AFTER_PREFLIGHT"):
        assert_preflight_hashes_unchanged_v24(before=before, after=after)


@pytest.mark.parametrize(
    "bad_name",
    [
        "outcome_payload.parquet",
        "target_payload.parquet",
        "metric_payload.parquet",
        "model_payload.parquet",
    ],
)
def test_v24_rejects_forbidden_input_paths_without_echoing_them(
    tmp_path: Path, bad_name: str
) -> None:
    """No result-like path can reach a reader, while target-blind roots remain valid."""
    paths = {
        "origins": tmp_path / "origins.parquet",
        "b1_source": tmp_path / "b1_source.parquet",
        "forbidden": tmp_path / bad_name,
        "output_root": tmp_path / "target_blind_v24_sourcebound",
    }

    with pytest.raises(ValueError, match="TARGET_BLIND_V24_FORBIDDEN_INPUT_PATH:forbidden"):
        assert_safe_target_blind_paths_v24(paths)


def test_v24_writer_is_idempotent_and_refuses_conflict(tmp_path: Path) -> None:
    """The new version retains byte-identical replay and conflict failure semantics."""
    path = tmp_path / "artifact.bin"

    write_if_new_or_identical_v24(path, lambda temporary: temporary.write_bytes(b"stable"))
    write_if_new_or_identical_v24(path, lambda temporary: temporary.write_bytes(b"stable"))

    with pytest.raises(
        FileExistsError, match="TARGET_BLIND_V24_OUTPUT_EXISTS_WITH_DIFFERENT_BYTES"
    ):
        write_if_new_or_identical_v24(path, lambda temporary: temporary.write_bytes(b"drift"))
    assert path.read_bytes() == b"stable"


def test_v24_manifest_is_deterministic_schema_valid_and_explicitly_oos_closed(
    tmp_path: Path,
) -> None:
    """A source-bound manifest records hashes and cannot turn OOS/reconciliation on."""
    _, panel, common = _valid_frames()
    panel_path = tmp_path / "panel.parquet"
    common_path = tmp_path / "common.parquet"
    panel.write_parquet(panel_path)
    common.write_parquet(common_path)
    kwargs = {
        "panel": panel,
        "common": common,
        "panel_path": panel_path,
        "common_path": common_path,
        "provenance_hashes": _provenance_hashes(),
        "source_hashes": {
            "fmp_bars_sha256": "1" * 64,
            "b1q_source_sha256": "2" * 64,
            "b2_primary_inputs_sha256": "3" * 64,
            "origins_sha256": "4" * 64,
            "b2_availability_sidecar_sha256": "5" * 64,
            "massive_reselection_sensitivity_v21_sha256": "6" * 64,
        },
        "summary": _summary(),
        "builder_hashes": {
            "script_sha256": "7" * 64,
            "panel_module_sha256": "8" * 64,
            "base_panel_module_sha256": "9" * 64,
            "provenance_module_sha256": "a" * 64,
        },
        "source_commit": "b" * 40,
        "panel_location": "D:/MDS650/phase6/derived/target_blind_v24_sourcebound/panel.parquet",
        "common_location": "D:/MDS650/phase6/derived/target_blind_v24_sourcebound/common.parquet",
    }

    first = build_sourcebound_manifest_v24(**kwargs)
    second = build_sourcebound_manifest_v24(**kwargs)

    assert first == second
    assert first["safe_to_reconcile_existing_results"] == "NO"
    assert first["SAFE_TO_OPEN_OR_EVALUATE_OOS"] == "NO"
    assert _canonical_sha256_without(first, "manifest_sha256") == first["manifest_sha256"]
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert not list(Draft202012Validator(schema).iter_errors(first))


def _valid_frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    origin_times = [
        datetime(2025, 8, 21, 14, 0, tzinfo=UTC),
        datetime(2025, 8, 21, 14, 5, tzinfo=UTC),
    ]
    panel_values: dict[str, object] = {
        "origin_id": ["origin-a", "origin-b"],
        "asset": ["AAPL", "AAPL"],
        "session_date": ["2025-08-21", "2025-08-21"],
        "forecast_origin_utc": origin_times,
        "forecast_origin_ns": [int(value.timestamp() * 1_000_000_000) for value in origin_times],
        "max_sip_timestamp_ns": [
            int(origin_times[0].timestamp() * 1_000_000_000) - 1,
            int(origin_times[1].timestamp() * 1_000_000_000) - 1,
        ],
        "b0v2_max_predictor_available_at_utc": origin_times,
        "b0v2_predictor_missing_reason": [None, None],
        "b1v2a_complete": [True, True],
        "b1v2b_complete": [True, True],
        "b1v2c_complete": [True, True],
        "b1q_source_time_rule": ["SIP_ASOF_ORIGIN_MAX_AGE_60S"] * 2,
        "b1v2_predictor_missing_reason": [None, None],
        "b2v2_complete": [True, True],
        "b2v2_cutoff_utc": origin_times,
        "b2v2_max_created_at_utc": [origin_times[0], None],
        "b2v2_availability_status": [
            "PIT_USABLE_ELIGIBLE_ACTIVITY",
            "PIT_EXCLUDED_DELAYED_RAW_WINDOW_TRADES",
        ],
        "b2v2_availability_eligible": [True, False],
        "b2v2_corrected_pit_complete": [True, False],
        "b2v2_predictor_missing_reason": [
            None,
            "B2V2_DELAYED_OR_UNAVAILABLE_ACTIVITY",
        ],
        "b0v2_predictor_complete": [True, True],
        "b1v2a_predictor_complete": [True, True],
        "b1v2b_predictor_complete": [True, True],
        "b1v2c_predictor_complete": [True, True],
        "b2v2_predictor_complete": [True, False],
        "common_predictor_complete": [True, False],
        "predictor_exclusion_reason": ["NONE", "B2V2_DELAYED_OR_UNAVAILABLE_ACTIVITY"],
    }
    for feature in B0V2_FEATURES:
        panel_values[feature] = ["AAPL", "AAPL"] if feature == "b0v2_asset_identity" else [1.0, 1.0]
    for feature in (*B1V2A_FEATURES, *B1V2B_FEATURES, *B1V2C_FEATURES):
        panel_values[feature] = [1.0, 1.0]
    for feature in B2V2_FEATURES:
        panel_values[feature] = [1.0, None]
    panel = pl.DataFrame(panel_values, strict=False).select(sorted(PANEL_ALLOWED_COLUMNS))
    origins = panel.select(*KEY_COLUMNS)
    common = panel.filter(pl.col("common_predictor_complete"))
    return origins, panel, common


def _provenance_hashes() -> dict[str, str]:
    return {
        "origins_sha256": "a" * 64,
        "b2_availability_sidecar_sha256": "b" * 64,
        "massive_reselection_recomputed_v21_sha256": "c" * 64,
        "b2_availability_manifest_v22_sha256": "d" * 64,
        "pit_reconciliation_gate_v21_sha256": "e" * 64,
    }


def _summary() -> dict[str, object]:
    return {
        "schema_version": "target-blind-common-predictor-panel-v2.4",
        "status": "PASS_TARGET_BLIND_INPUTS_RECONCILIATION_REMAINS_BLOCKED",
        "scope": "offline_target_blind_predictor_construction_only",
        "no_target_or_metric_payload_read": True,
        "model_fit_performed": False,
        "row_count": 2,
        "completion_counts": {"common_predictor_complete": 1},
        "completion_rates": {"common_predictor_complete": 0.5},
    }


def _canonical_sha256_without(payload: dict[str, object], hash_field: str) -> str:
    unsigned = dict(payload)
    unsigned.pop(hash_field)
    rendered = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()
