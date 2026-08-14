from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from scripts.prepare_b1v3_confirmation_acquisition import main

from mds650.b1v3_confirmation import canonical_sha256
from mds650.b1v3_confirmation_acquisition import (
    build_storage_projection,
    link_verified_file,
    reusable_records_from_manifest,
    sha256_file,
)

ROOT = Path(__file__).parents[2]
SCHEMA = (
    ROOT
    / "specs/001-pit-options-rv30/contracts/"
    "b1v3-confirmation-storage-reuse-v1.schema.json"
)
ARTIFACT = (
    ROOT
    / "artifacts/b1v3_confirmation_panel/storage_and_reuse_preflight.json"
)


def _checkpoint(day: str, raw_bytes: int, parquet_bytes: int) -> dict[str, object]:
    record: dict[str, object] = {
        "session_date": day,
        "status": "PASS",
        "raw_bytes": raw_bytes,
        "raw_sha256": "a" * 64,
        "parquet_bytes": parquet_bytes,
        "parquet_files": [
            {
                "relative_path": f"data/option_events/date={day}/asset=AAPL/events.parquet",
                "bytes": parquet_bytes,
                "sha256": "b" * 64,
            }
        ],
        "duplicate_event_ids": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    record["checkpoint_sha256"] = canonical_sha256(record)
    return record


def _source_manifest(records: list[dict[str, object]]) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": "b2-confirmation-acquisition-1.0",
        "status": "PASS",
        "completed_count": len(records),
        "target_outcome_read": False,
        "oos_read_count": 0,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
        "records": records,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def test_reusable_records_are_self_hashed_target_blind_and_allowlisted() -> None:
    first = _checkpoint("2024-08-02", 1000, 200)
    second = _checkpoint("2024-08-05", 1200, 240)

    selected = reusable_records_from_manifest(
        _source_manifest([first, second]),
        allowed_sessions=("2024-08-02", "2024-08-06"),
    )

    assert list(selected) == ["2024-08-02"]
    assert selected["2024-08-02"]["raw_bytes"] == 1000


def test_reusable_records_reject_tampered_checkpoint() -> None:
    record = _checkpoint("2024-08-02", 1000, 200)
    record["raw_bytes"] = 999
    manifest = _source_manifest([record])

    with pytest.raises(ValueError, match="B1V3_REUSE_CHECKPOINT_HASH_INVALID"):
        reusable_records_from_manifest(manifest, allowed_sessions=("2024-08-02",))


def test_reusable_records_reject_manifest_gate_and_duplicate_dates() -> None:
    first = _checkpoint("2024-08-02", 1000, 200)
    invalid_gate = _source_manifest([first])
    invalid_gate["status"] = "FAIL"
    invalid_gate["manifest_sha256"] = canonical_sha256(
        {key: value for key, value in invalid_gate.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_REUSE_MANIFEST_GATE_INVALID"):
        reusable_records_from_manifest(
            invalid_gate, allowed_sessions=("2024-08-02",)
        )

    duplicated = _source_manifest([first, first])
    with pytest.raises(ValueError, match="B1V3_REUSE_CHECKPOINT_DUPLICATE"):
        reusable_records_from_manifest(
            duplicated, allowed_sessions=("2024-08-02",)
        )


def test_reusable_records_reject_manifest_hash_and_invalid_checkpoint() -> None:
    record = _checkpoint("2024-08-02", 1000, 200)
    tampered_manifest = _source_manifest([record])
    tampered_manifest["completed_count"] = 999
    with pytest.raises(ValueError, match="B1V3_REUSE_MANIFEST_HASH_INVALID"):
        reusable_records_from_manifest(
            tampered_manifest, allowed_sessions=("2024-08-02",)
        )

    record["parquet_files"] = []
    record["checkpoint_sha256"] = canonical_sha256(
        {key: value for key, value in record.items() if key != "checkpoint_sha256"}
    )
    with pytest.raises(ValueError, match="B1V3_REUSE_CHECKPOINT_INVALID"):
        reusable_records_from_manifest(
            _source_manifest([record]), allowed_sessions=("2024-08-02",)
        )


def test_storage_projection_uses_exact_uw_and_massive_p95() -> None:
    projection = build_storage_projection(
        all_sessions=("2024-08-02", "2024-08-05", "2024-08-06"),
        reusable_records={"2024-08-02": _checkpoint("2024-08-02", 1000, 200)},
        uw_content_lengths={
            "2024-08-02": 1000,
            "2024-08-05": 2000,
            "2024-08-06": 3000,
        },
        massive_daily_bytes=(100, 200, 300, 400, 500),
        current_free_bytes=100_000,
        minimum_free_bytes=10_000,
        engineering_margin_bytes=1000,
    )

    assert projection["reusable_session_count"] == 1
    assert projection["missing_session_count"] == 2
    assert projection["uw_missing_raw_bytes"] == 5000
    assert projection["uw_filtered_projected_bytes"] == 1000
    assert projection["massive_daily_p95_bytes"] == 500
    assert projection["massive_missing_p95_bytes"] == 1000
    assert projection["peak_additional_bytes"] == 11_000
    assert projection["projected_minimum_free_bytes"] == 89_000
    assert projection["safe_to_continue"] is True


def test_storage_projection_fails_closed_below_floor() -> None:
    with pytest.raises(ValueError, match="B1V3_PROJECTED_MINIMUM_FREE_SPACE_BELOW_FLOOR"):
        build_storage_projection(
            all_sessions=("2024-08-02",),
            reusable_records={},
            uw_content_lengths={"2024-08-02": 9000},
            massive_daily_bytes=(1000,),
            current_free_bytes=10_000,
            minimum_free_bytes=8000,
            engineering_margin_bytes=1000,
        )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"all_sessions": ("2024-08-05", "2024-08-02")}, "SESSION_ALLOWLIST"),
        (
            {
                "reusable_records": {
                    "2024-08-05": _checkpoint("2024-08-05", 100, 20)
                }
            },
            "REUSE_OUTSIDE_ALLOWLIST",
        ),
        ({"uw_content_lengths": {"2024-08-02": 0}}, "UW_CONTENT_LENGTH"),
        ({"massive_daily_bytes": ()}, "MASSIVE_SAMPLE"),
        ({"engineering_margin_bytes": -1}, "STORAGE_BYTES"),
    ],
)
def test_storage_projection_rejects_invalid_inputs(
    overrides: dict[str, object], reason: str
) -> None:
    arguments: dict[str, Any] = {
        "all_sessions": ("2024-08-02",),
        "reusable_records": {},
        "uw_content_lengths": {"2024-08-02": 100},
        "massive_daily_bytes": (10,),
        "current_free_bytes": 10_000,
        "minimum_free_bytes": 100,
        "engineering_margin_bytes": 10,
    }
    arguments.update(overrides)
    with pytest.raises(ValueError, match=reason):
        build_storage_projection(**arguments)


