"""Publication is one transaction, publishes only aggregates, and records its failures.

The failure this guards against is not a wrong number. It is a database that half agrees
with itself: a run marked RUNNING with some of its results published and the previous
run's rows already stood down, so the current answer is missing and nothing says so.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]

MASK = "a" * 64
COMMIT = "b" * 40


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _contrast(base: str, expanded: str) -> dict[str, Any]:
    return {
        "raw": {
            "estimate": 0.004,
            "ci_low": 0.001,
            "ci_high": 0.007,
            "p_value": 0.001,
            "sessions": 156,
            "block_length": 5,
            "mde": 0.002,
            "equivalence_bound": 0.0015,
            "common_mask_sha256": MASK,
            "base_information_set": base,
            "expanded_information_set": expanded,
            "model_family": "gamma_glm",
        }
    }


def _run_dir(tmp_path: Path) -> Path:
    from mds650.rp2.ladder import PRIMARY_MODELS

    run = tmp_path / "rp2-v3-test-001"
    (run / "rp2_block8_ladder").mkdir(parents=True)
    ladder = {
        role: {
            "status": "MEASURED",
            "models": {
                family: {
                    "qlike": {"B0": 0.14},
                    "contrasts": {
                        "delta_b1": _contrast("B0", "B0+B1"),
                        "delta_b2_given_b1": _contrast("B0+B1", "B0+B1+B2"),
                    },
                }
                for family in PRIMARY_MODELS
            },
        }
        for role in ("D", "V")
    }
    (run / "rp2_block8_ladder" / "ladder.json").write_text(json.dumps(ladder), encoding="utf-8")
    (run / "scorecard.json").write_text(
        json.dumps(
            {
                "forecast": {
                    "gamma_glm": {
                        "D": {"common_mask_sha256": MASK},
                        "V": {"common_mask_sha256": "b" * 64},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    # A bar store of this fixture's own, so the test says what it means: it is about what
    # the publisher does with the digests, not about which parquet happens to sit on the
    # machine running it.
    store = _bar_store(tmp_path)
    (run / "input_manifest.json").write_text(
        json.dumps(
            {
                "gated_manifest_sha256": "1" * 64,
                "gated_files": 15,
                "bar_sources_sha256": _bar_digests(store),
                "tape_inventory_sha256": "3" * 64,
                "tape_fingerprint_sha256": "4" * 64,
                "tape_files": 3717,
                "tape_bytes": 84_600_000_000,
            }
        ),
        encoding="utf-8",
    )
    # A real record, not a hand-written stand-in: the publisher recomputes the manifest's
    # own scientific digest, so a fixture whose digest does not describe its own contents
    # is not a manifest the publisher would ever have been given.
    record = _manifest_record(data_root=str(store))
    (run / "run_manifest.json").write_text(json.dumps(record), encoding="utf-8")
    # The run writes its own name down before it produces anything, so a manifest relabelled
    # afterwards has something to disagree with.
    from mds650.rp2.run_manifest import IDENTITY_FILE

    (run / IDENTITY_FILE).write_text(json.dumps(record), encoding="utf-8")
    return run


def _bar_store(tmp_path: Path) -> Path:
    from mds650.rp2.bars import BAR_SOURCES

    store = tmp_path / "store"
    for index, (_name, _role, relative) in enumerate(BAR_SOURCES):
        path = store / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"bars {index}".encode())
    return store


def _bar_digests(store: Path) -> dict[str, str]:
    from mds650.rp2.bars import BAR_SOURCES
    from mds650.rp2.run_manifest import file_digest

    return {
        f"{name}|{role}": file_digest(store / relative)
        for name, role, relative in BAR_SOURCES
    }


def _manifest_record(
    data_root: str = "D:/MDS650",
    *,
    artifacts: dict[str, str] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    from mds650.rp2.run_manifest import RunManifest, StepRecord

    record = RunManifest(
        run_id="rp2-v3-test-001",
        code_commit=COMMIT,
        data_root=data_root,
        roles=("D", "V"),
        feature_registry_sha256="d" * 64,
        input_manifest_sha256="c" * 64,
        model_config_sha256="e" * 64,
        seeds={"numpy": 650},
        steps=(
            StepRecord(
                name="fit-model-ladder",
                command=("python", "scripts/rp2_block8_ladder.py"),
                exit_code=0,
                runtime_seconds=1.0,
                peak_memory_bytes=1,
                artifacts=artifacts or {},
                content=dict.fromkeys(artifacts or {}, "0" * 64),
            ),
        ),
        started_at_utc="2026-08-20T00:00:00Z",
        finished_at_utc="2026-08-20T01:00:00Z",
    ).as_record()
    record.update(overrides)
    return record


def test_only_the_primary_families_are_published(tmp_path: Path) -> None:
    """A table that mixes deciding and robustness families invites a query that forgets."""

    from mds650.rp2.ladder import PRIMARY_MODELS

    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x")
    families = {row["model_family"] for row in payload["contrasts"]}
    assert families == set(PRIMARY_MODELS)
    assert len(payload["contrasts"]) == 2 * len(PRIMARY_MODELS) * 2


def test_a_contrast_without_its_mask_is_refused(tmp_path: Path) -> None:
    module = _load("publish_rp2_v3_supabase")
    run = _run_dir(tmp_path)
    ladder = json.loads((run / "rp2_block8_ladder" / "ladder.json").read_text(encoding="utf-8"))
    ladder["D"]["models"]["gamma_glm"]["contrasts"]["delta_b1"]["raw"]["common_mask_sha256"] = ""
    (run / "rp2_block8_ladder" / "ladder.json").write_text(json.dumps(ladder), encoding="utf-8")

    with pytest.raises(SystemExit, match="RP2_PUBLISH_CONTRAST_WITHOUT_MASK"):
        module.build_payload(run, branch="x")


def test_nothing_origin_level_leaves_the_repository(tmp_path: Path) -> None:
    """What is published is what the public report is written from, and nothing else."""

    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x")

    def keys(value: Any, found: set[str]) -> set[str]:
        if isinstance(value, dict):
            for key, item in value.items():
                found.add(str(key))
                keys(item, found)
        elif isinstance(value, list):
            for item in value:
                keys(item, found)
        return found

    # Field names, not substrings of them: `common_mask_sha256` contains "ask" and is an
    # aggregate digest, while a field actually named `ask` would be a quote.
    published = keys(payload, set())
    for forbidden in ("origin_minute", "forecast", "premium", "bid", "ask", "trade", "iv"):
        assert forbidden not in published, forbidden
    for row in payload["contrasts"]:
        assert set(row) == {
            "role",
            "model_family",
            "base_information_set",
            "expanded_information_set",
            "estimate",
            "ci_low",
            "ci_high",
            "p_value",
            "sessions",
            "block_length",
            "mde",
            "equivalence_bound",
            "common_mask_sha256",
        }


def test_the_publication_is_one_call_and_a_failure_is_recorded_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("publish_rp2_v3"):
            return httpx.Response(200, json={"status": "PUBLISHED", "contrasts": 12})
        return httpx.Response(200, json=None)

    transport = httpx.MockTransport(handler)
    original = httpx.Client

    def client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = transport
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(module.httpx, "Client", client)
    assert module.publish(payload, "key")["status"] == "PUBLISHED"
    assert calls == ["/rest/v1/rpc/publish_rp2_v3"], "one call, one transaction"

    calls.clear()

    def failing(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("publish_rp2_v3"):
            return httpx.Response(400, text="constraint violated")
        return httpx.Response(200, json=None)

    def failing_client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(failing)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(module.httpx, "Client", failing_client)
    with pytest.raises(SystemExit, match="RP2_PUBLISH_FAILED"):
        module.publish(payload, "key")
    assert calls == [
        "/rest/v1/rpc/publish_rp2_v3",
        "/rest/v1/rpc/record_rp2_v3_failure",
    ], "a rollback leaves no trace, so the failure is recorded by its own call"


def test_an_artifact_changed_since_the_run_is_refused(tmp_path: Path) -> None:
    """The manifest is written when the run finishes; publication happens afterwards."""

    from mds650.rp2.run_manifest import file_digest

    module = _load("publish_rp2_v3_supabase")
    run = _run_dir(tmp_path)
    ladder = run / "rp2_block8_ladder" / "ladder.json"
    (run / "run_manifest.json").write_text(
        json.dumps(
            _manifest_record(
                data_root=str(_bar_store(tmp_path)),
                artifacts={"rp2_block8_ladder/ladder.json": file_digest(ladder)},
            )
        ),
        encoding="utf-8",
    )
    module.build_payload(run, branch="x")

    ladder.write_text(ladder.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(SystemExit, match="RP2_PUBLISH_ARTIFACT_CHANGED"):
        module.build_payload(run, branch="x")


def test_the_run_level_mask_identifies_every_role(tmp_path: Path) -> None:
    """One role's digest under a run-level field says the other was scored on rows it never saw."""

    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x")
    assert payload["run"]["common_mask_sha256"] not in {MASK, "b" * 64}

    scorecard = {"forecast": {"gamma_glm": {"D": {"common_mask_sha256": MASK}}}}
    only_d = module._mask_digest(scorecard)
    both = module._mask_digest(
        {
            "forecast": {
                "gamma_glm": {
                    "D": {"common_mask_sha256": MASK},
                    "V": {"common_mask_sha256": "b" * 64},
                }
            }
        }
    )
    assert only_d != both


