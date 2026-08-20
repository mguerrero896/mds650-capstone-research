"""Publish one RP2-v3 run to Supabase, atomically, from the artifacts it produced.

The publication is a single call to `public.publish_rp2_v3`, because a function body is a
transaction. Eight REST calls from a script can leave a run marked RUNNING with half its
results published and the previous run already stood down, and nothing in the database
would say which half is missing.

Nothing origin-level is sent. What leaves the repository is the run's identity, the digests
of its inputs, one row per block outcome and one row per nested contrast - the same
aggregates the public report is written from.

    $env:SUPABASE_SERVICE_KEY = "..."
    uv run python scripts/publish_rp2_v3_supabase.py --run-root artifacts/rp2_v3/<run_id>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(ROOT / "src"))

from mds650.rp2.inference import inference_config_digest  # noqa: E402
from mds650.rp2.run_manifest import (  # noqa: E402
    IDENTITY_FILE,
    TAPE_INVENTORY,
    assert_manifest_identity_intact,
    file_digest,
    inventory_paths,
    normalised_digest,
    stable_content_digest,
    tape_fingerprint,
)

PROJECT_REF = "eqpyjikcewqaegnbaemf"
REST = f"https://{PROJECT_REF}.supabase.co/rest/v1"
SPEC_VERSION = "rp2-v3"
#: Providers the ingestion contract allows. A derived panel is `derived`; anything else
#: has to name the provider whose licence it is held under.
DERIVED = "derived"


def _read(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def contrast_rows(ladder: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    """One row per nested contrast, per role, per primary family.

    Only the families the research contract decides on are published. The robustness
    families stay in the artifact: a reader who wants them can hash the artifact and read
    it, and a table that mixes deciding and robustness rows invites a later query that
    forgets the difference.
    """

    from mds650.rp2.ladder import PRIMARY_MODELS

    rows: list[dict[str, Any]] = []
    for role in ("D", "V"):
        role_block = ladder.get(role, {})
        if role_block.get("status") != "MEASURED":
            continue
        for family in PRIMARY_MODELS:
            model = role_block.get("models", {}).get(family)
            if not model:
                continue
            for label, contrast in model.get("contrasts", {}).items():
                raw = contrast.get("raw", {})
                if not raw.get("common_mask_sha256"):
                    raise SystemExit(f"RP2_PUBLISH_CONTRAST_WITHOUT_MASK:{role}:{family}:{label}")
                rows.append(
                    {
                        "role": role,
                        "model_family": family,
                        "base_information_set": raw["base_information_set"],
                        "expanded_information_set": raw["expanded_information_set"],
                        "estimate": raw["estimate"],
                        "ci_low": raw["ci_low"],
                        "ci_high": raw["ci_high"],
                        "p_value": raw["p_value"],
                        "sessions": raw["sessions"],
                        "block_length": raw["block_length"],
                        "mde": raw["mde"],
                        "equivalence_bound": raw["equivalence_bound"],
                        "common_mask_sha256": raw["common_mask_sha256"],
                    }
                )
    return rows


def assert_artifacts_match_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    """Every artifact this publisher reads is the one the run recorded.

    The manifest is written when the run finishes; the publication happens afterwards. A
    file changed in between would be read and published as though the run had produced it,
    and the digests in the manifest would say otherwise while nobody compared them.
    """

    for step in manifest.get("steps", []):
        artifacts = step.get("artifacts", {})
        content = step.get("content", {})
        # The two maps describe the same files, and only one of them is signed. An artifact
        # present in `artifacts` and absent from `content` contributes nothing to the run's
        # scientific identity while looking fully recorded.
        if set(artifacts) != set(content):
            missing = sorted(set(artifacts) ^ set(content))
            raise SystemExit(f"RP2_PUBLISH_ARTIFACT_UNSIGNED:{step.get('name')}:{missing[0]}")
        for name, digest in artifacts.items():
            path = run_dir / name
            if not path.is_file():
                raise SystemExit(f"RP2_PUBLISH_ARTIFACT_MISSING:{name}")
            # Against the signed digest, not only the byte digest beside the file.
            # `scientific_part` hashes `content` and deliberately not `artifacts`, so an
            # edit that rewrote a result and the byte digest describing it left the
            # manifest's own identity intact and satisfied this check with its own account
            # of itself. `content` cannot be rewritten without moving `scientific_sha256`,
            # which `assert_manifest_identity_intact` recomputes.
            if stable_content_digest(path) != content[name]:
                raise SystemExit(f"RP2_PUBLISH_ARTIFACT_CHANGED:{name}")
            if file_digest(path) != digest:
                raise SystemExit(f"RP2_PUBLISH_ARTIFACT_CHANGED:{name}")


def _mask_digest(scorecard: dict[str, Any]) -> str:
    """One digest identifying the evaluation masks of every role the run fitted.

    A single role's mask under a run-level field says the other role's contrasts were scored
    on rows they never saw. The per-contrast digests remain the authority; this identifies
    the set.
    """

    masks = {
        role: values.get("common_mask_sha256")
        for family in scorecard.get("forecast", {}).values()
        for role, values in family.items()
    }
    if not masks or any(value is None for value in masks.values()):
        raise SystemExit("RP2_PUBLISH_MASK_DIGEST_INCOMPLETE")
    canonical = json.dumps(masks, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: The artifact that carries each step's outcome. Taking whichever mapping key sorted first
#: published a panel's digest as Block 3's result while the block registry names its
#: comparison, so the row pointed at a file that is not the finding.
#: Pipeline step -> (canonical RP2 block id, the artifact that is that block's result).
#:
#: The block register in `scripts/sync_supabase_rp2_blocks.py` numbers the research blocks
#: `03` through `11`, and `rp2_block_results` keys its one-current-row index on that id.
#: Publishing under step names would open a second, disjoint namespace: `03` would never be
#: superseded, a join on it would find nothing, and the pipeline's administrative steps
#: would appear in the register as though they were research blocks.
#:
#: Blocks `09` and `11` are absent because this pipeline does not rebuild them - the
#: generalization cohort is sealed and the economics are frozen - so their existing rows
#: stay current, which is what a run that did not remeasure them should leave behind.
RESULT_BLOCKS: Final[dict[str, tuple[str, str]]] = {
    "build-targets": ("03", "rp2_block3_target/comparison.json"),
    "build-b0": ("04", "rp2_block4_b0/ladder.json"),
    "build-b1": ("05", "rp2_block5_surface/surface_coverage.json"),
    "build-b2": ("06", "rp2_block6_flow/flow_coverage.json"),
    "run-dml-diagnostics": ("07", "rp2_block7_dml/dml.json"),
    "fit-model-ladder": ("08", "rp2_block8_ladder/ladder.json"),
    "run-incremental-inference": ("10", "rp2_block10_inference/inference.json"),
}


def _block_status(run_dir: Path, step: dict[str, Any]) -> str:
    """What the block's own artifact says happened, falling back to the exit code.

    A producer can complete normally and record `INSUFFICIENT_ROWS` for a role: the process
    returns zero and nothing was measured. Publishing that as `MEASURED` because the exit
    code was zero states the opposite of what the artifact says.
    """

    if step.get("exit_code") != 0:
        return "FAILED"
    designated = _designated_artifact(step)
    if designated is None or not (run_dir / designated).is_file():
        return "MEASURED"
    try:
        payload = json.loads((run_dir / designated).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "MEASURED"
    statuses = {
        str(value.get("status"))
        for value in payload.values()
        if isinstance(value, dict) and value.get("status")
    }
    unmeasured = sorted(status for status in statuses if status != "MEASURED")
    if unmeasured:
        return unmeasured[0]
    if statuses:
        return "MEASURED"
    # Blocks 3 to 6 write a coverage or comparison report rather than a role-keyed result,
    # so there is no status to read. There is a row count, and a block that wrote an empty
    # panel measured nothing however its process exited.
    for key in ("rows", "panel_rows"):
        if isinstance(payload.get(key), int):
            return "MEASURED" if payload[key] > 0 else "EMPTY_PANEL"
    return "MEASURED"


def _block_result_digest(step: dict[str, Any]) -> str | None:
    """The digest of the artifact that *is* this step's result, or nothing if it has none."""

    designated = _designated_artifact(step)
    if designated is None:
        return None
    digest = step.get("artifacts", {}).get(designated)
    return str(digest) if digest else None


