from __future__ import annotations

import json
from pathlib import Path

import pytest

from mds650.date_level_pit_preflight_v1 import (
    EndpointDescriptor,
    PreflightError,
    run_date_level_pit_preflight,
    write_if_identical,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_plan_v1.json"
MIN_D_DRIVE_FREE_BYTES = 80 * 1024**3


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[EndpointDescriptor, object]] = []

    def __call__(self, descriptor: EndpointDescriptor, request: object) -> object:
        self.calls.append((descriptor, request))
        return {"status_code": 204, "payload": {"accepted": True}}


def _plan() -> dict[str, object]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _all_keys_present() -> dict[str, bool]:
    return {
        "FMP_API_KEY": True,
        "UNUSUALWHALES_API_KEY": True,
        "MASSIVE_API_KEY": True,
    }


def _descriptors() -> dict[str, EndpointDescriptor]:
    return {
        "fmp": EndpointDescriptor("fmp", "fmp-preflight", "GET", "opaque-fmp-preflight"),
        "unusual_whales": EndpointDescriptor(
            "unusual_whales", "uw-preflight", "GET", "opaque-uw-preflight"
        ),
        "massive": EndpointDescriptor(
            "massive", "massive-preflight", "GET", "opaque-massive-preflight"
        ),
    }


def _executing_kwargs(plan: dict[str, object]) -> dict[str, object]:
    return {
        "execute": True,
        "approved_plan_semantic_hash": plan["semantic_self_hash"],
        "zero_incremental_spend_asserted": True,
        "d_drive_free_bytes": MIN_D_DRIVE_FREE_BYTES,
        "secret_presence": _all_keys_present(),
        "endpoint_descriptors": _descriptors(),
    }


def test_run_preflight_without_execute_blocks_every_network_request() -> None:
    transport = RecordingTransport()
    report = run_date_level_pit_preflight(
        _plan(),
        execute=False,
        secret_presence=_all_keys_present(),
        request_fn=transport,
    )

    assert report["status"] == "DRY_RUN_NETWORK_BLOCKED"
    assert transport.calls == []
    assert {check["request_status"] for check in report["checks"]} == {"NETWORK_BLOCKED_DRY_RUN"}


def test_run_preflight_execute_requires_an_approved_plan_hash() -> None:
    transport = RecordingTransport()
    report = run_date_level_pit_preflight(
        _plan(),
        execute=True,
        zero_incremental_spend_asserted=True,
        d_drive_free_bytes=MIN_D_DRIVE_FREE_BYTES,
        secret_presence=_all_keys_present(),
        endpoint_descriptors=_descriptors(),
        request_fn=transport,
    )

    assert report["status"] == "FAILED_CLOSED"
    assert report["blocking_reasons"] == ["APPROVED_PLAN_HASH_REQUIRED"]
    assert transport.calls == []


def test_run_preflight_execute_rejects_a_mismatched_approved_plan_hash() -> None:
    plan = _plan()
    transport = RecordingTransport()
    kwargs = _executing_kwargs(plan)
    kwargs["approved_plan_semantic_hash"] = "sha256:" + "0" * 64
    report = run_date_level_pit_preflight(plan, **kwargs, request_fn=transport)

    assert report["status"] == "FAILED_CLOSED"
    assert report["blocking_reasons"] == ["APPROVED_PLAN_HASH_MISMATCH"]
    assert transport.calls == []


def test_run_preflight_execute_requires_eighty_gib_free_on_d_drive() -> None:
    plan = _plan()
    transport = RecordingTransport()
    kwargs = _executing_kwargs(plan)
    kwargs["d_drive_free_bytes"] = MIN_D_DRIVE_FREE_BYTES - 1
    report = run_date_level_pit_preflight(plan, **kwargs, request_fn=transport)

    assert report["status"] == "FAILED_CLOSED"
    assert report["blocking_reasons"] == ["D_DRIVE_FREE_SPACE_INSUFFICIENT"]
    assert transport.calls == []


def test_run_preflight_execute_requires_all_three_key_presence_checks() -> None:
    plan = _plan()
    transport = RecordingTransport()
    kwargs = _executing_kwargs(plan)
    kwargs["secret_presence"] = {
        "FMP_API_KEY": True,
        "UNUSUALWHALES_API_KEY": False,
        "MASSIVE_API_KEY": True,
    }
    report = run_date_level_pit_preflight(plan, **kwargs, request_fn=transport)

    assert report["status"] == "FAILED_CLOSED"
    assert report["blocking_reasons"] == ["MISSING_PROVIDER_SECRETS"]
    assert report["gates"]["key_presence"] == {
        "FMP_API_KEY": True,
        "UNUSUALWHALES_API_KEY": False,
        "MASSIVE_API_KEY": True,
    }
    assert transport.calls == []


def test_run_preflight_execute_requires_zero_incremental_spend_assertion() -> None:
    plan = _plan()
    transport = RecordingTransport()
    kwargs = _executing_kwargs(plan)
    kwargs["zero_incremental_spend_asserted"] = False
    report = run_date_level_pit_preflight(plan, **kwargs, request_fn=transport)

    assert report["status"] == "FAILED_CLOSED"
    assert report["blocking_reasons"] == ["ZERO_INCREMENTAL_SPEND_ASSERTION_REQUIRED"]
    assert transport.calls == []


def test_run_preflight_execute_fails_closed_for_unconfigured_endpoints() -> None:
    plan = _plan()
    transport = RecordingTransport()
    kwargs = _executing_kwargs(plan)
    kwargs["endpoint_descriptors"] = {}
    report = run_date_level_pit_preflight(plan, **kwargs, request_fn=transport)

    assert report["status"] == "FAILED_CLOSED"
    assert report["blocking_reasons"] == ["UNCONFIGURED_ENDPOINT"]
    assert {check["endpoint_status"] for check in report["checks"]} == {"UNCONFIGURED_ENDPOINT"}
    assert transport.calls == []


def test_run_preflight_execute_does_not_wire_a_real_network_transport() -> None:
    plan = _plan()
    report = run_date_level_pit_preflight(plan, **_executing_kwargs(plan))

    assert report["status"] == "FAILED_CLOSED"
    assert report["blocking_reasons"] == ["NETWORK_TRANSPORT_UNCONFIGURED"]
    assert {check["request_status"] for check in report["checks"]} == {
        "NOT_ATTEMPTED_GATE_BLOCKED"
    }


def test_run_preflight_report_is_deterministic() -> None:
    plan = _plan()
    first = run_date_level_pit_preflight(plan, execute=False, secret_presence=_all_keys_present())
    second = run_date_level_pit_preflight(plan, execute=False, secret_presence=_all_keys_present())

    assert first == second


def test_write_if_identical_rejects_conflicting_output(tmp_path: Path) -> None:
    target = tmp_path / "report.json"

    assert write_if_identical(target, b"stable\n") == "CREATED"
    assert write_if_identical(target, b"stable\n") == "IDENTICAL"
    with pytest.raises(PreflightError, match="REPORT_OUTPUT_CONFLICT"):
        write_if_identical(target, b"different\n")