def test_the_published_inputs_are_the_inputs(tmp_path: Path) -> None:
    """A consumer following `ingestion_inputs` must find what the results were built on."""

    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x")
    names = {row["input_name"] for row in payload["inputs"]}
    assert "option_tape" in names
    assert "gated_manifest" in names
    assert any(name.startswith("bars_") for name in names)
    bars = [row for row in payload["inputs"] if row["input_name"].startswith("bars_")]
    assert all(row["path"].endswith(".parquet") for row in bars), "the real relative path"
    assert not any("ladder" in name or "panel" in name for name in names)


def test_publication_from_another_commit_is_refused(tmp_path: Path) -> None:
    """The inference digest is computed from the working tree, so the tree has to be the run's."""

    module = _load("publish_rp2_v3_supabase")
    with pytest.raises(SystemExit, match="RP2_PUBLISH_COMMIT_MISMATCH"):
        module.assert_published_at_the_run_commit({"code_commit": "9" * 40})


def test_each_block_publishes_the_artifact_that_is_its_result() -> None:
    """Taking whichever key sorted first published a panel as Block 3's finding."""

    module = _load("publish_rp2_v3_supabase")
    step = {
        "name": "build-targets",
        "exit_code": 0,
        "artifacts": {
            "rp2_block3_target/target_panel.parquet": "a" * 64,
            "rp2_block3_target/comparison.json": "b" * 64,
        },
    }
    assert module._block_result_digest(step) == "b" * 64

    # A step with no designated result contributes no block row.
    assert module._block_result_digest({"name": "build-b1", "artifacts": {}}) is None
    assert module._block_result_digest({"name": "unknown-step", "artifacts": {}}) is None


