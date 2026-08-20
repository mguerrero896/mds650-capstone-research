"""What a rebuild has to be able to say about itself.

A result that cannot be traced to the inputs, the code and the seeds that produced it is a
number, not a measurement. This module holds the record of one run: the fixed order of its
steps, the digest of everything it read and wrote, and a hash over the parts that decide
the science.

The execution clock is deliberately outside that hash. Two runs of the same inputs at the
same commit with the same seeds must agree on it, and they will not agree on when they
happened. Runtime and memory are recorded beside it as engineering facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

#: Cohorts that must not be read during development. Matched on whole path components so
#: that `cohort_c` is caught and `concentration` is not.
_SEALED_PATTERNS: Final = (
    re.compile(r"^cohort[_-]?c$", re.IGNORECASE),
    # Any component that begins with phase 8 or 9, however it continues: `phase8`,
    # `phase_9`, `phase9_seal`, `phase8a-recovery`. A trailing digit is excluded so that a
    # hypothetical `phase80` is not mistaken for one of them.
    re.compile(r"^phase[_-]?[89](?!\d)", re.IGNORECASE),
)
#: Filename stems that name a sealed cohort even when the directory does not.
_SEALED_STEMS: Final = (
    re.compile(r"(^|[_-])cohort[_-]?c([_-]|$)", re.IGNORECASE),
    re.compile(r"(^|[_-])phase[_-]?[89]", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class PipelineStep:
    """One step of the fixed order, and what it is allowed to leave behind."""

    name: str
    description: str
    #: Artifacts the step must produce, relative to the run directory. A step that exits
    #: zero without writing them has not run, whatever its exit code says.
    outputs: tuple[str, ...] = ()


#: The order is the plan's, and it is fixed. A rebuild that runs these in another order is
#: not the same experiment: the masks depend on the panels, and the inference depends on
#: the masks.
PIPELINE_STEPS: Final[tuple[PipelineStep, ...]] = (
    PipelineStep(
        "validate-input-manifests",
        "every declared input exists and hashes as recorded",
    ),
    PipelineStep(
        "build-targets",
        "Block 3 realized-variance targets",
        ("rp2_block3_target/target_panel.parquet",),
    ),
    PipelineStep(
        "build-b0",
        "causal, asset-local baseline panel",
        ("rp2_block4_b0/b0_panel.parquet",),
    ),
    PipelineStep(
        "build-b1",
        "contemporaneous option-state snapshot",
        ("rp2_block5_surface/b1_surface_panel.parquet",),
    ),
    PipelineStep(
        "build-b2",
        "point-in-time option flow on both clocks",
        ("rp2_block6_flow/b2_flow_panel.parquet",),
    ),
    PipelineStep(
        "validate-feature-registry",
        "core sets resolve and meet their coverage floors",
    ),
    PipelineStep("construct-common-masks", "one evaluation mask per role, hashed"),
    PipelineStep(
        "fit-model-ladder",
        "the frozen primary families",
        ("rp2_block8_ladder/ladder.json",),
    ),
    PipelineStep(
        "run-dml-diagnostics",
        "partialling-out with time-block cross-fitting",
        ("rp2_block7_dml/dml.json",),
    ),
    PipelineStep(
        "run-incremental-inference",
        "session-level, family-matched",
        ("rp2_block10_inference/inference.json",),
    ),
    PipelineStep(
        "generate-scorecard",
        "every field the schema requires",
        ("scorecard.json", "scorecard.md"),
    ),
    PipelineStep(
        "generate-provenance",
        "inputs, code, seeds and digests",
        ("run_manifest.json",),
    ),
    PipelineStep("verify-artifact-hashes", "what was written is what was recorded"),
)


STEP_NAMES: Final[tuple[str, ...]] = tuple(step.name for step in PIPELINE_STEPS)


@dataclass(frozen=True, slots=True)
class StepRecord:
    """What one step did, separated into what decides the science and what does not."""

    name: str
    command: tuple[str, ...]
    exit_code: int
    runtime_seconds: float
    peak_memory_bytes: int
    #: Artifact path relative to the run directory -> sha256 of its bytes.
    artifacts: Mapping[str, str] = field(default_factory=dict)

    def scientific_part(self) -> dict[str, object]:
        """The step's contribution to the run's identity: what it ran and what it produced."""

        return {
            "name": self.name,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "artifacts": dict(sorted(self.artifacts.items())),
        }

    def as_record(self) -> dict[str, object]:
        return {
            **self.scientific_part(),
            "runtime_seconds": self.runtime_seconds,
            "peak_memory_bytes": self.peak_memory_bytes,
        }


@dataclass(frozen=True, slots=True)
class RunManifest:
    """One rebuild, end to end."""

    run_id: str
    code_commit: str
    data_root: str
    roles: tuple[str, ...]
    feature_registry_sha256: str
    input_manifest_sha256: str
    model_config_sha256: str
    seeds: Mapping[str, int]
    steps: tuple[StepRecord, ...]
    started_at_utc: str
    finished_at_utc: str

    def scientific_part(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "code_commit": self.code_commit,
            "data_root": self.data_root,
            "roles": list(self.roles),
            "feature_registry_sha256": self.feature_registry_sha256,
            "input_manifest_sha256": self.input_manifest_sha256,
            "model_config_sha256": self.model_config_sha256,
            "seeds": dict(sorted(self.seeds.items())),
            "steps": [step.scientific_part() for step in self.steps],
        }

    def as_record(self) -> dict[str, object]:
        return {
            **self.scientific_part(),
            "steps": [step.as_record() for step in self.steps],
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "scientific_sha256": scientific_sha256(self),
        }


def canonical_json(payload: object) -> str:
    """Sorted, separator-fixed JSON, so a hash depends on content and not on formatting."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scientific_sha256(manifest: RunManifest) -> str:
    """Digest of everything that decides the result, and of nothing that does not."""

    return hashlib.sha256(canonical_json(manifest.scientific_part()).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    """sha256 of a file's bytes, read in chunks so a multi-gigabyte panel still fits."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_no_sealed_paths(paths: Iterable[Path]) -> None:
    """Refuse before anything is read.

    Cohort C, Phase 8 and Phase 9 are sealed for the whole programme. A run that touches
    one of them has spent the confirmation, and no later care recovers it - so the check
    is a precondition, not a warning, and it names the offending path.
    """

    for path in paths:
        parts = [*path.parts, path.stem]
        for component in parts:
            if any(pattern.match(component) for pattern in _SEALED_PATTERNS):
                raise ValueError(f"RP2_RUN_SEALED_COHORT_FORBIDDEN:{path.as_posix()}")
        for pattern in _SEALED_STEMS:
            if pattern.search(path.stem):
                raise ValueError(f"RP2_RUN_SEALED_COHORT_FORBIDDEN:{path.as_posix()}")


def assert_artifact_stable(path: Path, expected_sha256: str) -> None:
    """One run id holds one version of an artifact.

    Re-running a step is ordinary. Re-running it to a *different* answer under the same run
    id would leave two incompatible results wearing one label, and a reader with the label
    would have no way to tell which one a document cited.
    """

    if not path.is_file():
        return
    actual = file_digest(path)
    if actual != expected_sha256:
        raise ValueError(
            f"RP2_RUN_ARTIFACT_HASH_CONFLICT:{path.name}:{actual[:12]}!={expected_sha256[:12]}"
        )


def write_manifest(run_dir: Path, manifest: RunManifest) -> Path:
    """Write the manifest, refusing to replace a different manifest for the same run id."""

    path = run_dir / "run_manifest.json"
    payload = json.dumps(manifest.as_record(), indent=2, sort_keys=True) + "\n"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("scientific_sha256") != manifest.as_record()["scientific_sha256"]:
            raise ValueError(f"RP2_RUN_MANIFEST_CONFLICT:{manifest.run_id}")
    path.write_text(payload, encoding="utf-8")
    return path


def declared_inputs(manifest_path: Path) -> tuple[Sequence[Path], str]:
    """Every path the gated-data manifest declares, and the digest of the manifest itself."""

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("files", [])
    return [Path(str(entry["path"])) for entry in entries], file_digest(manifest_path)
