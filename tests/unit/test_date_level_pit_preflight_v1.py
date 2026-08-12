from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import fields
from pathlib import Path
from typing import Protocol, TypedDict, cast

import pytest

import mds650.date_level_pit_preflight_v1 as preflight
from mds650.date_level_pit_preflight_v1 import (
    EndpointDescriptor,
    PreflightError,
    PreflightRequest,
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


class _ForecastOriginContract(Protocol):
    forecast_origin_utc: str
    forecast_origin_ns: int


class _ExecutingKwargs(TypedDict):
    execute: bool
    approved_plan_semantic_hash: str
    zero_incremental_spend_asserted: bool
    d_drive_free_bytes: int
    secret_presence: dict[str, bool]
    endpoint_descriptors: dict[str, EndpointDescriptor]


class _DeclaredOpenCloseMetadata(Mapping[str, object]):
    """A mapping that fails if the origin helper reads undeclared session inputs."""

    def __init__(self, open_utc: str, close_utc: str) -> None:
        self._values = {"open_utc": open_utc, "close_utc": close_utc}

    def __getitem__(self, key: str) -> object:
        if key not in self._values:
            raise AssertionError(f"unexpected session metadata access: {key}")
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _plan() -> dict[str, object]:
    decoded: object = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    assert isinstance(decoded, dict)
    return cast(dict[str, object], decoded)


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


def _executing_kwargs(plan: Mapping[str, object]) -> _ExecutingKwargs:
    semantic_hash = plan.get("semantic_self_hash")
    assert isinstance(semantic_hash, str)
    return {
        "execute": True,
        "approved_plan_semantic_hash": semantic_hash,
        "zero_incremental_spend_asserted": True,
        "d_drive_free_bytes": MIN_D_DRIVE_FREE_BYTES,
        "secret_presence": _all_keys_present(),
        "endpoint_descriptors": _descriptors(),
    }


def _checks(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw_checks = report.get("checks")
    assert isinstance(raw_checks, list)
    checks: list[Mapping[str, object]] = []
    for check in raw_checks:
        assert isinstance(check, Mapping)
        checks.append(cast(Mapping[str, object], check))
    return checks


def _key_presence(report: Mapping[str, object]) -> Mapping[str, object]:
    gates = report.get("gates")
    assert isinstance(gates, Mapping)
    key_presence = gates.get("key_presence")
    assert isinstance(key_presence, Mapping)
    return cast(Mapping[str, object], key_presence)


def _derive_origin(metadata: Mapping[str, object]) -> _ForecastOriginContract:
    candidate = getattr(preflight, "derive_forecast_origin", None)
    assert candidate is not None, "derive_forecast_origin contract is required"
    derive = cast(Callable[[Mapping[str, object]], _ForecastOriginContract], candidate)
    return derive(metadata)


def _metadata_by_session_date() -> dict[str, Mapping[str, object]]:
    raw_sessions = _plan().get("sentinel_sessions")
    assert isinstance(raw_sessions, list)
    metadata_by_date: dict[str, Mapping[str, object]] = {}
    for raw_session in raw_sessions:
        assert isinstance(raw_session, dict)
        session_date = raw_session.get("date")
        metadata = raw_session.get("calendar_metadata")
        assert isinstance(session_date, str)
        assert isinstance(metadata, dict)
        metadata_by_date[session_date] = metadata
    return metadata_by_date


@pytest.mark.parametrize(
    ("session_date", "expected_utc", "expected_ns"),
    (
        ("2025-11-28", "2025-11-28T16:15:00+00:00", 1764346500000000000),
        ("2026-01-20", "2026-01-20T17:45:00+00:00", 1768931100000000000),
        ("2026-03-06", "2026-03-06T17:45:00+00:00", 1772819100000000000),
        ("2026-03-09", "2026-03-09T16:45:00+00:00", 1773074700000000000),
    ),
    ids=("early_close", "winter", "pre_dst", "post_dst"),
)
def test_forecast_origin_uses_declared_utc_session_midpoint(
    session_date: str, expected_utc: str, expected_ns: int
) -> None:
    origin = _derive_origin(_metadata_by_session_date()[session_date])

    assert origin.forecast_origin_utc == expected_utc
    assert origin.forecast_origin_ns == expected_ns
    assert origin.forecast_origin_ns % (5 * 60 * 1_000_000_000) == 0
    assert len(str(origin.forecast_origin_ns)) == 19
    assert origin.forecast_origin_ns > 0


def test_forecast_origin_reads_only_declared_open_and_close_utc() -> None:
    origin = _derive_origin(
        _DeclaredOpenCloseMetadata(
            "2026-01-20T14:30:00+00:00", "2026-01-20T21:00:00+00:00"
        )
    )

    assert origin.forecast_origin_utc == "2026-01-20T17:45:00+00:00"


def test_forecast_origin_is_deterministic() -> None:
    metadata = _metadata_by_session_date()["2026-03-09"]

    assert _derive_origin(metadata) == _derive_origin(metadata)


@pytest.mark.parametrize(
    "metadata",
    (
        {"close_utc": "2026-01-20T21:00:00+00:00"},
        {"open_utc": "2026-01-20T14:30:00", "close_utc": "2026-01-20T21:00:00+00:00"},
        {
            "open_utc": "2026-01-20T14:30:00+01:00",
            "close_utc": "2026-01-20T21:00:00+00:00",
        },
        {
            "open_utc": "2026-01-20T21:00:00+00:00",
            "close_utc": "2026-01-20T14:30:00+00:00",
        },
        {
            "open_utc": "2026-01-20T14:30:00+00:00",
            "close_utc": "2026-01-20T14:35:00+00:00",
        },
    ),
    ids=("missing_open", "naive_open", "non_utc_open", "non_positive_interval", "not_strict"),
)
def test_forecast_origin_rejects_invalid_session_metadata(metadata: Mapping[str, object]) -> None:
    with pytest.raises(PreflightError, match="SENTINEL_SESSION_METADATA_INVALID"):
        _derive_origin(metadata)


def test_injected_transport_receives_only_target_free_origin_contract() -> None:
    plan = _plan()
    transport = RecordingTransport()
    report = run_date_level_pit_preflight(plan, **_executing_kwargs(plan), request_fn=transport)
    expected_origins = {
        session_date: _derive_origin(metadata)
        for session_date, metadata in _metadata_by_session_date().items()
    }
    massive_requests = [
        request for descriptor, request in transport.calls if descriptor.provider == "massive"
    ]

    assert report["status"] == "INJECTED_TRANSPORT_COMPLETED_NOT_PROVIDER_VALIDATED"
    assert [field.name for field in fields(PreflightRequest)] == [
        "provider",
        "session_date",
        "asset",
        "forecast_origin_utc",
        "forecast_origin_ns",
    ]
    assert len(massive_requests) == 7 * 8
    for request in massive_requests:
        assert isinstance(request, PreflightRequest)
        expected = expected_origins[request.session_date]
        assert request.forecast_origin_utc == expected.forecast_origin_utc
        assert request.forecast_origin_ns == expected.forecast_origin_ns
        assert len(str(request.forecast_origin_ns)) == 19
        assert request.forecast_origin_ns > 0


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
    assert {check["request_status"] for check in _checks(report)} == {"NETWORK_BLOCKED_DRY_RUN"}


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
    assert _key_presence(report) == {
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
    assert {check["endpoint_status"] for check in _checks(report)} == {"UNCONFIGURED_ENDPOINT"}
    assert transport.calls == []


def test_run_preflight_execute_does_not_wire_a_real_network_transport() -> None:
    plan = _plan()
    report = run_date_level_pit_preflight(plan, **_executing_kwargs(plan))

    assert report["status"] == "FAILED_CLOSED"
    assert report["blocking_reasons"] == ["NETWORK_TRANSPORT_UNCONFIGURED"]
    assert {check["request_status"] for check in _checks(report)} == {
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
