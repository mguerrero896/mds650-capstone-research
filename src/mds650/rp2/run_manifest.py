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
        (
            "rp2_block3_target/target_panel.parquet",
            "rp2_block3_target/comparison.json",
        ),
    ),
    PipelineStep(
        "build-b0",
        "causal, asset-local baseline panel",
        ("rp2_block4_b0/b0_panel.parquet", "rp2_block4_b0/ladder.json"),
    ),
    PipelineStep(
        "build-b1",
        "contemporaneous option-state snapshot",
        (
            "rp2_block5_surface/b1_surface_panel.parquet",
            # The scorecard reads this. An artifact a result depends on that the manifest
            # never hashed is an artifact a rebuild cannot be checked against.
            "rp2_block5_surface/surface_coverage.json",
        ),
    ),
    PipelineStep(
        "build-b2",
        "point-in-time option flow on both clocks",
        (
            "rp2_block6_flow/b2_flow_panel.parquet",
            "rp2_block6_flow/flow_coverage.json",
        ),
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
    #: Artifact path relative to the run directory -> sha256 of its bytes. This is the
    #: integrity digest: it answers "is the file on disk the file this step wrote".
    artifacts: Mapping[str, str] = field(default_factory=dict)
    #: The same artifacts, digested with their volatile fields removed. This is the
    #: scientific digest: it answers "did this step produce the same result", which is a
    #: different question, because every block artifact stamps itself with the time it was
    #: written and the scorecard records how long the run took.
    content: Mapping[str, str] = field(default_factory=dict)
    #: Whether this step reused an artifact a previous attempt at the same run produced.
    #: Provenance, not science: a byte-identical panel is the same panel whether it was
    #: rebuilt or reused, and recording the difference in the identity would make a
    #: same-commit retry disagree with the run it is retrying.
    reused: bool = False

    def __post_init__(self) -> None:
        # A step that recorded byte digests and no content digests would contribute
        # nothing to the run's identity while looking fully recorded - which is exactly
        # what the resumed-run branch did to the four reused panels.
        missing = sorted(set(self.artifacts) - set(self.content))
        if missing:
            raise ValueError(f"RP2_STEP_CONTENT_MISSING:{self.name}:{','.join(missing)}")

    def scientific_part(self) -> dict[str, object]:
        """The step's contribution to the run's identity: what it ran and what it produced."""

        return {
            "name": self.name,
            # Normalised, not verbatim. The recorded command carries this machine's
            # interpreter path and this checkout's output root; hashing those would make
            # the same experiment on another machine disagree about its own identity. The
            # full command is kept in `as_record` for provenance.
            "command": normalise_command(self.command),
            "exit_code": self.exit_code,
            # Deliberately the stable digests. Using the byte digests here would let the
            # clock into the run's scientific identity through the artifacts, which is
            # precisely what keeping `started_at_utc` out of it was for.
            "content": dict(sorted(self.content.items())),
        }

    def as_record(self) -> dict[str, object]:
        return {
            **self.scientific_part(),
            "command": list(self.command),
            "reused": self.reused,
            "artifacts": dict(sorted(self.artifacts.items())),
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

    def identity_part(self) -> dict[str, object]:
        """What makes a retry the same run, including where it was run and what it is called."""

        return {
            **self.scientific_part(),
            "run_id": self.run_id,
            "data_root": self.data_root,
        }

    def scientific_part(self) -> dict[str, object]:
        """What decides the result.

        Deliberately without the run id and the data root. The same inputs rebuilt under a
        new label, or from a store mounted at a different letter, are the same experiment;
        a hash that disagreed there would contradict the reproducibility it exists to
        establish. Both stay in the record, and both are still compared when a run id is
        reused.
        """

        return {
            "code_commit": self.code_commit,
            "roles": list(self.roles),
            "feature_registry_sha256": self.feature_registry_sha256,
            "input_manifest_sha256": self.input_manifest_sha256,
            "model_config_sha256": self.model_config_sha256,
            "seeds": dict(sorted(self.seeds.items())),
            "steps": [step.scientific_part() for step in self.steps],
        }

    def as_record(self) -> dict[str, object]:
        return {
            **self.identity_part(),
            "steps": [step.as_record() for step in self.steps],
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "scientific_sha256": scientific_sha256(self),
        }


#: Arguments whose value is a path on this machine rather than a decision about the run.
_LOCAL_PATH_FLAGS: Final = frozenset(
    {"--output-dir", "--panel-root", "--output-root", "--data-root"}
)


def normalise_command(command: Sequence[str]) -> list[str]:
    """The part of a command that says *what ran*, with machine-local paths removed.

    An interpreter at `C:/Users/.../python.exe` and one at `/home/.../bin/python3.12` are
    the same decision; so are two output roots differing only by where the repository was
    checked out. The script and its scientific flags are what identify the step.
    """

    normalised: list[str] = []
    skip_next = False
    for index, argument in enumerate(command):
        if skip_next:
            normalised.append("<path>")
            skip_next = False
            continue
        if argument in _LOCAL_PATH_FLAGS:
            normalised.append(argument)
            skip_next = True
            continue
        if index == 0 and ("python" in Path(argument).name.lower() or argument == "internal"):
            normalised.append("python")
            continue
        looks_like_a_path = "/" in argument or "\\" in argument
        normalised.append(Path(argument).as_posix() if looks_like_a_path else argument)
    return normalised


def canonical_json(payload: object) -> str:
    """Sorted, separator-fixed JSON, so a hash depends on content and not on formatting."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scientific_sha256(manifest: RunManifest) -> str:
    """Digest of everything that decides the result, and of nothing that does not."""

    return hashlib.sha256(canonical_json(manifest.scientific_part()).encode("utf-8")).hexdigest()


#: Fields that record *when* or *how long*, not *what*. They are stripped before an
#: artifact is digested for the run's scientific identity, because every block artifact
#: stamps itself and the scorecard records its own runtime: hashing those bytes would make
#: two identical executions disagree.
VOLATILE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "generated_at_utc",
        "generated_at",
        "started_at_utc",
        "finished_at_utc",
        "created_at",
        "runtime_seconds",
        "peak_memory_bytes",
        "elapsed_seconds",
        # The run's label. Administration, like the data root: the same experiment under a
        # new name is the same experiment, and the scorecard is itself a hashed artifact.
        "run_id",
    }
)


def _without_volatile(value: object) -> object:
    """The same structure with every volatile field removed, however deeply it is nested."""

    if isinstance(value, Mapping):
        return {
            key: _without_volatile(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_without_volatile(item) for item in value]
    return value


def stable_content_digest(path: Path) -> str:
    """Digest of what an artifact *says*, rather than of the bytes it happens to occupy.

    JSON artifacts are reparsed, stripped of their volatile fields and re-serialised
    canonically, so indentation and a timestamp cannot move the digest. Anything else -
    a parquet panel, a rendered document - is digested by its bytes, which for those is
    already the content.
    """

    if path.suffix.lower() != ".json":
        return file_digest(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return file_digest(path)
    return hashlib.sha256(canonical_json(_without_volatile(payload)).encode("utf-8")).hexdigest()


def inventory_paths(path: Path) -> list[Path]:
    """Every file the option-tape inventory points a producer at.

    Blocks 5 and 6 open each of these. A sealed-cohort check that inspects only the gated
    manifest and the data root leaves the guarantee resting on the inventory happening to
    be the one somebody looked at once.
    """

    paths: list[Path] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            target = record.get("path")
            if target:
                paths.append(Path(str(target)))
    return paths


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
        # Absence is not agreement. A step recorded this file; if it is gone by the time
        # the run verifies itself, the manifest describes something that no longer exists.
        raise ValueError(f"RP2_RUN_ARTIFACT_MISSING:{path.name}")
    actual = file_digest(path)
    if actual != expected_sha256:
        raise ValueError(
            f"RP2_RUN_ARTIFACT_HASH_CONFLICT:{path.name}:{actual[:12]}!={expected_sha256[:12]}"
        )


#: What makes two runs the same run. Everything here is decided before the first producer
#: starts, which is why it can be checked before one does.
_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "code_commit",
    "data_root",
    "feature_registry_sha256",
    "model_config_sha256",
    # Same commit, same seeds, different data is a different run and not a retry. Left out
    # of this list, a re-acquired input would silently overwrite the previous outputs.
    "input_manifest_sha256",
    "seeds",
    "roles",
)


def assert_run_identity_unchanged(run_dir: Path, manifest: RunManifest) -> None:
    """Refuse a run id that already holds a different run, *before* anything overwrites it.

    Checking this at the end is too late: by then every producer has already written its
    output over the previous run's, and the conflict is discovered next to artifacts that
    no longer match the manifest sitting beside them.
    """

    path = run_dir / "run_manifest.json"
    if not path.is_file():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ValueError(f"RP2_RUN_IDENTITY_CONFLICT:{manifest.run_id}:unreadable") from None
    proposed = manifest.identity_part()
    # A field the caller cannot know yet is skipped rather than compared against a blank:
    # the input digest is only available once step 1 has hashed the inputs, so the check
    # runs twice - before anything at all, and again after step 1 and still before the
    # first producer.
    differing = [
        field
        for field in _IDENTITY_FIELDS
        if proposed.get(field)
        and existing.get(field) is not None
        and existing.get(field) != proposed.get(field)
    ]
    if differing:
        raise ValueError(
            f"RP2_RUN_IDENTITY_CONFLICT:{manifest.run_id}:{','.join(sorted(differing))}"
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
