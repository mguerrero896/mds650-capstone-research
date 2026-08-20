"""Publication is one transaction, publishes only aggregates, and records its failures.

The failure this guards against is not a wrong number. It is a database that half agrees
with itself: a run marked RUNNING with some of its results published and the previous
run's rows already stood down, so the current answer is missing and nothing says so.
"""

from __future__ import annotations

import importlib.util
import json
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
        json.dumps({"forecast": {"gamma_glm": {"D": {"common_mask_sha256": MASK}}}}),
        encoding="utf-8",
    )
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "rp2-v3-test-001",
                "code_commit": COMMIT,
                "input_manifest_sha256": "c" * 64,
                "feature_registry_sha256": "d" * 64,
                "model_config_sha256": "e" * 64,
                "scientific_sha256": "f" * 64,
                "steps": [
                    {
                        "name": "fit-model-ladder",
                        "exit_code": 0,
                        "artifacts": {"rp2_block8_ladder/ladder.json": "1" * 64},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return run


def test_only_the_primary_families_are_published(tmp_path: Path) -> None:
    """A table that mixes deciding and robustness families invites a query that forgets."""

    from mds650.rp2.ladder import PRIMARY_MODELS

    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x", supersedes=None)
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
        module.build_payload(run, branch="x", supersedes=None)


def test_nothing_origin_level_leaves_the_repository(tmp_path: Path) -> None:
    """What is published is what the public report is written from, and nothing else."""

    module = _load("publish_rp2_v3_supabase")
    payload = module.build_payload(_run_dir(tmp_path), branch="x", supersedes=None)

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
    payload = module.build_payload(_run_dir(tmp_path), branch="x", supersedes=None)
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