def _designated_artifact(step: dict[str, Any]) -> str | None:
    """The artifact that is this step's block result, if the step produces one."""

    entry = RESULT_BLOCKS.get(str(step.get("name")))
    return entry[1] if entry else None


def _verified_gated_manifest(resolved: dict[str, Any]) -> str:
    """The gated manifest as it is now, checked against the one the run read.

    It is the source of truth for which licensed files a run may open, and it was the last
    input published from its run-time digest alone: the row would have carried that digest
    beside the current file's size, describing two different versions of the same manifest.
    """

    recorded = str(resolved["gated_manifest_sha256"])
    current = normalised_digest(ROOT / "data" / "GATED_DATA_POINTERS.json")
    if current != recorded:
        raise SystemExit(f"RP2_PUBLISH_GATED_MANIFEST_CHANGED:{current[:12]}!={recorded[:12]}")
    return recorded


def _verified_tape_fingerprint(resolved: dict[str, Any]) -> str:
    """The tape as it is now, checked against the tape the run read.

    The bar stores are re-digested before their lineage is published and the tape was not,
    although it is the largest input and the one a same-path replacement is least visible
    in: neither the inventory file nor any step artifact changes when a file is swapped for
    different bytes at the same path. Re-read in whichever mode the run recorded, so the
    check is as strong as the record it is checking.
    """

    # The inventory's own rows, first. The fingerprints below cover the files it points at
    # and their filesystem metadata, so an inventory edited to reassign a session or a role
    # produces the same tape identity while describing a different experiment.
    inventory = normalised_digest(TAPE_INVENTORY)
    if inventory != str(resolved.get("tape_inventory_sha256")):
        raise SystemExit(
            f"RP2_PUBLISH_TAPE_INVENTORY_CHANGED:{inventory[:12]}"
            f"!={str(resolved.get('tape_inventory_sha256'))[:12]}"
        )
    recorded = str(resolved["tape_fingerprint_sha256"])
    identity, freshness, _, _ = tape_fingerprint(
        inventory_paths(TAPE_INVENTORY),
        hash_contents=resolved.get("tape_fingerprint_mode") == "content",
    )
    if identity != recorded:
        raise SystemExit(f"RP2_PUBLISH_TAPE_CHANGED:{identity[:12]}!={recorded[:12]}")
    if freshness != str(resolved.get("tape_freshness_sha256")):
        raise SystemExit("RP2_PUBLISH_TAPE_CHANGED:freshness")
    return recorded