def test_verified_hardlink_is_idempotent_and_conflict_safe(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "nested" / "destination.bin"
    source.write_bytes(b"immutable-commercial-evidence")
    expected = sha256_file(source)

    assert link_verified_file(source, destination, expected) == "LINKED_VERIFIED"
    assert destination.read_bytes() == source.read_bytes()
    assert os.path.samefile(source, destination)
    assert link_verified_file(source, destination, expected) == "REUSED_VERIFIED"

    destination.unlink()
    destination.write_bytes(b"conflict")
    with pytest.raises(ValueError, match="B1V3_REUSE_DESTINATION_HASH_MISMATCH"):
        link_verified_file(source, destination, expected)


def test_verified_hardlink_rejects_equal_but_physically_duplicated_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"same-bytes-but-not-the-same-file")
    destination.write_bytes(source.read_bytes())

    with pytest.raises(ValueError, match="B1V3_REUSE_DESTINATION_HASH_MISMATCH"):
        link_verified_file(source, destination, sha256_file(source))


def test_verified_hardlink_rejects_invalid_chunk_and_link_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"immutable")
    with pytest.raises(ValueError, match="B1V3_REUSE_HASH_CHUNK_INVALID"):
        sha256_file(source, chunk_size=0)

    monkeypatch.setattr(os, "link", lambda *_args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(ValueError, match="B1V3_REUSE_HARDLINK_FAILED"):
        link_verified_file(source, tmp_path / "destination.bin", sha256_file(source))


def test_verified_hardlink_rejects_non_hardlink_created_by_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"immutable")

    def fake_link(_source: Path, target: Path) -> None:
        target.write_bytes(source.read_bytes())
        raise FileExistsError

    monkeypatch.setattr(os, "link", fake_link)
    with pytest.raises(ValueError, match="B1V3_REUSE_DESTINATION_HASH_MISMATCH"):
        link_verified_file(source, destination, sha256_file(source))


def test_storage_reuse_schema_is_valid_draft_2020_12() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_storage_reuse_cli_help_is_directly_executable() -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])


def test_canonical_storage_reuse_artifact_is_schema_valid_and_self_hashed() -> None:
    document = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(document)
    unsigned = {key: value for key, value in document.items() if key != "manifest_sha256"}
    assert document["manifest_sha256"] == canonical_sha256(unsigned)
    assert document["status"] == "PASS_STORAGE_AND_REUSE_PREPARED"
    assert document["reusable_session_count"] == 60
    assert document["missing_session_count"] == 30
    assert document["outcome_read_count"] == 0
