"""The runner: one order, one run id, one set of hashes, and it stops rather than guesses.

Eight scripts run by hand with scattered configuration is not a pipeline; it is a habit.
What is checked here is the part a rebuild depends on: that the steps run in the order the
plan fixes, that the run refuses the things it must refuse, and that two runs of the same
inputs at the same commit agree on the scientific hash while disagreeing on the clock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mds650.rp2.run_manifest import (
    PIPELINE_STEPS,
    RunManifest,
    StepRecord,
    assert_artifact_stable,
    assert_no_sealed_paths,
    file_digest,
    scientific_sha256,
    stable_content_digest,
)

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "scripts" / "run_rp2_v3_pipeline.py"


def _manifest(run_id: str = "rp2-v3-test-001", **overrides: object) -> RunManifest:
    defaults: dict[str, object] = {
        "run_id": run_id,
        "code_commit": "0" * 40,
        "data_root": "D:/MDS650",
        "roles": ("D", "V"),
        "feature_registry_sha256": "a" * 64,
        "input_manifest_sha256": "b" * 64,
        "model_config_sha256": "c" * 64,
        "seeds": {"bootstrap": 650, "lightgbm": 20260818},
        "steps": (),
        "started_at_utc": "2026-08-20T00:00:00+00:00",
        "finished_at_utc": "2026-08-20T01:00:00+00:00",
    }
    defaults.update(overrides)
    return RunManifest(**defaults)  # type: ignore[arg-type]


def test_the_thirteen_steps_are_fixed_and_ordered() -> None:
    assert [step.name for step in PIPELINE_STEPS] == [
        "validate-input-manifests",
        "build-targets",
        "build-b0",
        "build-b1",
        "build-b2",
        "validate-feature-registry",
        "construct-common-masks",
        "fit-model-ladder",
        "run-dml-diagnostics",
        "run-incremental-inference",
        "generate-scorecard",
        "generate-provenance",
        "verify-artifact-hashes",
    ]


def test_the_runner_lists_its_plan_without_touching_the_data(tmp_path: Path) -> None:
    """A dry run is how an operator checks the order before spending two hours on it."""

    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--data-root",
            str(tmp_path / "absent"),
            "--output-root",
            str(tmp_path / "out"),
            "--run-id",
            "rp2-v3-dry-001",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert completed.returncode == 0, completed.stderr
    for index, step in enumerate(PIPELINE_STEPS, start=1):
        assert f"{index:2d}. {step.name}" in completed.stdout
    assert not (tmp_path / "out").exists(), "a dry run must not create the run directory"


def test_the_execution_clock_is_not_part_of_the_scientific_hash() -> None:
    """Two runs of the same inputs at the same commit must agree, whatever the clock says."""

    early = _manifest(started_at_utc="2026-08-20T00:00:00+00:00")
    late = _manifest(
        started_at_utc="2026-09-01T12:34:56+00:00", finished_at_utc="2026-09-01T13:00:00+00:00"
    )
    assert scientific_sha256(early) == scientific_sha256(late)

    different_seed = _manifest(seeds={"bootstrap": 651, "lightgbm": 20260818})
    assert scientific_sha256(different_seed) != scientific_sha256(early)

    different_commit = _manifest(code_commit="1" * 40)
    assert scientific_sha256(different_commit) != scientific_sha256(early)


def test_a_step_that_produced_a_different_artifact_changes_the_hash(tmp_path: Path) -> None:
    first = tmp_path / "one.json"
    first.write_text('{"a": 1}', encoding="utf-8")
    second = tmp_path / "two.json"
    second.write_text('{"a": 2}', encoding="utf-8")

    def record(path: Path, *, runtime: float = 1.0, memory: int = 1024) -> StepRecord:
        # Both digests, the way the runner records them: the bytes for integrity, the
        # volatile-free content for the science.
        return StepRecord(
            name="fit-model-ladder",
            command=("uv", "run", "python", "scripts/rp2_block8_ladder.py"),
            exit_code=0,
            runtime_seconds=runtime,
            peak_memory_bytes=memory,
            artifacts={"ladder.json": file_digest(path)},
            content={"ladder.json": stable_content_digest(path)},
        )

    assert scientific_sha256(_manifest(steps=(record(first),))) != scientific_sha256(
        _manifest(steps=(record(second),))
    )
    # Runtime and memory are engineering facts, not scientific ones.
    slow = record(first, runtime=9999.0, memory=99_999_999)
    assert scientific_sha256(_manifest(steps=(slow,))) == scientific_sha256(
        _manifest(steps=(record(first),))
    )


@pytest.mark.parametrize(
    "path",
    [
        "artifacts/b1v3_confirmation/cohort_c.parquet",
        "D:/MDS650/phase8/holdout.parquet",
        "artifacts/phase9_seal/results.json",
        "data/cohort_C/origins.parquet",
    ],
)
def test_the_runner_refuses_to_touch_a_sealed_cohort(path: str) -> None:
    """Not a warning, not a skip. The run stops before anything reads a byte."""

    with pytest.raises(ValueError, match="RP2_RUN_SEALED_COHORT_FORBIDDEN"):
        assert_no_sealed_paths([Path(path)])


def test_ordinary_inputs_are_not_mistaken_for_sealed_ones() -> None:
    assert_no_sealed_paths(
        [
            Path("artifacts/rp2_block4_b0/b0_panel.parquet"),
            Path("D:/MDS650/bars/spy.parquet"),
            Path("artifacts/rp2_v3/rp2-v3-20260820-001/ladder.json"),
        ]
    )


def test_one_run_id_cannot_hold_two_versions_of_the_same_artifact(tmp_path: Path) -> None:
    """Re-running a step is fine. Re-running it to a different answer is not."""

    run_dir = tmp_path / "rp2-v3-20260820-001"
    run_dir.mkdir()
    artifact = run_dir / "ladder.json"
    artifact.write_text('{"qlike": 0.13}', encoding="utf-8")
    digest = file_digest(artifact)

    assert_artifact_stable(artifact, digest)
    with pytest.raises(ValueError, match="RP2_RUN_ARTIFACT_HASH_CONFLICT"):
        assert_artifact_stable(artifact, "d" * 64)


def test_the_manifest_round_trips_through_json(tmp_path: Path) -> None:
    manifest = _manifest()
    payload = json.loads(json.dumps(manifest.as_record()))
    assert payload["run_id"] == "rp2-v3-test-001"
    assert payload["scientific_sha256"] == scientific_sha256(manifest)
    assert payload["roles"] == ["D", "V"]