def _bar_inputs(resolved: dict[str, Any], data_root: Path) -> list[dict[str, Any]]:
    """The bar stores as they are: their real relative paths and their real sizes.

    An invented path and a one-byte size make the lineage unusable for the thing lineage is
    for - finding the file a number was built from.
    """

    from mds650.rp2.bars import BAR_SOURCES

    digests = resolved.get("bar_sources_sha256", {})
    rows: list[dict[str, Any]] = []
    for name, role, relative in BAR_SOURCES:
        key = f"{name}|{role}"
        if key not in digests:
            continue
        path = data_root / relative
        if not path.is_file():
            # Publishing a one-byte size beside a path and a digest that describe a real
            # parquet makes the row describe a file that does not exist.
            raise SystemExit(f"RP2_PUBLISH_BAR_INPUT_MISSING:{relative}")
        # And it is still the file the run read. Pairing the run-time digest with today's
        # size describes neither the file the results were built on nor the file on disk,
        # which is the one question lineage is asked.
        current = file_digest(path)
        if current != digests[key]:
            raise SystemExit(
                f"RP2_PUBLISH_BAR_INPUT_CHANGED:{relative}:{current[:12]}!={digests[key][:12]}"
            )
        rows.append(
            {
                "input_name": f"bars_{name}",
                "path": relative,
                "provider": "fmp",
                "sha256": digests[key],
                "bytes": path.stat().st_size,
                "rows": None,
                "schema_sha256": None,
                "time_min": None,
                "time_max": None,
            }
        )
    return rows


