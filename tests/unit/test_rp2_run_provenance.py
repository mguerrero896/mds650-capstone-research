"""What the run manifest has to identify, and what it must not accidentally depend on.

Three failures this pins, all of them ways a manifest can look complete and identify
nothing:

* hashing the files a run *declares* rather than the files it *reads*, so changing the real
  input leaves the recorded provenance identical;
* letting a clock into the scientific hash by the back door, through the bytes of an
  artifact that stamps itself;
* discovering that a run id already holds a different run only after its producers have
  overwritten the outputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mds650.rp2.run_manifest import (
    VOLATILE_KEYS,
    RunManifest,
    StepRecord,
    assert_no_sealed_paths,
    assert_run_identity_unchanged,
    file_digest,
    inventory_paths,
    scientific_sha256,
    stable_content_digest,
    write_manifest,
)


def _manifest(**overrides: object) -> RunManifest:
    defaults: dict[str, object] = {
        "run_id": "rp2-v3-test-001",
        "code_commit": "0" * 40,
        "data_root": "D:/MDS650",
        "roles": ("D", "V"),
        "feature_registry_sha256": "a" * 64,
        "input_manifest_sha256": "b" * 64,
        "model_config_sha256": "c" * 64,
        "seeds": {"bootstrap": 650},
        "steps": (),
        "started_at_utc": "2026-08-20T00:00:00+00:00",
        "finished_at_utc": "2026-08-20T01:00:00+00:00",
    }
    defaults.update(overrides)
    return RunManifest(**defaults)  # type: ignore[arg-type]


def test_an_artifact_that_stamps_itself_does_not_move_the_scientific_hash(tmp_path: Path) -> None:
    """Every block artifact carries `generated_at_utc`; the scorecard carries a runtime.

    Hashing their bytes and calling that the run's scientific identity would put the clock
    back into the identity through the side door, which is exactly what excluding
    `started_at_utc` from the manifest was for.
    """

    early = tmp_path / "early.json"
    late = tmp_path / "late.json"
    early.write_text(
        json.dumps({"qlike": 0.134, "generated_at_utc": "2026-08-20T07:00:00+00:00"}),
        encoding="utf-8",
    )
    late.write_text(
        json.dumps(
            {"qlike": 0.134, "generated_at_utc": "2027-01-01T23:59:59+00:00"},
            indent=2,
        ),
        encoding="utf-8",
    )

    assert file_digest(early) != file_digest(late), "the bytes differ, and integrity cares"
    assert stable_content_digest(early) == stable_content_digest(late)

    moved = tmp_path / "moved.json"
    moved.write_text(json.dumps({"qlike": 0.135, "generated_at_utc": "x"}), encoding="utf-8")
    assert stable_content_digest(moved) != stable_content_digest(early)


def test_the_volatile_keys_are_stripped_wherever_they_are_nested(tmp_path: Path) -> None:
    shallow = tmp_path / "a.json"
    deep = tmp_path / "b.json"
    shallow.write_text(json.dumps({"D": {"models": {"g": {"qlike": 1.0}}}}), encoding="utf-8")
    deep.write_text(
        json.dumps(
            {
                "D": {"models": {"g": {"qlike": 1.0, "runtime_seconds": 91.2}}},
                "generated_at_utc": "2026-08-20T00:00:00+00:00",
                "peak_memory_bytes": 12345,
            }
        ),
        encoding="utf-8",
    )
    assert stable_content_digest(shallow) == stable_content_digest(deep)
    assert {"generated_at_utc", "runtime_seconds", "peak_memory_bytes"} <= VOLATILE_KEYS


def test_a_step_record_keeps_both_digests_and_uses_the_stable_one_for_science(
    tmp_path: Path,
) -> None:
    stamped = tmp_path / "ladder.json"
    stamped.write_text(json.dumps({"q": 1.0, "generated_at_utc": "t0"}), encoding="utf-8")

    def record(when: str) -> StepRecord:
        stamped.write_text(json.dumps({"q": 1.0, "generated_at_utc": when}), encoding="utf-8")
        return StepRecord(
            name="fit-model-ladder",
            command=("uv", "run", "python", "scripts/rp2_block8_ladder.py"),
            exit_code=0,
            runtime_seconds=1.0,
            peak_memory_bytes=1024,
            artifacts={"ladder.json": file_digest(stamped)},
            content={"ladder.json": stable_content_digest(stamped)},
        )

    first = record("2026-08-20T07:00:00+00:00")
    second = record("2027-05-05T05:05:05+00:00")
    assert first.artifacts != second.artifacts, "byte integrity still notices the rewrite"
    assert scientific_sha256(_manifest(steps=(first,))) == scientific_sha256(
        _manifest(steps=(second,))
    )


def test_a_run_id_that_already_holds_a_different_run_is_refused_before_anything_runs(
    tmp_path: Path,
) -> None:
    """The check has to happen first. Afterwards the producers have already overwritten."""

    run_dir = tmp_path / "rp2-v3-20260820-001"
    run_dir.mkdir()
    write_manifest(run_dir, _manifest(run_id="rp2-v3-20260820-001"))

    # Same identity: a resumed run is ordinary.
    assert_run_identity_unchanged(run_dir, _manifest(run_id="rp2-v3-20260820-001"))

    for field, value in (
        ("code_commit", "1" * 40),
        ("feature_registry_sha256", "9" * 64),
        ("seeds", {"bootstrap": 651}),
        ("data_root", "E:/elsewhere"),
    ):
        with pytest.raises(ValueError, match="RP2_RUN_IDENTITY_CONFLICT"):
            assert_run_identity_unchanged(
                run_dir, _manifest(run_id="rp2-v3-20260820-001", **{field: value})
            )


def test_the_tape_inventory_is_read_and_every_path_in_it_is_checked(tmp_path: Path) -> None:
    """`--forbid-sealed-cohorts` promises the run touches no sealed cohort.

    The producers open every path in the inventory. Checking only the gated manifest and
    the data root leaves that promise resting on the inventory happening to be the one
    that was checked by hand once.
    """

    inventory = tmp_path / "inventory.jsonl"
    inventory.write_text(
        "\n".join(
            json.dumps({"path": path, "asset": "AAPL", "size_bytes": 1})
            for path in (
                "D:/MDS650/b1v3_confirmation/data/option_events/date=2024-08-02/a.parquet",
                "D:/MDS650/phase6/data/option_events/date=2025-01-02/a.parquet",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    paths = inventory_paths(inventory)
    assert len(paths) == 2
    assert_no_sealed_paths(paths)

    sealed = tmp_path / "sealed.jsonl"
    sealed.write_text(
        json.dumps({"path": "D:/MDS650/phase8_one_shot/events.parquet", "size_bytes": 1}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="RP2_RUN_SEALED_COHORT_FORBIDDEN"):
        assert_no_sealed_paths(inventory_paths(sealed))


def test_a_step_cannot_record_bytes_without_recording_content() -> None:
    """The invariant, rather than the call site.

    The `--skip-panels` branch recorded byte digests and left `content` empty, so the four
    reused panels were absent from the scientific hash entirely: a resumed run claimed an
    identity that did not bind the panels it was built on. Making the record refuse that
    shape fixes every call site at once, including the ones not written yet.
    """

    with pytest.raises(ValueError, match="RP2_STEP_CONTENT_MISSING:build-b1"):
        StepRecord(
            name="build-b1",
            command=("reused",),
            exit_code=0,
            runtime_seconds=0.0,
            peak_memory_bytes=0,
            artifacts={"rp2_block5_surface/b1_surface_panel.parquet": "a" * 64},
        )

    # A step with no artifacts at all is ordinary: not every step writes one.
    StepRecord(
        name="verify-artifact-hashes",
        command=("internal",),
        exit_code=0,
        runtime_seconds=0.0,
        peak_memory_bytes=0,
    )


def test_a_changed_input_moves_the_identity_even_when_everything_else_matches(
    tmp_path: Path,
) -> None:
    """Same commit, same seeds, different data. That is a different run, not a retry."""

    run_dir = tmp_path / "rp2-v3-20260820-001"
    run_dir.mkdir()
    write_manifest(run_dir, _manifest(input_manifest_sha256="1" * 64))

    assert_run_identity_unchanged(run_dir, _manifest(input_manifest_sha256="1" * 64))
    with pytest.raises(ValueError, match="RP2_RUN_IDENTITY_CONFLICT.*input_manifest_sha256"):
        assert_run_identity_unchanged(run_dir, _manifest(input_manifest_sha256="2" * 64))


def test_every_artifact_the_scorecard_reads_is_a_recorded_output() -> None:
    """A result that depends on a file the manifest never hashed is not reproducible.

    The scorecard reads both coverage reports; the step outputs listed only the panels, so
    a rebuild could have been assembled from one run's panels and another's coverage with
    nothing recording it.
    """

    from mds650.rp2.run_manifest import PIPELINE_STEPS

    declared = {output for step in PIPELINE_STEPS for output in step.outputs}
    for required in (
        "rp2_block5_surface/surface_coverage.json",
        "rp2_block6_flow/flow_coverage.json",
        "rp2_block3_target/comparison.json",
        "rp2_block4_b0/ladder.json",
    ):
        assert required in declared, required


def test_a_resumed_run_is_held_to_the_identity_it_started_with(tmp_path: Path) -> None:
    """The manifest is written last, which is too late to stop a resume from drifting.

    An interrupted run has no manifest, so an identity check that reads only the manifest
    compares nothing and `--skip-panels` can reuse panels built at another commit or from
    other inputs, publishing them under the current identity.
    """

    from mds650.rp2.run_manifest import write_run_identity

    run_dir = tmp_path / "rp2-v3-20260820-001"
    run_dir.mkdir()
    write_run_identity(run_dir, _manifest(run_id="rp2-v3-20260820-001"))
    assert (run_dir / "run_identity.json").is_file()
    assert not (run_dir / "run_manifest.json").exists(), "the run never finished"

    assert_run_identity_unchanged(run_dir, _manifest(run_id="rp2-v3-20260820-001"))
    for field, value in (("code_commit", "1" * 40), ("input_manifest_sha256", "9" * 64)):
        with pytest.raises(ValueError, match="RP2_RUN_IDENTITY_CONFLICT"):
            assert_run_identity_unchanged(
                run_dir, _manifest(run_id="rp2-v3-20260820-001", **{field: value})
            )


def test_a_metric_that_is_not_a_number_was_not_measured() -> None:
    """`NaN` is a scalar, so a null check accepts it and `json.dumps` writes `NaN`."""

    from mds650.rp2.scorecard import assert_scorecard_complete, required_fields

    groups = required_fields()
    scorecard: dict[str, object] = {
        group: dict.fromkeys(fields, 1.0) for group, fields in groups.items() if group != "forecast"
    }
    scorecard["data"] = {**scorecard["data"], "duplicate_keys": 0}  # type: ignore[dict-item]
    scorecard["b1"] = {
        **scorecard["b1"],
        "b1_post_cutoff_observations": 0,
        "b1_duplicate_contracts_per_snapshot": 0,
        "b1_rows_dropped_for_rate_or_dividend": 0,
        "b1_core_coverage": float("nan"),
    }  # type: ignore[dict-item]
    scorecard["b2"] = {**scorecard["b2"], "b2_pit_violation_count": 0}  # type: ignore[dict-item]
    scorecard["forecast"] = {
        "gamma_glm": {
            "D": {
                field: 1.0
                for field in groups["forecast"]
                if field not in ("calibration_slope", "calibration_intercept")
            }
        }
    }
    scorecard["forecast_calibration"] = {"calibration_slope": 1.0, "calibration_intercept": 0.0}

    with pytest.raises(ValueError, match="b1.b1_core_coverage:unmeasured"):
        assert_scorecard_complete(scorecard)


def test_a_sealed_cohort_is_refused_by_its_role_even_under_a_neutral_path(
    tmp_path: Path,
) -> None:
    """The path check reads names; a sealed row need not carry one.

    The input fingerprint opens every inventoried file, so a row whose role is `C` and
    whose path looks ordinary would be read whether or not a producer later selected it.
    """

    from mds650.rp2.run_manifest import assert_no_sealed_roles

    ordinary = tmp_path / "ordinary.jsonl"
    ordinary.write_text(
        "\n".join(
            json.dumps({"role": role, "path": "D:/MDS650/store/events.parquet"})
            for role in ("D", "V")
        )
        + "\n",
        encoding="utf-8",
    )
    assert_no_sealed_roles(ordinary)

    disguised = tmp_path / "disguised.jsonl"
    disguised.write_text(
        json.dumps({"role": "C", "path": "D:/MDS650/store/events.parquet"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="RP2_RUN_SEALED_COHORT_FORBIDDEN:role=C"):
        assert_no_sealed_roles(disguised)


def test_the_manifest_is_published_whole_or_not_at_all(tmp_path: Path) -> None:
    """A truncated manifest is read as an unreadable identity and closes the run id."""

    run_dir = tmp_path / "rp2-v3-20260820-001"
    run_dir.mkdir()
    write_manifest(run_dir, _manifest(run_id="rp2-v3-20260820-001"))

    assert not list(run_dir.glob("*.partial")), "the staging file is replaced, not left"
    payload = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "rp2-v3-20260820-001"


def test_the_confirmation_role_this_codebase_uses_is_sealed() -> None:
    """`BURNED` is what `assign_role` returns for every confirmation session.

    Its own docstring says those sessions are never used for anything. Leaving it out of
    the sealed roles left the guarantee resting on the sealed sessions never being
    enumerated rather than on their being refused.
    """

    from datetime import date

    from mds650.rp2.partition import assign_role
    from mds650.rp2.run_manifest import SEALED_ROLES

    assert assign_role(date(2026, 12, 31)) == "BURNED"
    assert "BURNED" in SEALED_ROLES
