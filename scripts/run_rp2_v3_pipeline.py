"""One command that rebuilds RP2-v3, in one order, under one run id.

Eight scripts run by hand with scattered configuration is not a pipeline. Whichever one is
forgotten, or run with last week's flags, still produces an artifact that looks complete,
and the mismatch surfaces later as a number nobody can reproduce.

This runner fixes the order, gives every step the same run directory, records what each one
read and wrote, and stops on the first thing that would make the result untrustworthy: a
missing input, a changed schema, a core feature that does not resolve, a sealed cohort, or
an artifact that already exists under this run id with a different hash.

    uv run python scripts/run_rp2_v3_pipeline.py \\
        --data-root D:/MDS650 \\
        --output-root artifacts/rp2_v3 \\
        --run-id rp2-v3-20260820-001 \\
        --roles D V \\
        --forbid-sealed-cohorts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(ROOT / "src"))

from mds650.rp2.feature_registry import CONFIG as REGISTRY_CONFIG  # noqa: E402
from mds650.rp2.feature_registry import registry_sha256  # noqa: E402
from mds650.rp2.run_manifest import (  # noqa: E402
    PIPELINE_STEPS,
    RunManifest,
    StepRecord,
    assert_artifact_stable,
    assert_no_sealed_paths,
    assert_run_identity_unchanged,
    canonical_json,
    declared_inputs,
    file_digest,
    inventory_paths,
    stable_content_digest,
    write_manifest,
)

GATED_MANIFEST = ROOT / "data" / "GATED_DATA_POINTERS.json"
#: The option tape the producers actually open, one JSON record per session-asset file.
TAPE_INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
#: The frozen partition. The sessions a rebuild produces have to be these sessions.
PARTITION = ROOT / "artifacts" / "rp2_block1_partition" / "partition.json"
SCORECARD_FIELDS = ROOT / "configs" / "rp2_v3_scorecard_fields.json"
MODEL_CONFIG = ROOT / "configs" / "rp2_v3_feature_sets.json"
#: Seeds are part of the run's identity, so they are declared here rather than left to
#: each script's default and discovered afterwards.
SEEDS = {"bootstrap": 650, "lightgbm": 20260818, "dml_folds": 5}


def _peak_memory_bytes(process: subprocess.Popen[bytes]) -> int:
    """Peak working set of a finished child, without adding a dependency for it.

    On Windows the process handle stays valid after exit, so the counter can still be
    read; elsewhere the child's rusage is the honest answer. A platform that offers
    neither records zero rather than a guess.
    """

    if sys.platform == "win32":  # pragma: no cover - platform specific
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        handle = getattr(process, "_handle", None)
        if handle is None:
            return 0
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            int(handle), ctypes.byref(counters), counters.cb
        )
        return int(counters.PeakWorkingSetSize) if ok else 0
    import resource  # pragma: no cover - POSIX only

    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    # Linux reports kilobytes, macOS bytes.
    return int(usage.ru_maxrss * (1024 if sys.platform.startswith("linux") else 1))


def _code_commit() -> str:
    """The commit the run is executing, which is half of what makes it reproducible."""

    return subprocess.run(  # noqa: S603
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def run_step(name: str, command: Sequence[str], run_dir: Path) -> StepRecord:
    """Run one step, timing it, and refuse to accept a step that did not write its outputs."""

    started = time.perf_counter()
    process = subprocess.Popen(list(command), cwd=ROOT)  # noqa: S603 - fixed command list
    process.wait()
    memory = _peak_memory_bytes(process)
    runtime = time.perf_counter() - started
    step = next(candidate for candidate in PIPELINE_STEPS if candidate.name == name)
    if process.returncode != 0:
        raise SystemExit(f"RP2_RUN_STEP_FAILED:{name}:exit={process.returncode}")
    artifacts, content = _digest_outputs(name, run_dir, step.outputs)
    return StepRecord(
        name=name,
        command=tuple(command),
        exit_code=process.returncode,
        runtime_seconds=round(runtime, 3),
        peak_memory_bytes=memory,
        artifacts=artifacts,
        content=content,
    )


def _digest_outputs(
    name: str, run_dir: Path, outputs: Sequence[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Both digests of everything a step was supposed to write.

    The byte digest answers whether the file on disk is the file the step wrote. The stable
    digest answers whether the step produced the same *result*, which is a different
    question: every block artifact stamps itself with the moment it was written, so two
    identical executions differ byte for byte and agree on content.
    """

    artifacts: dict[str, str] = {}
    content: dict[str, str] = {}
    for output in outputs:
        path = run_dir / output
        if not path.is_file():
            # A step that exits zero without writing its output has not run. Accepting it
            # would let the next step read the previous run's file and label the result
            # with this run id.
            raise SystemExit(f"RP2_RUN_STEP_OUTPUT_MISSING:{name}:{output}")
        artifacts[output] = file_digest(path)
        content[output] = stable_content_digest(path)
    return artifacts, content


