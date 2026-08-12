from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from mds650.date_level_pit_preflight_v1 import (
    EndpointDescriptor,
    render_report,
    run_date_level_pit_preflight,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_plan_v1.json"
SCHEMA_PATH = (
    ROOT / "specs/001-pit-options-rv30/contracts/date-level-pit-preflight-report-v1.schema.json"
)
MIN_D_DRIVE_FREE_BYTES = 80 * 1024**3


class SanitizationProbeTransport:
    def __init__(self) -> None:
        self.call_count = 0

    def __call__(self, descriptor: EndpointDescriptor, request: object) -> object:
        self.call_count += 1
        return {
            "status_code": 200,
            "url": "https://provider.invalid/check?token=do-not-emit",
            "body": {"authorization": "do-not-emit", "nested": ["do-not-emit"]},
            "payload": {"credential": "do-not-emit", "rows": [{"value": 7}]},
        }


def _plan() -> dict[str, object]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


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


def test_injected_transport_report_is_schema_valid_and_sanitized() -> None:
    plan = _plan()
    transport = SanitizationProbeTransport()
    report = run_date_level_pit_preflight(
        plan,
        execute=True,
        approved_plan_semantic_hash=plan["semantic_self_hash"],
        zero_incremental_spend_asserted=True,
        d_drive_free_bytes=MIN_D_DRIVE_FREE_BYTES,
        secret_presence={
            "FMP_API_KEY": True,
            "UNUSUALWHALES_API_KEY": True,
            "MASSIVE_API_KEY": True,
        },
        endpoint_descriptors=_descriptors(),
        request_fn=transport,
    )
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    output = render_report(report).decode("utf-8")

    assert report["status"] == "INJECTED_TRANSPORT_COMPLETED_NOT_PROVIDER_VALIDATED"
    assert transport.call_count == 3 * 7 * 8
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert list(validator.iter_errors(report)) == []
    assert "do-not-emit" not in output
    assert "provider.invalid" not in output
    assert "opaque-fmp-preflight" not in output