#: Which window results may be published under. `adopted` is null until the owner of the
#: research programme records the decision; see `docs/rp2_v3/STUDY_WINDOW.md`.
#: The tracked path, and only the tracked path. An environment variable pointing somewhere
#: else would let an operator or a stale runner substitute a window without the recorded
#: configuration change the study rule requires, and neither the commit check nor the
#: dirty-worktree check can see a file outside the repository.
STUDY_WINDOW_CONFIG: Final = ROOT / "configs" / "rp2_v3_study_window.json"


def assert_study_window_decided(
    enforced: dict[str, Any], configured: dict[str, Any]
) -> None:
    """Publish only under a window somebody chose, and only the window the run used.

    The repository states two: `AGENTS.md` freezes twelve months from 2025-07-21, and every
    artifact was built on the partition, 2024-08-02 through 2026-07-17. A code change cannot
    settle that - adopting the twelve-month window discards roughly 309 of the 389
    development sessions, which is a different study rather than a correction - so this
    refuses to publish while the choice is unrecorded instead of publishing under whichever
    window the run happened to use.
    """

    adopted = configured.get("adopted")
    if not adopted:
        raise SystemExit(
            "RP2_PUBLISH_STUDY_WINDOW_UNDECIDED:"
            f"set 'adopted' in {STUDY_WINDOW_CONFIG.name} "
            "(see docs/rp2_v3/STUDY_WINDOW.md)"
        )
    window = configured.get("candidates", {}).get(adopted)
    if not window:
        raise SystemExit(f"RP2_PUBLISH_STUDY_WINDOW_UNKNOWN:{adopted}")
    first = min(str(role["first_session"]) for role in enforced.values())
    last = max(str(role["last_session"]) for role in enforced.values())
    # The configured end is exclusive, because the rule it comes from is written that way:
    # a window of `2025-07-21` through `2026-07-21` (end exclusive) has its last trading
    # session before July 21, not on it. Comparing an exclusive bound against an observed
    # session would refuse every correctly built run.
    start, final = window.get("first_session"), window.get("last_session")
    if not start or not final:
        # `last_session` is the final trading session inside the window, which the calendar
        # decides rather than the rule: a window written end-exclusive does not say which
        # day precedes its end. Until it is recorded, containment is all that could be
        # checked, and containment accepts a run that covers a fortnight of twelve months.
        raise SystemExit(
            f"RP2_PUBLISH_STUDY_WINDOW_INCOMPLETE:{adopted}:"
            f"record 'last_session' in {STUDY_WINDOW_CONFIG.name}"
        )
    if (first, last) != (str(start), str(final)):
        raise SystemExit(
            f"RP2_PUBLISH_STUDY_WINDOW_MISMATCH:{adopted}:"
            f"{first}..{last}!={start}..{final}"
        )


def assert_run_id_is_the_one_that_ran(run_dir: Path, manifest: dict[str, Any]) -> None:
    """The name the results are published under is the name that produced them.

    `scientific_part_of_record` leaves the run id out on purpose - the same inputs rebuilt
    under a new label are the same experiment - so an edited `run_id` passes the identity
    check and every artifact digest still matches. The run wrote its own name into
    `run_identity.json` before it produced anything, and that is what this compares against.
    """

    identity_path = run_dir / IDENTITY_FILE
    if not identity_path.is_file():
        raise SystemExit(f"RP2_PUBLISH_RUN_IDENTITY_MISSING:{identity_path.name}")
    identity = _read(identity_path)
    # The directory the run wrote into is named after it. The marker is a file and can be
    # edited alongside the manifest; the directory name is a third thing to have to keep
    # consistent, and it is the one the artifacts actually sit inside.
    if run_dir.name != manifest.get("run_id"):
        raise SystemExit(
            f"RP2_PUBLISH_RUN_ID_MISMATCH:directory:{run_dir.name}!={manifest.get('run_id')}"
        )
    for field in ("run_id", "code_commit"):
        if identity.get(field) != manifest.get(field):
            raise SystemExit(
                f"RP2_PUBLISH_RUN_ID_MISMATCH:{field}:"
                f"{identity.get(field)}!={manifest.get(field)}"
            )