def test_a_missing_bar_store_is_refused_rather_than_invented(tmp_path: Path) -> None:
    module = _load("publish_rp2_v3_supabase")
    resolved = {"bar_sources_sha256": {"gate7_c6|D": "2" * 64}}
    with pytest.raises(SystemExit, match="RP2_PUBLISH_BAR_INPUT_MISSING"):
        module._bar_inputs(resolved, tmp_path / "absent")


def test_a_block_that_measured_nothing_is_not_published_as_measured(tmp_path: Path) -> None:
    """A producer can exit zero and record `INSUFFICIENT_ROWS` for a role."""

    module = _load("publish_rp2_v3_supabase")
    run = tmp_path / "run"
    (run / "rp2_block8_ladder").mkdir(parents=True)
    ladder = run / "rp2_block8_ladder" / "ladder.json"
    step = {"name": "fit-model-ladder", "exit_code": 0, "artifacts": {}}

    both = {"D": {"status": "MEASURED"}, "V": {"status": "MEASURED"}}
    ladder.write_text(json.dumps(both), "utf-8")
    assert module._block_status(run, step) == "MEASURED"

    ladder.write_text(
        json.dumps({"D": {"status": "MEASURED"}, "V": {"status": "INSUFFICIENT_ROWS"}}), "utf-8"
    )
    assert module._block_status(run, step) == "INSUFFICIENT_ROWS"

    assert module._block_status(run, {**step, "exit_code": 1}) == "FAILED"