def _tape_fingerprint(paths: Sequence[Path], *, hash_contents: bool) -> tuple[str, int, int]:
    """A digest of the option tape the producers will open, and what it cost to compute.

    Eighty-five gigabytes across three thousand seven hundred files is too much to read on
    every rebuild for no gain, so the default fingerprint is over each file's path, size
    and modification time: it changes whenever a session is re-acquired, replaced or
    truncated. `--hash-tape-contents` reads every byte instead, and the artifact records
    which of the two was done rather than leaving a reader to assume the stronger one.
    """

    digest = hashlib.sha256()
    total = 0
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            raise SystemExit(f"RP2_RUN_TAPE_INPUT_MISSING:{path.as_posix()}")
        stat = path.stat()
        total += stat.st_size
        if hash_contents:
            digest.update(f"{path.as_posix()}:{file_digest(path)}".encode())
        else:
            digest.update(f"{path.as_posix()}:{stat.st_size}:{stat.st_mtime_ns}".encode())
    return digest.hexdigest(), len(paths), total


def validate_inputs(
    run_dir: Path, *, data_root: Path, forbid_sealed: bool, hash_tape_contents: bool = False
) -> str:
    """Step 1: everything the run will actually read exists, and is identified.

    Three sets of files, not one. The gated pointers are hashed byte for byte, because they
    are small and their digests are already recorded. The one-minute bar stores are hashed
    the same way. The option tape is fingerprinted from the inventory the producers read,
    because that is the list of files Blocks 5 and 6 open - and hashing only the gated
    pointers would leave the provenance unable to tell one acquisition of the tape from
    another.
    """

    from mds650.rp2.bars import BAR_SOURCES

    paths, manifest_digest = declared_inputs(GATED_MANIFEST)
    if not TAPE_INVENTORY.is_file():
        raise SystemExit(f"RP2_RUN_TAPE_INVENTORY_MISSING:{TAPE_INVENTORY.name}")
    tape = inventory_paths(TAPE_INVENTORY)
    bars = [data_root / relative for _, _, relative in BAR_SOURCES]
    if forbid_sealed:
        # Every path a producer will open, not only the ones this run declared. The
        # guarantee `--forbid-sealed-cohorts` makes is about what gets read.
        assert_no_sealed_paths([*paths, data_root, TAPE_INVENTORY, *bars, *tape])

    payload = json.loads(GATED_MANIFEST.read_text(encoding="utf-8"))
    failures: list[str] = []
    for entry in payload.get("files", []):
        path = ROOT / str(entry["path"])
        if not path.is_file():
            failures.append(f"missing:{entry['path']}")
            continue
        recorded = str(entry.get("sha256", ""))
        if recorded and file_digest(path) != recorded:
            failures.append(f"changed:{entry['path']}")
    bar_digests: dict[str, str] = {}
    for name, role, relative in BAR_SOURCES:
        path = data_root / relative
        if not path.is_file():
            failures.append(f"missing_bars:{name}")
            continue
        bar_digests[f"{name}|{role}"] = file_digest(path)
    if failures:
        raise SystemExit("RP2_RUN_INPUT_MANIFEST_INVALID:" + ",".join(sorted(failures)))

    tape_digest, tape_files, tape_bytes = _tape_fingerprint(
        tape, hash_contents=hash_tape_contents
    )
    record = {
        "gated_manifest_sha256": manifest_digest,
        "gated_files": len(payload.get("files", [])),
        "bar_sources_sha256": bar_digests,
        "tape_inventory_sha256": file_digest(TAPE_INVENTORY),
        "tape_fingerprint_sha256": tape_digest,
        "tape_fingerprint_mode": "content" if hash_tape_contents else "path_size_mtime",
        "tape_files": tape_files,
        "tape_bytes": tape_bytes,
    }
    (run_dir / "input_manifest.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # The digest the manifest carries covers all three sets, so changing any real input
    # moves it.
    return hashlib.sha256(canonical_json(record).encode("utf-8")).hexdigest()


def assert_partition_matches(run_dir: Path) -> None:
    """The rebuilt panels cover the frozen partition, session for session.

    The producers load every bar store they can find. Left unchecked, a store that grew
    silently widens the sample and one that lost a file silently shortens it, and either
    way the result is labelled with the same run id as the study it no longer matches.
    """

    import polars as pl

    from mds650.rp2.panel import panel_paths

    partition = json.loads(PARTITION.read_text(encoding="utf-8"))
    panel = pl.read_parquet(panel_paths(run_dir)["b0"], columns=["role", "session_date"])
    breaches: list[str] = []
    for role, expected in partition["roles"].items():
        if not expected["sessions"]:
            continue
        built = panel.filter(pl.col("role") == role)["session_date"].unique()
        if built.len() != int(expected["sessions"]):
            breaches.append(f"{role}:sessions={built.len()}!={expected['sessions']}")
            continue
        first, last = str(built.min()), str(built.max())
        if first != expected["first_session"] or last != expected["last_session"]:
            breaches.append(
                f"{role}:window={first}..{last}!="
                f"{expected['first_session']}..{expected['last_session']}"
            )
    if breaches:
        raise SystemExit("RP2_RUN_PARTITION_MISMATCH:" + ",".join(breaches))


def validate_feature_registry(run_dir: Path) -> Path:
    """Step 6: the core sets resolve *against this run's panels* and meet their floors.

    Importing the registry proves the configuration parses. It does not prove that the
    features it names exist in the panels this run just built, which is the only version
    of the question that can fail.
    """

    from mds650.rp2.feature_registry import (
        assert_minimum_coverage,
        describe_coverage,
        feature_map,
        registry_sha256,
    )
    from mds650.rp2.panel import CORE_SETS, load_merged_panel, panel_paths

    panels = panel_paths(run_dir)
    panel = load_merged_panel(panels["b0"], panels["b1"], panels["b2"])
    for label in CORE_SETS.values():
        missing = [name for name in feature_map(label) if name not in panel.columns]
        if missing:
            # Absent is a different failure from thinly covered, and it has to be said
            # first: a coverage report over a column that does not exist is a report about
            # nothing.
            raise SystemExit(f"RP2_RUN_CORE_FEATURE_ABSENT:{label}:{','.join(sorted(missing))}")
    assert_minimum_coverage(panel, *CORE_SETS.values())
    report = {
        "registry_sha256": registry_sha256(),
        "rows": panel.height,
        "coverage": describe_coverage(panel, *CORE_SETS.values()),
    }
    path = run_dir / "feature_registry_report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def construct_common_masks(run_dir: Path, roles: Sequence[str]) -> Path:
    """Step 7: one evaluation mask per role, hashed, before any model is fitted.

    The mask is what makes a nested comparison nested. Recording its digest here - rather
    than only inside whichever producer happened to compute it - is what lets a reader
    confirm afterwards that the base and the expanded model were scored on one sample.
    """

    import numpy as np
    import polars as pl

    from mds650.rp2.panel import (
        common_evaluation_mask,
        load_merged_panel,
        mask_sha256,
        panel_paths,
    )

    panels = panel_paths(run_dir)
    panel = load_merged_panel(panels["b0"], panels["b1"], panels["b2"])
    if "rv30" not in panel.columns:
        raise SystemExit("RP2_RUN_TARGET_ABSENT:rv30")
    masks: dict[str, object] = {}
    for role in roles:
        frame = panel.filter(pl.col("role") == role)
        if frame.is_empty():
            raise SystemExit(f"RP2_RUN_ROLE_EMPTY:{role}")
        target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
        mask = common_evaluation_mask(frame, target)
        masks[role] = {
            "rows": int(frame.height),
            "usable_rows": int(mask.sum()),
            "mask_sha256": mask_sha256(mask),
        }
    path = run_dir / "common_masks.json"
    path.write_text(json.dumps(masks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def build_scorecard(run_dir: Path, manifest: RunManifest) -> dict[str, object]:
    """Step 11: assemble the scorecard the schema requires, and fail on a missing field."""

    from mds650.rp2.scorecard import assemble_scorecard, render_scorecard

    scorecard = assemble_scorecard(run_dir, manifest)
    (run_dir / "scorecard.json").write_text(
        json.dumps(scorecard, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (run_dir / "scorecard.md").write_text(render_scorecard(scorecard), encoding="utf-8")
    return scorecard


def verify_artifacts(run_dir: Path, steps: Sequence[StepRecord]) -> None:
    """Step 13: what was written is still what was recorded."""

    for step in steps:
        for name, digest in step.artifacts.items():
            assert_artifact_stable(run_dir / name, digest)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "rp2_v3")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--roles", nargs="+", default=["D", "V"])
    parser.add_argument("--forbid-sealed-cohorts", action="store_true", default=True)
    parser.add_argument(
        "--allow-sealed-cohorts", dest="forbid_sealed_cohorts", action="store_false"
    )
    parser.add_argument(
        "--skip-panels",
        action="store_true",
        help="reuse the panels already in the run directory instead of rebuilding them",
    )
    parser.add_argument(
        "--hash-tape-contents",
        action="store_true",
        help="read all 85 GB of option tape to digest it, instead of path/size/mtime",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.dry_run:
        print(f"RP2-v3 pipeline, run id {args.run_id}, roles {' '.join(args.roles)}")
        for index, step in enumerate(PIPELINE_STEPS, start=1):
            print(f"{index:2d}. {step.name} - {step.description}")
        return 0

    run_dir = Path(args.output_root) / str(args.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat()
    python = [sys.executable]
    panel_flags = ["--panel-root", str(run_dir)]

    def block_flags(directory: str, *, data: bool = False) -> list[str]:
        """Each producer writes into its own directory inside the run.

        Block 4 and Block 8 both write a file named `ladder.json`. Pointed at one flat
        directory the second would replace the first, and the baseline comparison the B0
        block produced would be gone with nothing recording that it had ever existed.
        """

        flags = ["--output-dir", str(run_dir / directory)]
        return ["--data-root", str(args.data_root), *flags] if data else flags

    # Before anything is written: if this run id already holds a run, it has to be the
    # same run. Discovering that at the end would mean discovering it beside artifacts the
    # producers had already overwritten.
    identity = RunManifest(
        run_id=str(args.run_id),
        code_commit=_code_commit(),
        data_root=str(args.data_root),
        roles=tuple(args.roles),
        feature_registry_sha256=registry_sha256(),
        input_manifest_sha256="",
        model_config_sha256=file_digest(MODEL_CONFIG),
        seeds=SEEDS,
        steps=(),
        started_at_utc=started,
        finished_at_utc=started,
    )
    assert_run_identity_unchanged(run_dir, identity)

    steps: list[StepRecord] = []
    manifest_digest = validate_inputs(
        run_dir,
        data_root=Path(args.data_root),
        forbid_sealed=args.forbid_sealed_cohorts,
        hash_tape_contents=args.hash_tape_contents,
    )
    steps.append(
        StepRecord(
            name="validate-input-manifests",
            command=("internal", "validate_inputs"),
            exit_code=0,
            runtime_seconds=0.0,
            peak_memory_bytes=0,
            artifacts={"input_manifest.json": file_digest(run_dir / "input_manifest.json")},
            content={
                "input_manifest.json": stable_content_digest(run_dir / "input_manifest.json")
            },
        )
    )

    panel_steps = (
        (
            "build-targets",
            [
                *python,
                "scripts/rp2_block3_target_panel.py",
                *block_flags("rp2_block3_target", data=True),
            ],
        ),
        (
            "build-b0",
            [*python, "scripts/rp2_block4_b0_panel.py", *block_flags("rp2_block4_b0", data=True)],
        ),
        # B1 and B2 are sampled at the origins of this run's own B0 panel, so they are
        # told where that panel is rather than finding the previous run's.
        (
            "build-b1",
            [
                *python,
                "scripts/rp2_block5_surface_panel.py",
                *block_flags("rp2_block5_surface", data=True),
                *panel_flags,
            ],
        ),
        (
            "build-b2",
            [
                *python,
                "scripts/rp2_block6_flow_panel.py",
                *block_flags("rp2_block6_flow", data=True),
                *panel_flags,
            ],
        ),
    )
    for name, command in panel_steps:
        if args.skip_panels:
            step = next(candidate for candidate in PIPELINE_STEPS if candidate.name == name)
            missing = [output for output in step.outputs if not (run_dir / output).is_file()]
            if missing:
                raise SystemExit(f"RP2_RUN_PANEL_MISSING:{name}:{','.join(missing)}")
            steps.append(
                StepRecord(
                    name=name,
                    command=("reused", *command[1:]),
                    exit_code=0,
                    runtime_seconds=0.0,
                    peak_memory_bytes=0,
                    artifacts={output: file_digest(run_dir / output) for output in step.outputs},
                )
            )
            continue
        steps.append(run_step(name, command, run_dir))

    assert_partition_matches(run_dir)

    # Steps 6 and 7 run in this process against the panels this run just built. Shelling
    # out to an import would prove the configuration parses, which is not the question
    # that can fail: the question is whether the features the registry names exist in
    # *these* panels and whether the mask they imply is non-empty.
    internal_steps: tuple[tuple[str, Callable[[], Path]], ...] = (
        ("validate-feature-registry", lambda: validate_feature_registry(run_dir)),
        ("construct-common-masks", lambda: construct_common_masks(run_dir, args.roles)),
    )
    for name, produce in internal_steps:
        started_step = time.perf_counter()
        artifact = produce()
        steps.append(
            StepRecord(
                name=name,
                command=("internal", name),
                exit_code=0,
                runtime_seconds=round(time.perf_counter() - started_step, 3),
                peak_memory_bytes=0,
                artifacts={artifact.name: file_digest(artifact)},
                content={artifact.name: stable_content_digest(artifact)},
            )
        )

    for name, script, directory in (
        ("fit-model-ladder", "scripts/rp2_block8_ladder.py", "rp2_block8_ladder"),
        ("run-dml-diagnostics", "scripts/rp2_block7_dml.py", "rp2_block7_dml"),
        ("run-incremental-inference", "scripts/rp2_block10_inference.py", "rp2_block10_inference"),
    ):
        command = [*python, script, *block_flags(directory), *panel_flags]
        steps.append(run_step(name, command, run_dir))

    manifest = RunManifest(
        run_id=str(args.run_id),
        code_commit=_code_commit(),
        data_root=str(args.data_root),
        roles=tuple(args.roles),
        feature_registry_sha256=registry_sha256(),
        input_manifest_sha256=manifest_digest,
        model_config_sha256=file_digest(MODEL_CONFIG),
        seeds=SEEDS,
        steps=tuple(steps),
        started_at_utc=started,
        finished_at_utc=datetime.now(UTC).isoformat(),
    )
    build_scorecard(run_dir, manifest)
    steps.append(
        StepRecord(
            name="generate-scorecard",
            command=("internal", "build_scorecard"),
            exit_code=0,
            runtime_seconds=0.0,
            peak_memory_bytes=0,
            artifacts={
                "scorecard.json": file_digest(run_dir / "scorecard.json"),
                "scorecard.md": file_digest(run_dir / "scorecard.md"),
            },
            content={
                "scorecard.json": stable_content_digest(run_dir / "scorecard.json"),
                "scorecard.md": stable_content_digest(run_dir / "scorecard.md"),
            },
        )
    )

    manifest = RunManifest(
        **{
            **{
                field: getattr(manifest, field)
                for field in (
                    "run_id",
                    "code_commit",
                    "data_root",
                    "roles",
                    "feature_registry_sha256",
                    "input_manifest_sha256",
                    "model_config_sha256",
                    "seeds",
                    "started_at_utc",
                )
            },
            "steps": tuple(steps),
            "finished_at_utc": datetime.now(UTC).isoformat(),
        }
    )
    write_manifest(run_dir, manifest)
    verify_artifacts(run_dir, steps)
    digest = str(manifest.as_record()["scientific_sha256"])
    print(f"run {manifest.run_id}: {len(steps)} steps, scientific hash {digest[:16]}")
    print(f"registry {REGISTRY_CONFIG.name}, scorecard fields {SCORECARD_FIELDS.name}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