def assert_published_at_the_run_commit(manifest: dict[str, Any]) -> None:
    """The code publishing the run is the code that produced it.

    The inference configuration digest is computed here, from the constants in the working
    tree. Publishing from a different commit would record the settings of code the run never
    used, which is the drift this whole discipline exists to prevent.
    """

    import subprocess

    head = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    if head != manifest.get("code_commit"):
        raise SystemExit(
            f"RP2_PUBLISH_COMMIT_MISMATCH:{head[:12]}!={str(manifest.get('code_commit'))[:12]}"
        )
    # And the tree is that commit. An inference constant edited without committing leaves
    # `rev-parse` agreeing while the digest is taken from something the run never ran.
    status = subprocess.run(  # noqa: S603
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    dirty = [line for line in status.splitlines() if line.strip() and not line.startswith("??")]
    if dirty:
        raise SystemExit("RP2_PUBLISH_WORKTREE_DIRTY:" + ",".join(line[3:] for line in dirty[:5]))


def build_payload(run_dir: Path, *, branch: str) -> dict[str, Any]:
    """Assemble what the transaction needs, from the run's own manifest and artifacts."""

    manifest = _read(run_dir / "run_manifest.json")
    # Before anything is read out of it. The artifact check below compares files against
    # the digests this manifest records; if the manifest itself was edited afterwards,
    # those digests are the edit's own account of itself.
    try:
        assert_manifest_identity_intact(manifest)
    except (ValueError, KeyError) as error:
        raise SystemExit(f"RP2_PUBLISH_MANIFEST_ALTERED:{error}") from error
    assert_run_id_is_the_one_that_ran(run_dir, manifest)
    assert_artifacts_match_manifest(run_dir, manifest)
    scorecard = _read(run_dir / "scorecard.json")
    ladder = _read(run_dir / "rp2_block8_ladder" / "ladder.json")
    run_id = str(manifest["run_id"])

    artifacts = manifest.get("steps", [])
    # What the run *read*, from step 1's own record. Populating this from the step outputs
    # described the panels and reports the run produced, so a consumer following
    # `ingestion_inputs` to find out what the results were built on found the results.
    resolved = _read(run_dir / "input_manifest.json")
    assert_study_window_decided(
        resolved.get("study_window_enforced", {}), _read(STUDY_WINDOW_CONFIG)
    )
    inputs = [
        {
            "input_name": "gated_manifest",
            "path": "data/GATED_DATA_POINTERS.json",
            "provider": DERIVED,
            "sha256": _verified_gated_manifest(resolved),
            # The file's size. Publishing the entry count here while `path` and `sha256`
            # identify the file makes the row disagree with itself.
            "bytes": (ROOT / "data" / "GATED_DATA_POINTERS.json").stat().st_size,
            "rows": resolved.get("gated_files"),
            "schema_sha256": None,
            "time_min": None,
            "time_max": None,
        },
        {
            "input_name": "option_tape",
            "path": "artifacts/rp2_block1_partition/inventory.jsonl",
            "provider": DERIVED,
            "sha256": _verified_tape_fingerprint(resolved),
            "bytes": int(resolved["tape_bytes"]),
            "rows": int(resolved["tape_files"]),
            "schema_sha256": resolved["tape_inventory_sha256"],
            "time_min": None,
            "time_max": None,
        },
        *_bar_inputs(resolved, Path(str(manifest["data_root"]))),
    ]

    blocks = [
        {
            "block_id": RESULT_BLOCKS[str(step["name"])][0],
            "status": _block_status(run_dir, step),
            "verdict": "SEE_ARTIFACT",
            "document": "docs/rp2_v3/REBUILD_RUNBOOK.md",
            "artifact_sha256": digest,
        }
        for step in artifacts
        if str(step["name"]) in RESULT_BLOCKS
        for digest in [_block_result_digest(step)]
        if digest is not None
    ]

    return {
        "run": {
            "run_id": run_id,
            "code_commit": manifest["code_commit"],
            "inputs_sha256": manifest["input_manifest_sha256"],
            "spec_version": SPEC_VERSION,
            "branch_name": branch,
            "feature_registry_sha256": manifest["feature_registry_sha256"],
            "model_config_sha256": manifest["model_config_sha256"],
            # The settings a contrast is computed under, not the run's scientific hash:
            # that covers the commit, the inputs and the step outputs, and tells a reader
            # nothing about the block length, the bootstrap or the equivalence margin.
            "inference_config_sha256": inference_config_digest(),
            # A digest over every role's mask, not one role's. The run-level field used to
            # carry D's, which attributed the V contrasts to rows they were never scored
            # on; each contrast row still carries its own.
            "common_mask_sha256": _mask_digest(scorecard),
            # The run's own identity digest, recomputed above before anything was read out
            # of the manifest. Carried as a field rather than only inside the note: a digest
            # a reader can reach only by parsing prose cannot be checked or joined on.
            "scientific_sha256": manifest["scientific_sha256"],
            "note": f"RP2-v3 rebuild, scientific hash {manifest['scientific_sha256'][:16]}",
        },
        "inputs": inputs,
        "blocks": blocks,
        "contrasts": contrast_rows(ladder, run_id),
    }


def publish(payload: dict[str, Any], key: str, *, timeout: float = 120.0) -> dict[str, Any]:
    """One call, one transaction. A failure is recorded by a separate call, not by a retry."""

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout, headers=headers) as client:
        try:
            response = client.post(f"{REST}/rpc/publish_rp2_v3", json={"payload": payload})
        except httpx.HTTPError as error:
            # Name resolution, connection setup and response reading are how a publication
            # most often fails to happen at all. Letting the exception leave here skipped
            # the failure record entirely, so the attempt left no trace anywhere - which is
            # the state the separate record exists to prevent.
            raise SystemExit(
                f"RP2_PUBLISH_TRANSPORT_FAILED:{type(error).__name__}:{error}"
                f"{_record_failure(client, payload, f'{type(error).__name__}: {error}')}"
            ) from error
        if response.status_code not in (200, 201):
            unrecorded = _record_failure(client, payload, response.text[:400])
            raise SystemExit(
                f"RP2_PUBLISH_FAILED:{response.status_code}:{response.text[:300]}{unrecorded}"
            )
        return dict(response.json())