def test_the_bootstrap_seed_is_part_of_the_inference_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two contrasts drawn from different resamples were not tested the same way."""

    from mds650.rp2 import inference

    before = inference.inference_config_digest()
    monkeypatch.setattr(inference, "DEFAULT_SEED", 651)
    assert inference.inference_config_digest() != before


def test_a_manifest_edited_after_the_run_is_refused(tmp_path: Path) -> None:
    """The manifest's own digest covers its provenance fields, so it can be checked."""

    module = _load("publish_rp2_v3_supabase")
    run = _run_dir(tmp_path)
    (run / "run_manifest.json").write_text(
        json.dumps(_manifest_record(input_manifest_sha256="9" * 64)), encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="RP2_PUBLISH_MANIFEST_ALTERED"):
        module.build_payload(run, branch="db/rp2-v3-versioned-results")


def test_a_bar_store_changed_since_the_run_is_refused(tmp_path: Path) -> None:
    """Lineage that pairs a run-time digest with today's bytes describes neither."""

    module = _load("publish_rp2_v3_supabase")
    from mds650.rp2.bars import BAR_SOURCES
    from mds650.rp2.run_manifest import file_digest

    name, role, relative = BAR_SOURCES[0]
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"the bars as they were")
    resolved = {"bar_sources_sha256": {f"{name}|{role}": file_digest(path)}}
    assert module._bar_inputs(resolved, tmp_path)[0]["sha256"] == file_digest(path)

    path.write_bytes(b"the bars as they are now")
    with pytest.raises(SystemExit, match="RP2_PUBLISH_BAR_INPUT_CHANGED"):
        module._bar_inputs(resolved, tmp_path)


def test_blocks_are_published_under_the_register_s_own_ids(tmp_path: Path) -> None:
    """One namespace, or the versioned row never supersedes the block it rebuilt."""

    module = _load("publish_rp2_v3_supabase")
    canonical = _load("sync_supabase_rp2_blocks")

    published = {block for block, _ in module.RESULT_BLOCKS.values()}
    assert published <= set(canonical.BLOCK_ARTIFACTS)
    # The administrative steps are not research blocks and do not belong in the register.
    for step in ("generate-scorecard", "validate-input-manifests", "validate-feature-registry"):
        assert step not in module.RESULT_BLOCKS

    from mds650.rp2.run_manifest import file_digest

    run = _run_dir(tmp_path)
    ladder = run / "rp2_block8_ladder" / "ladder.json"
    (run / "run_manifest.json").write_text(
        json.dumps(
            _manifest_record(
                data_root=str(_bar_store(tmp_path)),
                artifacts={"rp2_block8_ladder/ladder.json": file_digest(ladder)},
            )
        ),
        encoding="utf-8",
    )
    payload = module.build_payload(run, branch="x")
    assert {row["block_id"] for row in payload["blocks"]} == {"08"}


