"""Fail-closed, transport-injected date-level PIT preflight preparation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from typing import Final, Protocol, cast

PROVIDERS: Final[tuple[str, ...]] = ("fmp", "unusual_whales", "massive")
REQUIRED_KEY_NAMES: Final[dict[str, str]] = {
    "fmp": "FMP_API_KEY",
    "unusual_whales": "UNUSUALWHALES_API_KEY",
    "massive": "MASSIVE_API_KEY",
}
MIN_D_DRIVE_FREE_BYTES: Final[int] = 80 * 1024**3
ENDPOINT_CATALOG_SCHEMA_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "specs/001-pit-options-rv30/contracts/"
    "date-level-pit-preflight-endpoint-catalog-v1.schema.json"
)
UTC: Final[timezone] = timezone.utc  # noqa: UP017
UNIX_EPOCH: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)
NANOSECONDS_PER_SECOND: Final[int] = 1_000_000_000
NANOSECONDS_PER_MICROSECOND: Final[int] = 1_000
FIVE_MINUTES_NS: Final[int] = 5 * 60 * NANOSECONDS_PER_SECOND
MIN_NINETEEN_DIGIT_NS: Final[int] = 1_000_000_000_000_000_000
MAX_NINETEEN_DIGIT_NS: Final[int] = 9_999_999_999_999_999_999


class PreflightError(RuntimeError):
    """Static-code failure for a preflight gate or output operation."""


class _CatalogValidator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[object]: ...


class _CatalogValidatorFactory(Protocol):
    def __call__(self, schema: Mapping[str, object]) -> _CatalogValidator: ...

    def check_schema(self, schema: Mapping[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class EndpointDescriptor:
    """Opaque, declarative endpoint configuration; its target is never emitted."""

    provider: str
    endpoint_id: str
    method: str
    request_target: str


@dataclass(frozen=True, slots=True)
class ForecastOrigin:
    """A target-free UTC origin derived only from declared session bounds."""

    forecast_origin_utc: str
    forecast_origin_ns: int


@dataclass(frozen=True, slots=True)
class PreflightRequest:
    """A target-free date-level check passed to an injected transport."""

    provider: str
    session_date: str
    asset: str
    forecast_origin_utc: str
    forecast_origin_ns: int


RequestFn = Callable[[EndpointDescriptor, PreflightRequest], object]


def derive_forecast_origin(session_metadata: Mapping[str, object]) -> ForecastOrigin:
    """Derive one strict, five-minute-aligned UTC origin from declared bounds only."""
    if not isinstance(session_metadata, Mapping):
        raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
    open_utc = _parse_declared_utc(session_metadata.get("open_utc"))
    close_utc = _parse_declared_utc(session_metadata.get("close_utc"))
    open_ns = _unix_ns(open_utc)
    close_ns = _unix_ns(close_utc)
    if close_ns <= open_ns:
        raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
    midpoint_ns = open_ns + (close_ns - open_ns) // 2
    forecast_origin_ns = midpoint_ns - midpoint_ns % FIVE_MINUTES_NS
    if not open_ns < forecast_origin_ns < close_ns:
        raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
    if not MIN_NINETEEN_DIGIT_NS <= forecast_origin_ns <= MAX_NINETEEN_DIGIT_NS:
        raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
    forecast_origin_utc = UNIX_EPOCH + timedelta(
        microseconds=forecast_origin_ns // NANOSECONDS_PER_MICROSECOND
    )
    return ForecastOrigin(
        forecast_origin_utc=forecast_origin_utc.isoformat(timespec="seconds"),
        forecast_origin_ns=forecast_origin_ns,
    )


def _parse_declared_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PreflightError("SENTINEL_SESSION_METADATA_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
    return parsed.astimezone(UTC)


def _unix_ns(moment: datetime) -> int:
    delta = moment - UNIX_EPOCH
    return (
        delta.days * 86_400 * NANOSECONDS_PER_SECOND
        + delta.seconds * NANOSECONDS_PER_SECOND
        + delta.microseconds * NANOSECONDS_PER_MICROSECOND
    )


def canonical_json(value: Mapping[str, object]) -> bytes:
    """Encode a mapping deterministically for reports and semantic hashes."""
    serialized = json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return serialized.encode("utf-8")


def load_plan(path: Path) -> dict[str, object]:
    """Load a local plan without emitting its path or contents on failure."""
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError("PLAN_READ_FAILED") from exc
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise PreflightError("PLAN_FORMAT_INVALID")
    return cast(dict[str, object], decoded)


def load_endpoint_descriptors(path: Path) -> dict[str, EndpointDescriptor]:
    """Load descriptors only from a schema-validated, declarative catalog."""
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError("ENDPOINT_CATALOG_READ_FAILED") from exc
    schema = _load_endpoint_catalog_schema()
    validator = _endpoint_catalog_validator(schema)
    if any(validator.iter_errors(decoded)):
        raise PreflightError("ENDPOINT_CATALOG_SCHEMA_INVALID")
    if not isinstance(decoded, Mapping):
        raise PreflightError("ENDPOINT_CATALOG_SCHEMA_INVALID")
    endpoints = decoded.get("endpoints")
    if not isinstance(endpoints, list):
        raise PreflightError("ENDPOINT_CATALOG_SCHEMA_INVALID")
    descriptors: dict[str, EndpointDescriptor] = {}
    for item in endpoints:
        if not isinstance(item, Mapping):
            raise PreflightError("ENDPOINT_CATALOG_SCHEMA_INVALID")
        descriptor_keys = ("provider", "endpoint_id", "method", "request_target")
        values = {key: item.get(key) for key in descriptor_keys}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise PreflightError("ENDPOINT_CATALOG_SCHEMA_INVALID")
        provider = cast(str, values["provider"])
        if provider not in PROVIDERS or provider in descriptors:
            raise PreflightError("ENDPOINT_CATALOG_SCHEMA_INVALID")
        descriptors[provider] = EndpointDescriptor(
            provider=provider,
            endpoint_id=cast(str, values["endpoint_id"]),
            method=cast(str, values["method"]),
            request_target=cast(str, values["request_target"]),
        )
    if tuple(descriptors) != PROVIDERS:
        raise PreflightError("ENDPOINT_CATALOG_SCHEMA_INVALID")
    return descriptors


def _load_endpoint_catalog_schema() -> dict[str, object]:
    try:
        decoded: object = json.loads(ENDPOINT_CATALOG_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError("ENDPOINT_CATALOG_SCHEMA_UNAVAILABLE") from exc
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise PreflightError("ENDPOINT_CATALOG_SCHEMA_UNAVAILABLE")
    return cast(dict[str, object], decoded)


def _endpoint_catalog_validator(schema: Mapping[str, object]) -> _CatalogValidator:
    try:
        module = import_module("jsonschema")
        factory = cast(_CatalogValidatorFactory, module.Draft202012Validator)
        factory.check_schema(schema)
        return factory(schema)
    except Exception as exc:
        raise PreflightError("ENDPOINT_CATALOG_SCHEMA_UNAVAILABLE") from exc


def environment_key_presence(environ: Mapping[str, str] | None = None) -> dict[str, bool]:
    """Check only membership of the three required environment-variable names."""
    source = os.environ if environ is None else environ
    return {name: name in source for name in REQUIRED_KEY_NAMES.values()}


def d_drive_free_bytes() -> int:
    """Return available bytes on D: without inspecting files or credentials."""
    try:
        return shutil.disk_usage("D:/").free
    except OSError as exc:
        raise PreflightError("D_DRIVE_FREE_SPACE_UNAVAILABLE") from exc


def run_date_level_pit_preflight(
    plan: Mapping[str, object],
    *,
    execute: bool,
    approved_plan_semantic_hash: str | None = None,
    zero_incremental_spend_asserted: bool = False,
    d_drive_free_bytes: int | None = None,
    secret_presence: Mapping[str, bool] | None = None,
    endpoint_descriptors: Mapping[str, EndpointDescriptor] | None = None,
    request_fn: RequestFn | None = None,
) -> dict[str, object]:
    """Prepare or execute only an explicitly authorized injected-transport preflight."""
    plan_hash = _plan_hash(plan)
    key_presence = _key_presence(secret_presence)
    descriptors = {} if endpoint_descriptors is None else dict(endpoint_descriptors)
    endpoint_statuses = {}
    for provider in PROVIDERS:
        endpoint_statuses[provider] = (
            "CONFIGURED"
            if _valid_descriptor(descriptors.get(provider), provider)
            else "UNCONFIGURED_ENDPOINT"
        )
    observed_free_bytes = d_drive_free_bytes
    blockers: list[str] = []
    plan_integrity = "PASS" if plan_hash is not None else "FAIL"
    approval_status = "NOT_REQUIRED_DRY_RUN"
    spend_status = "NOT_REQUIRED_DRY_RUN"
    disk_status = "NOT_REQUIRED_DRY_RUN"
    key_status = "PASS" if all(key_presence.values()) else "FAIL"
    transport_status = "NETWORK_BLOCKED_DRY_RUN"

    if execute:
        approval_status = _approval_status(approved_plan_semantic_hash, plan_hash)
        spend_status = "ASSERTED" if zero_incremental_spend_asserted else "MISSING"
        if observed_free_bytes is None:
            try:
                observed_free_bytes = d_drive_free_bytes_for_execution()
            except PreflightError:
                observed_free_bytes = None
                disk_status = "UNAVAILABLE"
        if disk_status != "UNAVAILABLE":
            disk_status = (
                "PASS"
                if observed_free_bytes is not None and observed_free_bytes >= MIN_D_DRIVE_FREE_BYTES
                else "FAIL"
            )
        transport_status = "NOT_EVALUATED"
        if plan_integrity == "FAIL":
            blockers.append("PLAN_SELF_HASH_INVALID")
        if approval_status == "MISSING":
            blockers.append("APPROVED_PLAN_HASH_REQUIRED")
        elif approval_status == "MISMATCH":
            blockers.append("APPROVED_PLAN_HASH_MISMATCH")
        if spend_status == "MISSING":
            blockers.append("ZERO_INCREMENTAL_SPEND_ASSERTION_REQUIRED")
        if disk_status == "UNAVAILABLE":
            blockers.append("D_DRIVE_FREE_SPACE_UNAVAILABLE")
        elif disk_status == "FAIL":
            blockers.append("D_DRIVE_FREE_SPACE_INSUFFICIENT")
        if key_status == "FAIL":
            blockers.append("MISSING_PROVIDER_SECRETS")
        if "UNCONFIGURED_ENDPOINT" in endpoint_statuses.values():
            blockers.append("UNCONFIGURED_ENDPOINT")
        elif request_fn is None:
            blockers.append("NETWORK_TRANSPORT_UNCONFIGURED")
        if not blockers:
            transport_status = "INJECTED_TRANSPORT_ENABLED"

    checks = _build_checks(plan, endpoint_statuses, execute, blockers, request_fn, descriptors)
    has_transport_failure = any(
        check["request_status"] == "INJECTED_TRANSPORT_FAILURE" for check in checks
    )
    if execute and not blockers and has_transport_failure:
        blockers.append("INJECTED_TRANSPORT_REQUEST_FAILURE")
        transport_status = "INJECTED_TRANSPORT_FAILURE"
    status = (
        "DRY_RUN_NETWORK_BLOCKED"
        if not execute
        else "FAILED_CLOSED"
        if blockers
        else "INJECTED_TRANSPORT_COMPLETED_NOT_PROVIDER_VALIDATED"
    )
    report: dict[str, object] = {
        "artifact_type": "date_level_pit_preflight_report_v1",
        "schema_version": "1.0.0",
        "status": status,
        "execution_mode": "DRY_RUN" if not execute else "EXECUTE_WITH_INJECTED_TRANSPORT",
        "plan_semantic_hash": plan_hash,
        "approved_plan_semantic_hash": approved_plan_semantic_hash,
        "blocking_reasons": blockers,
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
            "request_urls_emitted": False,
            "request_bodies_emitted": False,
        },
        "gates": {
            "plan_integrity": plan_integrity,
            "approval_hash": approval_status,
            "zero_incremental_spend_assertion": spend_status,
            "d_drive_free_space": {
                "threshold_bytes": MIN_D_DRIVE_FREE_BYTES,
                "observed_free_bytes": observed_free_bytes,
                "status": disk_status,
            },
            "key_presence": key_presence,
            "key_presence_status": key_status,
            "endpoint_configuration": endpoint_statuses,
            "transport": transport_status,
        },
        "checks": checks,
        "semantic_hash_scope": "canonical-json-excluding-semantic_self_hash",
    }
    report["semantic_self_hash"] = _semantic_self_hash(report)
    return report


def render_report(report: Mapping[str, object]) -> bytes:
    """Render a deterministic report without mutable timestamps or raw responses."""
    return canonical_json(report) + b"\n"


def write_if_identical(path: Path, content: bytes) -> str:
    """Write once, accept exact replay bytes, and reject divergent output."""
    try:
        if path.exists():
            if path.read_bytes() == content:
                return "IDENTICAL"
            raise PreflightError("REPORT_OUTPUT_CONFLICT")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError as exc:
        raise PreflightError("REPORT_OUTPUT_WRITE_FAILED") from exc
    return "CREATED"


def d_drive_free_bytes_for_execution() -> int:
    """Internal seam retained so tests never inspect local disk state."""
    return d_drive_free_bytes()


def _plan_hash(plan: Mapping[str, object]) -> str | None:
    actual = plan.get("semantic_self_hash")
    if not isinstance(actual, str):
        return None
    payload = dict(plan)
    payload.pop("semantic_self_hash", None)
    expected = _semantic_self_hash(payload)
    return actual if actual == expected else None


def _semantic_self_hash(payload: Mapping[str, object]) -> str:
    normalized = dict(payload)
    normalized.pop("semantic_self_hash", None)
    return f"sha256:{hashlib.sha256(canonical_json(normalized)).hexdigest()}"


def _key_presence(source: Mapping[str, bool] | None) -> dict[str, bool]:
    presence = environment_key_presence() if source is None else source
    return {name: presence.get(name) is True for name in REQUIRED_KEY_NAMES.values()}


def _valid_descriptor(descriptor: EndpointDescriptor | None, provider: str) -> bool:
    return bool(
        descriptor
        and descriptor.provider == provider
        and descriptor.endpoint_id
        and descriptor.method
        and descriptor.request_target
    )


def _approval_status(approved_hash: str | None, plan_hash: str | None) -> str:
    if approved_hash is None:
        return "MISSING"
    return "MATCH" if plan_hash is not None and approved_hash == plan_hash else "MISMATCH"


def _build_checks(
    plan: Mapping[str, object],
    endpoint_statuses: Mapping[str, str],
    execute: bool,
    blockers: list[str],
    request_fn: RequestFn | None,
    descriptors: Mapping[str, EndpointDescriptor],
) -> list[dict[str, object]]:
    assets, session_origins = _plan_dimensions(plan)
    checks: list[dict[str, object]] = []
    for provider in PROVIDERS:
        descriptor = descriptors.get(provider)
        for session_date, forecast_origin in session_origins:
            for asset in assets:
                check: dict[str, object] = {
                    "provider": provider,
                    "session_date": session_date,
                    "asset": asset,
                    "endpoint_status": endpoint_statuses[provider],
                    "request_status": _request_status(
                        execute, blockers, endpoint_statuses[provider]
                    ),
                    "response": None,
                }
                if execute and not blockers and descriptor is not None and request_fn is not None:
                    try:
                        request = PreflightRequest(
                            provider=provider,
                            session_date=session_date,
                            asset=asset,
                            forecast_origin_utc=forecast_origin.forecast_origin_utc,
                            forecast_origin_ns=forecast_origin.forecast_origin_ns,
                        )
                        response = request_fn(descriptor, request)
                    except Exception:
                        check["request_status"] = "INJECTED_TRANSPORT_FAILURE"
                    else:
                        check["request_status"] = "INJECTED_TRANSPORT_RESPONSE"
                        check["response"] = _sanitize_response(response)
                checks.append(check)
    return checks


def _plan_dimensions(
    plan: Mapping[str, object],
) -> tuple[list[str], list[tuple[str, ForecastOrigin]]]:
    raw_assets = plan.get("assets")
    raw_sessions = plan.get("sentinel_sessions")
    assets = (
        list(raw_assets)
        if isinstance(raw_assets, list) and all(isinstance(asset, str) for asset in raw_assets)
        else []
    )
    if not isinstance(raw_sessions, list):
        raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
    session_origins: list[tuple[str, ForecastOrigin]] = []
    session_dates: set[str] = set()
    for session in raw_sessions:
        if not isinstance(session, Mapping):
            raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
        session_date = session.get("date")
        session_metadata = session.get("calendar_metadata")
        if (
            not isinstance(session_date, str)
            or not session_date
            or not isinstance(session_metadata, Mapping)
            or session_date in session_dates
        ):
            raise PreflightError("SENTINEL_SESSION_METADATA_INVALID")
        session_dates.add(session_date)
        session_origins.append((session_date, derive_forecast_origin(session_metadata)))
    return assets, session_origins


def _request_status(execute: bool, blockers: list[str], endpoint_status: str) -> str:
    if not execute:
        return "NETWORK_BLOCKED_DRY_RUN"
    if endpoint_status == "UNCONFIGURED_ENDPOINT":
        return "NOT_ATTEMPTED_UNCONFIGURED_ENDPOINT"
    return "NOT_ATTEMPTED_GATE_BLOCKED" if blockers else "INJECTED_TRANSPORT_RESPONSE"


def _sanitize_response(response: object) -> dict[str, object]:
    status_code: int | None = None
    payload: object = None
    if isinstance(response, Mapping):
        candidate = response.get("status_code")
        status_code = candidate if isinstance(candidate, int) and 100 <= candidate <= 599 else None
        payload = response.get("payload")
    shape = _shape(payload)
    return {
        "http_status": status_code,
        "response_shape_sha256": hashlib.sha256(canonical_json({"shape": shape})).hexdigest(),
    }


def _shape(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            "kind": "mapping",
            "entries": sorted((str(key), _shape(item)) for key, item in value.items()),
        }
    if isinstance(value, list):
        return {"kind": "list", "items": [_shape(item) for item in value]}
    return {"kind": type(value).__name__}
