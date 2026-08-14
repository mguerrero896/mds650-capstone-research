"""Contract tests for the authenticated, bounded B1v3 preflight runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator

from mds650.b1v3_provider_preflight_runner_v2 import (
    ProviderSecrets,
    execute_preflight,
    render_report,
    write_if_identical,
)
from mds650.b1v3_provider_preflight_v2 import CandidatePreflightPlan, CandidateSession


def _plan() -> CandidatePreflightPlan:
    origin = datetime(2024, 8, 2, 13, 35, tzinfo=UTC)
    return CandidatePreflightPlan(
        schema_version="b1v3-date-level-pit-preflight-plan-2.0",
        status="FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION",
        target_blind=True,
        outcome_read_count=0,
        assets=("AAPL",),
        sessions=(
            CandidateSession(
                date="2024-08-02",
                role="training_warmup",
                open_utc="2024-08-02T13:30:00+00:00",
                close_utc="2024-08-02T20:00:00+00:00",
                forecast_origin_utc=origin.isoformat(),
                forecast_origin_ns=int(origin.timestamp() * 1_000_000_000),
                expected_regular_minutes=2,
            ),
        ),
        training_session_count=1,
        confirmation_session_count=0,
        source_confirmation_plan_sha256="a" * 64,
        plan_sha256="b" * 64,
    )


def _handler(seen: list[httpx.Request]) -> httpx.MockTransport:
    origin_ns = _plan().sessions[0].forecast_origin_ns

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "financialmodelingprep.com":
            assert request.url.params["apikey"] == "fmp-secret"
            return httpx.Response(
                200,
                request=request,
                json=[
                    {
                        "date": "2024-08-02 09:30:00",
                        "open": 4.0,
                        "high": 4.1,
                        "low": 3.9,
                        "close": 4.0,
                    },
                    {
                        "date": "2024-08-02 09:31:00",
                        "open": 4.0,
                        "high": 4.2,
                        "low": 3.9,
                        "close": 4.1,
                    },
                ],
            )
        if request.url.host == "api.unusualwhales.com":
            assert request.method == "GET"
            assert "range" not in request.headers
            assert request.headers["authorization"] == "Bearer uw-secret"
            assert request.headers["accept"] == "application/json"
            return httpx.Response(
                200,
                request=request,
                headers={
                    "content-type": "application/zip",
                    "content-length": "1024",
                    "x-request-id": "uw-request",
                },
                content=b"not-read-by-runner",
            )
        if request.url.path == "/v3/reference/options/contracts":
            assert request.url.params["apiKey"] == "massive-secret"
            assert request.url.params["expiration_date.gte"] == "2024-09-01"
            assert request.url.params["expiration_date.lte"] == "2024-10-01"
            assert float(request.url.params["strike_price.gte"]) == 3.9975
            assert float(request.url.params["strike_price.lte"]) == 4.2025
            if request.url.params["expired"] == "true":
                return httpx.Response(200, request=request, json={"results": []})
            return httpx.Response(
                200,
                request=request,
                json={
                    "results": [
                        {
                            "ticker": "O:AAPL240920C00004000",
                            "underlying_ticker": "AAPL",
                            "expiration_date": "2024-09-20",
                            "strike_price": 4.0,
                            "contract_type": "call",
                        }
                    ]
                },
            )
        if request.url.path == "/v3/reference/options/contracts/O:AAPL240920C00004000":
            assert request.url.params["as_of"] == "2024-08-02"
            return httpx.Response(
                200,
                request=request,
                json={
                    "results": {
                        "ticker": "O:AAPL240920C00004000",
                        "underlying_ticker": "AAPL",
                    }
                },
            )
        if request.url.path == "/v3/quotes/O:AAPL240920C00004000":
            assert request.url.params["timestamp.lte"] == str(origin_ns)
            return httpx.Response(
                200,
                request=request,
                json={
                    "results": [
                        {
                            "sip_timestamp": origin_ns - 10_000_000_000,
                            "bid_price": 4.0,
                            "ask_price": 4.4,
                            "sequence_number": 9,
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request {request.url}")

    return httpx.MockTransport(handle)


def test_bounded_runner_executes_documented_routes_and_is_idempotent(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    secrets = ProviderSecrets(
        fmp="fmp-secret",
        unusual_whales="uw-secret",
        massive="massive-secret",
    )
    raw_root = tmp_path / "raw"
    report = execute_preflight(
        _plan(),
        secrets=secrets,
        raw_root=raw_root,
        free_bytes=100 * 1024**3,
        transport=_handler(seen),
    )

    assert report["status"] == "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND"
    assert report["safe_to_acquire_predictors"] is True
    assert report["pit_semantics_confirmed"] is False
    assert report["network_attempt_count"] == 6
    massive_record = report["records"]["massive"][0]
    assert massive_record["primary_filter_pass"] is True
    assert massive_record["sensitivity_filter_pass"] is True
    assert len(seen) == 6
    rendered = render_report(report)
    assert b"fmp-secret" not in rendered
    assert b"uw-secret" not in rendered
    assert b"massive-secret" not in rendered
    assert str(tmp_path).encode() not in rendered

    def fail_if_called(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("cache replay unexpectedly called network")

    replay = execute_preflight(
        _plan(),
        secrets=secrets,
        raw_root=raw_root,
        free_bytes=100 * 1024**3,
        transport=httpx.MockTransport(fail_if_called),
    )
    assert render_report(replay) == rendered

    output = tmp_path / "report.json"
    assert write_if_identical(output, rendered) == "CREATED"
    assert write_if_identical(output, rendered) == "IDENTICAL"
    parsed = json.loads(output.read_text(encoding="utf-8"))
    assert parsed["report_sha256"] == report["report_sha256"]
    schema = json.loads(
        Path(
            "specs/001-pit-options-rv30/contracts/b1v3-provider-preflight-report-v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        parsed
    )


def test_retryable_http_failure_is_not_persisted_in_cache(tmp_path: Path) -> None:
    secrets = ProviderSecrets(
        fmp="fmp-secret",
        unusual_whales="uw-secret",
        massive="massive-secret",
    )
    raw_root = tmp_path / "raw"

    def fail_fmp(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.unusualwhales.com":
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "application/zip", "content-length": "1024"},
                content=b"not-read",
            )
        if request.url.host == "financialmodelingprep.com":
            return httpx.Response(503, request=request, json={"error": "retry"})
        raise AssertionError(f"unexpected request {request.url}")

    blocked = execute_preflight(
        _plan(),
        secrets=secrets,
        raw_root=raw_root,
        free_bytes=100 * 1024**3,
        transport=httpx.MockTransport(fail_fmp),
    )

    assert blocked["status"] == "BLOCKED_PROVIDER_PREFLIGHT"
    assert not (raw_root / "fmp/2024-08-02/AAPL.json").exists()

    seen: list[httpx.Request] = []
    recovered = execute_preflight(
        _plan(),
        secrets=secrets,
        raw_root=raw_root,
        free_bytes=100 * 1024**3,
        transport=_handler(seen),
    )
    assert recovered["status"] == "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND"
    assert any(request.url.host == "financialmodelingprep.com" for request in seen)
