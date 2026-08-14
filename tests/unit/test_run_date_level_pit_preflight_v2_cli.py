"""CLI tests for the frozen B1v3 date-level preflight."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def test_check_only_builds_and_validates_exact_frozen_plan(tmp_path: Path) -> None:
    plan_output = tmp_path / "candidate_preflight_plan.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_date_level_pit_preflight_v2.py",
            "--check-only",
            "--plan-output",
            str(plan_output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    stdout = json.loads(result.stdout)
    assert stdout == {
        "mode": "CHECK_ONLY",
        "plan_output_state": "CREATED",
        "session_count": 90,
        "status": "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION",
    }
    plan = json.loads(plan_output.read_text(encoding="utf-8"))
    assert len(plan["assets"]) == 8
    assert len(plan["sessions"]) == 90
    assert sum(row["role"] == "training_warmup" for row in plan["sessions"]) == 60
    assert sum(row["role"] == "confirmation" for row in plan["sessions"]) == 30
    assert plan["outcome_read_count"] == 0
    schema = json.loads(
        Path(
            "specs/001-pit-options-rv30/contracts/b1v3-provider-preflight-plan-v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(plan)


def test_cli_help_requires_no_provider_secrets() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_date_level_pit_preflight_v2.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--execute" in result.stdout
    assert "--smoke" in result.stdout