def _record_failure(client: httpx.Client, payload: dict[str, Any], reason: str) -> str:
    """Write the failed attempt down, and say so when even that could not be written.

    A rollback leaves no trace, so the failure is recorded by its own call - and that call
    can fail too. Discarding its response would report an unrecorded failure as an audited
    one, which is the state this record exists to prevent.
    """

    try:
        recorded = client.post(
            f"{REST}/rpc/record_rp2_v3_failure",
            json={"failed_run_id": payload["run"]["run_id"], "reason": reason},
        )
    except httpx.HTTPError as error:
        return f":RP2_FAILURE_UNRECORDED:{type(error).__name__}"
    if recorded.status_code not in (200, 201, 204):
        return f":RP2_FAILURE_UNRECORDED:{recorded.status_code}:{recorded.text[:120]}"
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--branch", default="results/rp2-v3-rebuild")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # Before anything is assembled: the inference-configuration digest below is computed
    # from the working tree, so publishing from another commit would record settings the run
    # never used.
    assert_published_at_the_run_commit(_read(args.run_root / "run_manifest.json"))
    payload = build_payload(args.run_root, branch=args.branch)
    if args.dry_run:
        # Whole, not the first four thousand characters. The step this supports is an
        # operator reading what is about to be published, and a truncated payload drops
        # exactly the contrast estimates and lineage fields that reading is for.
        review = args.run_root / "publication_payload.json"
        review.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        print(f"[dry-run] written to {review}")
        print(
            f"[dry-run] {len(payload['inputs'])} inputs, {len(payload['blocks'])} blocks, "
            f"{len(payload['contrasts'])} contrasts"
        )
        return 0

    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        raise SystemExit("SUPABASE_SERVICE_KEY missing (User env var; see DATA_ACCESS.md).")
    result = publish(payload, key)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