def test_an_unrecorded_failure_is_not_reported_as_an_audited_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The separate failure record is a promise, so its own failure has to be visible."""

    module = _load("publish_rp2_v3_supabase")
    original = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("publish_rp2_v3"):
            return httpx.Response(500, text="publication exploded")
        return httpx.Response(403, text="record_rp2_v3_failure is not permitted")

    def client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(module.httpx, "Client", client)
    with pytest.raises(SystemExit) as raised:
        module.publish({"run": {"run_id": "r"}}, "key")
    assert "RP2_PUBLISH_FAILED" in str(raised.value)
    assert "RP2_FAILURE_UNRECORDED" in str(raised.value)


def test_a_block_that_wrote_no_panel_is_not_published_as_measured(tmp_path: Path) -> None:
    """The panel blocks record no per-role status, but they do record a row count.

    Blocks 3 to 6 write a coverage or comparison report rather than a role-keyed result, so
    there is no status to read out of them. There is a row count, and a block that wrote an
    empty panel measured nothing however its process exited.
    """

    module = _load("publish_rp2_v3_supabase")
    run = tmp_path / "run"
    (run / "rp2_block6_flow").mkdir(parents=True)
    coverage = run / "rp2_block6_flow" / "flow_coverage.json"
    step = {"name": "build-b2", "exit_code": 0, "artifacts": {}}

    coverage.write_text(json.dumps({"block": 6, "rows": 184632}), encoding="utf-8")
    assert module._block_status(run, step) == "MEASURED"

    coverage.write_text(json.dumps({"block": 6, "rows": 0}), encoding="utf-8")
    assert module._block_status(run, step) == "EMPTY_PANEL"


def test_a_relabelled_manifest_cannot_publish_under_the_new_name(tmp_path: Path) -> None:
    """The scientific digest deliberately excludes the run id, so it cannot catch this.

    `scientific_part_of_record` leaves out the run id on purpose: the same inputs rebuilt
    under a new label are the same experiment. That is what makes an edited `run_id` invisible
    to the identity check, and every result would be published under a name that produced
    nothing while the artifacts beside it still carry the original one.
    """

    module = _load("publish_rp2_v3_supabase")
    run = _run_dir(tmp_path)
    module.build_payload(run, branch="x")

    (run / "run_manifest.json").write_text(
        json.dumps(
            _manifest_record(data_root=str(_bar_store(tmp_path)), run_id="rp2-v3-someone-else")
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="RP2_PUBLISH_RUN_ID_MISMATCH"):
        module.build_payload(run, branch="x")

    # The marker is a file too, so editing both would agree. The directory the run wrote
    # into is named after it, and that is a third thing to have to keep consistent.
    relabelled = _manifest_record(
        data_root=str(_bar_store(tmp_path)), run_id="rp2-v3-someone-else"
    )
    from mds650.rp2.run_manifest import IDENTITY_FILE

    (run / IDENTITY_FILE).write_text(json.dumps(relabelled), encoding="utf-8")
    with pytest.raises(SystemExit, match="RP2_PUBLISH_RUN_ID_MISMATCH:directory"):
        module.build_payload(run, branch="x")


def test_one_constant_decides_the_bootstrap_seed() -> None:
    """A declared constant nothing calls is a claim about the code, not a property of it."""

    import inspect

    from mds650.rp2 import inference

    seeded = [
        (name, function)
        for name, function in inspect.getmembers(inference, inspect.isfunction)
        if "seed" in inspect.signature(function).parameters
    ]
    assert seeded, "the module is supposed to have seeded estimators"
    for name, function in seeded:
        default = inspect.signature(function).parameters["seed"].default
        if default is not inspect.Parameter.empty:
            assert default == inference.DEFAULT_SEED, f"{name} carries its own seed"

    from mds650.rp2 import power

    for name, function in inspect.getmembers(power, inspect.isfunction):
        parameter = inspect.signature(function).parameters.get("seed")
        if parameter is not None and parameter.default is not inspect.Parameter.empty:
            assert parameter.default == inference.DEFAULT_SEED, f"power.{name} carries its own"

    # And no RP2 producer writes the number down for itself. A literal at a call site is the
    # same defect as a literal in a default: the digest stops describing what ran.
    literal = re.compile(r"seed\s*=\s*\d+")
    for script in sorted((REPO / "scripts").glob("rp2_*.py")):
        found = literal.findall(script.read_text(encoding="utf-8"))
        assert not found, f"{script.name} passes {found} instead of DEFAULT_SEED"


def test_no_rp2_producer_writes_an_inference_setting_down_for_itself() -> None:
    """The digest describes the settings, so the settings come from what the digest covers.

    The seed was the first of these; `repetitions=1000` in the SPA call was the second, and
    the digest recorded 2000. A literal at a producer's call site is a setting the published
    configuration does not describe.
    """

    from mds650.rp2 import inference

    # Deliberately not `alpha` or `power`: both name a model hyperparameter here as well
    # as an inference setting - `Ridge(alpha=1e-4)`, `TweedieRegressor(power=...)` - and
    # those belong to `model_config_sha256`. A check that fired on them would be
    # reporting the wrong digest.
    names = "repetitions|seed|block_length|block_mean|equivalence_fraction"
    literal = re.compile(r"\b(" + names + r")\s*=\s*[\d.]+")
    # The pattern is checked against a case it must catch. A scan that silently stopped
    # matching - a mangled escape, a renamed setting - would otherwise pass by finding
    # nothing, which is the same result as finding nothing wrong.
    assert literal.findall("hansen_spa(x, repetitions=1000)") == ["repetitions"]
    assert not literal.findall("Ridge(alpha=1e-4)")
    for script in sorted((REPO / "scripts").glob("rp2_*.py")):
        found = literal.findall(script.read_text(encoding="utf-8"))
        assert not found, f"{script.name} sets {found} itself"

    covered = json.loads(inference.inference_config_payload())
    assert covered["spa_repetitions"] == inference.SPA_REPETITIONS
    assert covered["bootstrap_repetitions"] == inference.DEFAULT_BOOTSTRAP


def test_the_publisher_does_not_offer_to_name_the_predecessor(tmp_path: Path) -> None:
    """The rows know what they replace, so nothing else is asked to say it.

    A single identifier cannot describe blocks that currently belong to different runs, and
    the transaction reads each block's owner before standing it down. An option that
    overrides that answer can only make it wrong.
    """

    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x")
    assert all("supersedes_run_id" not in row for row in payload["blocks"])

    parser_options = module.main.__doc__ or ""
    assert "--supersedes" not in parser_options
    source = (REPO / "scripts" / "publish_rp2_v3_supabase.py").read_text(encoding="utf-8")
    assert "--supersedes" not in source, "an option nothing acts on is worse than none"


def test_a_publication_that_never_reached_the_database_is_still_recorded() -> None:
    """DNS, connection and read failures are how a publication most often does not happen."""

    module = _load("publish_rp2_v3_supabase")
    original = httpx.Client
    attempted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempted.append(request.url.path)
        if request.url.path.endswith("publish_rp2_v3"):
            raise httpx.ConnectError("name or service not known")
        return httpx.Response(200, json=None)

    def client(*args: object, **kwargs: object) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module.httpx, "Client", client)
        with pytest.raises(SystemExit, match="RP2_PUBLISH_TRANSPORT_FAILED"):
            module.publish({"run": {"run_id": "r"}}, "key")
    assert attempted[-1].endswith("record_rp2_v3_failure"), "the attempt was never recorded"


def test_the_run_publishes_its_scientific_hash_as_a_field(tmp_path: Path) -> None:
    """A digest a reader can only reach by parsing prose is not really published.

    The publisher recomputes the manifest's `scientific_sha256` before it publishes anything,
    so the run row can carry the digest that assertion was made against - and a reader can
    check it, or join on it, rather than searching a free-text note for sixteen characters.
    """

    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x")
    manifest = json.loads((tmp_path / "rp2-v3-test-001" / "run_manifest.json").read_text("utf-8"))

    assert payload["run"]["scientific_sha256"] == manifest["scientific_sha256"]
    assert len(payload["run"]["scientific_sha256"]) == 64
