"""Authenticated, bounded and resumable B1v3 provider preflight runner.

The runner checks historical request availability for an already frozen,
target-blind 60/30 plan.  It does not download the Unusual Whales ZIP body,
construct predictors, read RV30/QLIKE, or claim provider publication/receipt
semantics.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final, cast
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx

from mds650.b1v3_provider_preflight_v2 import (
    B1V3PreflightError,
    CandidatePreflightPlan,
    CandidateSession,
    build_request_budget,
    canonical_json,
    validate_fmp_session,
    validate_massive_quote,
    validate_storage_gate,
    validate_uw_zip_headers,
)
from mds650.date_level_pit_preflight_v2 import AttemptBudgetError, AttemptLedger
from mds650.massive_contract_selection_v1 import (
    HistoricalOptionContract,
    SelectedContract,
    select_contract_grid,
)

FMP_BASE_URL: Final[str] = "https://financialmodelingprep.com"
UW_BASE_URL: Final[str] = "https://api.unusualwhales.com"
MASSIVE_BASE_URL: Final[str] = "https://api.massive.com"
MAX_ATTEMPTS_PER_OPERATION: Final[int] = 3
CONNECT_TIMEOUT_SECONDS: Final[float] = 20.0
READ_TIMEOUT_SECONDS: Final[float] = 60.0
AUTHORIZATION_ID: Final[str] = "OWNER_APPROVED_B1V3_WRITTEN_SPEC_2026-08-14"
CONTRACT_SELECTION_RULE_ID: Final[str] = "massive-contract-grid-v1-asof-dte-moneyness-tiebreak"


@dataclass(frozen=True, slots=True)
class ProviderSecrets:
    """Three in-memory credentials; values are never serialized or logged."""

    fmp: str
    unusual_whales: str
    massive: str

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in asdict(self).values()):
            raise B1V3PreflightError("B1V3_PREFLIGHT_PROVIDER_SECRET_MISSING")


@dataclass(frozen=True, slots=True)
class _CachedResponse:
    provider: str
    evidence_key: str
    request_fingerprint: str
    status_code: int
    headers: Mapping[str, str]
    payload: object
    response_sha256: str
    network_attempts: int


class _EvidenceStore:
    """Immutable commercial-response cache rooted outside the repository."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def load(self, evidence_key: str, request_fingerprint: str) -> _CachedResponse | None:
        path = self._path(evidence_key)
        if not path.exists():
            return None
        try:
            decoded: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise B1V3PreflightError("B1V3_PREFLIGHT_CACHE_INVALID") from exc
        if not isinstance(decoded, dict):
            raise B1V3PreflightError("B1V3_PREFLIGHT_CACHE_INVALID")
        if decoded.get("request_fingerprint") != request_fingerprint:
            raise B1V3PreflightError("B1V3_PREFLIGHT_CACHE_REQUEST_CONFLICT")
        stored_hash = decoded.get("cache_self_hash")
        normalized = dict(decoded)
        normalized.pop("cache_self_hash", None)
        if stored_hash != _sha256_hex(normalized):
            raise B1V3PreflightError("B1V3_PREFLIGHT_CACHE_HASH_INVALID")
        return _cached_response(decoded, evidence_key=evidence_key)

    def store(self, evidence_key: str, response: _CachedResponse) -> _CachedResponse:
        path = self._path(evidence_key)
        body: dict[str, object] = {
            "schema_version": "b1v3-provider-preflight-cache-2.0",
            "provider": response.provider,
            "request_fingerprint": response.request_fingerprint,
            "status_code": response.status_code,
            "headers": dict(sorted(response.headers.items())),
            "payload": response.payload,
            "response_sha256": response.response_sha256,
            "network_attempts": response.network_attempts,
        }
        body["cache_self_hash"] = _sha256_hex(body)
        content = canonical_json(body) + b"\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_bytes() != content:
                    raise B1V3PreflightError("B1V3_PREFLIGHT_CACHE_OUTPUT_CONFLICT")
            else:
                path.write_bytes(content)
        except OSError as exc:
            raise B1V3PreflightError("B1V3_PREFLIGHT_CACHE_WRITE_FAILED") from exc
        return response

    def _path(self, evidence_key: str) -> Path:
        relative = Path(evidence_key)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".json":
            raise B1V3PreflightError("B1V3_PREFLIGHT_EVIDENCE_KEY_INVALID")
        path = (self._root / relative).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise B1V3PreflightError("B1V3_PREFLIGHT_EVIDENCE_KEY_INVALID") from exc
        return path


class _Transport:
    """Secret-safe HTTP boundary with one inclusive atomic attempt ledger."""

    def __init__(
        self,
        *,
        secrets: ProviderSecrets,
        store: _EvidenceStore,
        ledger: AttemptLedger,
        transport: httpx.BaseTransport | None,
    ) -> None:
        self._secrets = secrets
        self._store = store
        self._ledger = ledger
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=READ_TIMEOUT_SECONDS,
                pool=CONNECT_TIMEOUT_SECONDS,
            ),
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def json_request(
        self,
        *,
        provider: str,
        operation_id: str,
        evidence_key: str,
        url: str,
        params: Mapping[str, str | int | float | bool],
    ) -> _CachedResponse:
        headers, request_params = self._authenticated_request(provider, params)
        fingerprint = _request_fingerprint(
            provider=provider,
            method="GET",
            url=url,
            params=params,
            headers=_sanitized_request_headers(headers),
        )
        cached = self._store.load(evidence_key, fingerprint)
        if cached is not None:
            return cached
        last_response: httpx.Response | None = None
        attempts = 0
        for attempt in range(1, MAX_ATTEMPTS_PER_OPERATION + 1):
            self._reserve(operation_id)
            attempts = attempt
            try:
                response = self._client.get(url, params=request_params, headers=headers)
            except httpx.HTTPError as exc:
                raise B1V3PreflightError("B1V3_PREFLIGHT_NETWORK_FAILURE") from exc
            last_response = response
            if response.status_code not in {429} and response.status_code < 500:
                break
            if attempt < MAX_ATTEMPTS_PER_OPERATION:
                time.sleep(_retry_delay(response.headers, attempt))
        if last_response is None:
            raise B1V3PreflightError("B1V3_PREFLIGHT_NETWORK_FAILURE")
        raw = last_response.content
        try:
            payload: object = last_response.json()
        except ValueError:
            payload = None
        cached_response = _CachedResponse(
            provider=provider,
            evidence_key=evidence_key,
            request_fingerprint=fingerprint,
            status_code=last_response.status_code,
            headers=_sanitized_response_headers(last_response.headers),
            payload=payload,
            response_sha256=hashlib.sha256(raw).hexdigest(),
            network_attempts=attempts,
        )
        if last_response.status_code == 429 or last_response.status_code >= 500:
            return cached_response
        return self._store.store(evidence_key, cached_response)

    def uw_zip_metadata(
        self,
        *,
        session_date: str,
        evidence_key: str,
    ) -> _CachedResponse:
        url = f"{UW_BASE_URL}/api/option-trades/full-tape/{session_date}"
        request_headers = {
            "Authorization": f"Bearer {self._secrets.unusual_whales}",
            "Accept": "application/json",
        }
        fingerprint = _request_fingerprint(
            provider="unusual_whales",
            method="GET",
            url=url,
            params={},
            headers={"Accept": "application/json"},
        )
        cached = self._store.load(evidence_key, fingerprint)
        if cached is not None:
            return cached
        operation_id = f"unusual_whales:full_tape_zip:{session_date}"
        last_status = 0
        last_headers: Mapping[str, str] = {}
        attempts = 0
        for attempt in range(1, MAX_ATTEMPTS_PER_OPERATION + 1):
            self._reserve(operation_id)
            attempts = attempt
            try:
                with self._client.stream("GET", url, headers=request_headers) as response:
                    last_status = response.status_code
                    last_headers = _sanitized_response_headers(response.headers)
            except httpx.HTTPError as exc:
                raise B1V3PreflightError("B1V3_PREFLIGHT_NETWORK_FAILURE") from exc
            if last_status not in {429} and last_status < 500:
                break
            if attempt < MAX_ATTEMPTS_PER_OPERATION:
                time.sleep(_retry_delay(last_headers, attempt))
        payload: dict[str, object] = {
            "method": "GET",
            "request_headers": {"Accept": "application/json"},
        }
        response_hash = _sha256_hex(
            {"status_code": last_status, "headers": dict(sorted(last_headers.items()))}
        )
        cached_response = _CachedResponse(
            provider="unusual_whales",
            evidence_key=evidence_key,
            request_fingerprint=fingerprint,
            status_code=last_status,
            headers=last_headers,
            payload=payload,
            response_sha256=response_hash,
            network_attempts=attempts,
        )
        if last_status == 429 or last_status >= 500:
            return cached_response
        return self._store.store(evidence_key, cached_response)

    def _authenticated_request(
        self,
        provider: str,
        params: Mapping[str, str | int | float | bool],
    ) -> tuple[dict[str, str], dict[str, str | int | float | bool]]:
        request_params = dict(params)
        if provider == "fmp":
            request_params["apikey"] = self._secrets.fmp
            return {"Accept": "application/json"}, request_params
        if provider == "massive":
            request_params["apiKey"] = self._secrets.massive
            return {"Accept": "application/json"}, request_params
        raise B1V3PreflightError("B1V3_PREFLIGHT_PROVIDER_INVALID")

    def _reserve(self, operation_id: str) -> None:
        try:
            self._ledger.reserve_attempt(operation_id)
        except AttemptBudgetError as exc:
            raise B1V3PreflightError("B1V3_PREFLIGHT_HTTP_ATTEMPT_CAP_EXCEEDED") from exc


def execute_preflight(
    plan: CandidatePreflightPlan,
    *,
    secrets: ProviderSecrets,
    raw_root: Path,
    free_bytes: int,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    """Execute the bounded historical-availability checks for a frozen plan.

    Parameters
    ----------
    plan
        Target-blind provider plan with fixed assets, sessions and origins.
    secrets
        In-memory provider credentials.
    raw_root
        External commercial-evidence root, normally on ``D:``.
    free_bytes
        Observed free bytes on the same evidence volume before transport.
    transport
        Optional HTTPX transport used by deterministic contract tests.

    Returns
    -------
    dict[str, object]
        Sanitized, self-hashed provider availability report.

    Notes
    -----
    A passing report authorizes predictor acquisition only under registered
    timing assumptions. It does not confirm publication or customer receipt
    timestamps and does not authorize outcome/model access.
    """
    _validate_execution_plan(plan)
    validate_storage_gate(free_bytes=free_bytes)
    budget = build_request_budget(asset_count=len(plan.assets), session_count=len(plan.sessions))
    store = _EvidenceStore(raw_root)
    ledger = AttemptLedger(
        http_attempt_cap=budget.http_attempt_cap,
        max_attempts_per_logical_request=MAX_ATTEMPTS_PER_OPERATION,
    )
    client = _Transport(secrets=secrets, store=store, ledger=ledger, transport=transport)
    uw_records: list[dict[str, object]] = []
    fmp_records: list[dict[str, object]] = []
    massive_records: list[dict[str, object]] = []
    blockers: list[str] = []
    spots: dict[tuple[str, str], float] = {}
    try:
        for session in plan.sessions:
            record = _run_uw(client, session)
            uw_records.append(record)
            _append_blocker(record, blockers)
        for session in plan.sessions:
            for asset in plan.assets:
                record = _run_fmp(client, session, asset)
                fmp_records.append(record)
                if record["pass"] is True:
                    spots[(asset, session.date)] = cast(float, record["spot"])
                _append_blocker(record, blockers)
        for session in plan.sessions:
            for asset in plan.assets:
                spot = spots.get((asset, session.date))
                if spot is None:
                    record = _blocked_massive_record(
                        asset=asset,
                        session_date=session.date,
                        reason="MASSIVE_BLOCKED_MISSING_FMP_SPOT",
                    )
                else:
                    record = _run_massive(client, session, asset, spot)
                massive_records.append(record)
                _append_blocker(record, blockers)
    finally:
        client.close()
    all_records = (*uw_records, *fmp_records, *massive_records)
    network_attempt_count = sum(_record_attempt_count(record) for record in all_records)
    expected_fmp = len(plan.assets) * len(plan.sessions)
    expected_uw = len(plan.sessions)
    expected_massive = expected_fmp
    passed_fmp = sum(record["pass"] is True for record in fmp_records)
    passed_uw = sum(record["pass"] is True for record in uw_records)
    passed_massive = sum(record["pass"] is True for record in massive_records)
    passed = (
        passed_fmp == expected_fmp
        and passed_uw == expected_uw
        and passed_massive == expected_massive
        and not blockers
    )
    report: dict[str, object] = {
        "schema_version": "b1v3-provider-preflight-report-2.0",
        "status": (
            "PASS_PROVIDER_PREFLIGHT_ASSUMPTION_BOUND" if passed else "BLOCKED_PROVIDER_PREFLIGHT"
        ),
        "authorization_id": AUTHORIZATION_ID,
        "target_blind": True,
        "outcome_read_count": 0,
        "plan_sha256": plan.plan_sha256,
        "contract_selection_rule_id": CONTRACT_SELECTION_RULE_ID,
        "storage_gate": {
            "minimum_free_bytes": 80 * 1024**3,
            "observed_free_bytes": free_bytes,
            "status": "PASS",
        },
        "request_budget": asdict(budget),
        "network_attempt_count": network_attempt_count,
        "provider_counts": {
            "fmp": {"expected": expected_fmp, "passed": passed_fmp},
            "unusual_whales": {"expected": expected_uw, "passed": passed_uw},
            "massive": {"expected": expected_massive, "passed": passed_massive},
        },
        "records": {
            "fmp": fmp_records,
            "unusual_whales": uw_records,
            "massive": massive_records,
        },
        "blocking_reasons": sorted(set(blockers)),
        "safe_to_acquire_predictors": passed,
        "safe_to_read_outcomes": False,
        "pit_semantics_confirmed": False,
        "timing_boundary": {
            "fmp": "PLUS_1_MINUTE_RESEARCH_ASSUMPTION_PLUS_2_SENSITIVITY",
            "unusual_whales": "CREATED_AT_OPERATIONAL_PROXY_NOT_PUBLICATION_TIME",
            "massive": "SIP_SOURCE_TIME_ASOF_NOT_REST_RECEIPT_TIME",
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
            "credentialed_urls_emitted": False,
            "uw_zip_body_downloaded": False,
        },
    }
    report["report_sha256"] = _sha256_hex(report)
    return report


def render_report(report: Mapping[str, object]) -> bytes:
    """Validate and render a report with deterministic self-hash bytes."""
    declared = report.get("report_sha256")
    payload = dict(report)
    payload.pop("report_sha256", None)
    if not isinstance(declared, str) or declared != _sha256_hex(payload):
        raise B1V3PreflightError("B1V3_PREFLIGHT_REPORT_HASH_INVALID")
    return canonical_json(report) + b"\n"


def write_if_identical(path: Path, content: bytes) -> str:
    """Create immutable evidence or accept a byte-identical replay."""
    try:
        if path.exists():
            if path.read_bytes() == content:
                return "IDENTICAL"
            raise B1V3PreflightError("B1V3_PREFLIGHT_REPORT_OUTPUT_CONFLICT")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError as exc:
        raise B1V3PreflightError("B1V3_PREFLIGHT_REPORT_WRITE_FAILED") from exc
    return "CREATED"


def _run_fmp(
    client: _Transport,
    session: CandidateSession,
    asset: str,
) -> dict[str, object]:
    key = f"fmp/{session.date}/{asset}.json"
    try:
        response = client.json_request(
            provider="fmp",
            operation_id=f"fmp:minute_bars:{session.date}:{asset}",
            evidence_key=key,
            url=f"{FMP_BASE_URL}/stable/historical-chart/1min",
            params={
                "symbol": asset,
                "from": session.date,
                "to": session.date,
                "extended": "false",
                "nonadjusted": "false",
            },
        )
        if response.status_code != 200:
            raise B1V3PreflightError(f"FMP_HTTP_{response.status_code}")
        evidence = validate_fmp_session(
            response.payload,
            session_date=session.date,
            expected_minutes=session.expected_regular_minutes,
            forecast_origin_utc=datetime.fromisoformat(session.forecast_origin_utc),
        )
        return {
            "provider": "fmp",
            "asset": asset,
            "session_date": session.date,
            "pass": True,
            "status": evidence.status,
            "reason": None,
            "spot": evidence.spot,
            "returned_row_count": evidence.returned_row_count,
            "exact_session_row_count": evidence.exact_session_row_count,
            "provider_over_return_count": evidence.provider_over_return_count,
            "evidence_key": key,
            "request_fingerprint": response.request_fingerprint,
            "response_sha256": response.response_sha256,
            "network_attempts": response.network_attempts,
            "pit_claim": False,
        }
    except B1V3PreflightError as exc:
        return _failure_record(
            provider="fmp",
            asset=asset,
            session_date=session.date,
            evidence_key=key,
            reason=str(exc),
            response=locals().get("response"),
        )


def _run_uw(client: _Transport, session: CandidateSession) -> dict[str, object]:
    key = f"unusual_whales/{session.date}/full_tape_metadata.json"
    try:
        response = client.uw_zip_metadata(session_date=session.date, evidence_key=key)
        payload = response.payload
        if not isinstance(payload, Mapping):
            raise B1V3PreflightError("B1V3_PREFLIGHT_UW_CACHE_INVALID")
        method = payload.get("method")
        request_headers = payload.get("request_headers")
        if not isinstance(method, str) or not isinstance(request_headers, Mapping):
            raise B1V3PreflightError("B1V3_PREFLIGHT_UW_CACHE_INVALID")
        evidence = validate_uw_zip_headers(
            status_code=response.status_code,
            headers=response.headers,
            method=method,
            request_headers=cast(Mapping[str, str], request_headers),
        )
        return {
            "provider": "unusual_whales",
            "asset": None,
            "session_date": session.date,
            "pass": True,
            "status": evidence.status,
            "reason": None,
            "content_length_bytes": evidence.content_length_bytes,
            "request_id": evidence.request_id,
            "evidence_key": key,
            "request_fingerprint": response.request_fingerprint,
            "response_sha256": response.response_sha256,
            "network_attempts": response.network_attempts,
            "pit_claim": False,
            "full_tape_downloaded": False,
        }
    except B1V3PreflightError as exc:
        return _failure_record(
            provider="unusual_whales",
            asset=None,
            session_date=session.date,
            evidence_key=key,
            reason=str(exc),
            response=locals().get("response"),
        )


def _run_massive(
    client: _Transport,
    session: CandidateSession,
    asset: str,
    spot: float,
) -> dict[str, object]:
    base_key = f"massive/{session.date}/{asset}"
    responses: list[_CachedResponse] = []
    try:
        candidates, search_responses = _massive_candidates(client, session, asset, spot, base_key)
        responses.extend(search_responses)
        selected_grid = select_contract_grid(
            candidates,
            asset=asset,
            as_of=date.fromisoformat(session.date),
            spot=spot,
        )
        selected = _select_preflight_contract(selected_grid)
        reference = client.json_request(
            provider="massive",
            operation_id=f"massive:contract_reference:{session.date}:{asset}",
            evidence_key=f"{base_key}/reference_asof_v2.json",
            url=f"{MASSIVE_BASE_URL}/v3/reference/options/contracts/{selected.contract_id}",
            params={"as_of": session.date},
        )
        responses.append(reference)
        _validate_massive_reference(reference, asset=asset, contract_id=selected.contract_id)
        quote = client.json_request(
            provider="massive",
            operation_id=f"massive:quote_as_of:{session.date}:{asset}",
            evidence_key=f"{base_key}/quote.json",
            url=f"{MASSIVE_BASE_URL}/v3/quotes/{selected.contract_id}",
            params={
                "timestamp.lte": session.forecast_origin_ns,
                "sort": "timestamp",
                "order": "desc",
                "limit": 1,
            },
        )
        responses.append(quote)
        if quote.status_code != 200:
            raise B1V3PreflightError(f"MASSIVE_QUOTE_HTTP_{quote.status_code}")
        evidence = validate_massive_quote(
            quote.payload,
            forecast_origin_ns=session.forecast_origin_ns,
            contract_id=selected.contract_id,
        )
        return {
            "provider": "massive",
            "asset": asset,
            "session_date": session.date,
            "pass": True,
            "status": evidence.status,
            "reason": None,
            "contract_id": selected.contract_id,
            "expiry": selected.expiry.isoformat(),
            "dte": selected.dte,
            "target_moneyness": selected.target_moneyness,
            "quote_age_seconds": evidence.quote_age_seconds,
            "relative_spread": evidence.relative_spread,
            "sip_timestamp_ns": evidence.sip_timestamp_ns,
            "primary_filter_pass": evidence.primary_filter_pass,
            "sensitivity_filter_pass": evidence.sensitivity_filter_pass,
            "evidence_keys": [response.evidence_key for response in responses],
            "request_fingerprints": [response.request_fingerprint for response in responses],
            "response_sha256": [response.response_sha256 for response in responses],
            "network_attempts": sum(response.network_attempts for response in responses),
            "pit_receipt_claim": False,
        }
    except (B1V3PreflightError, ValueError) as exc:
        return {
            "provider": "massive",
            "asset": asset,
            "session_date": session.date,
            "pass": False,
            "status": "BLOCKED",
            "reason": str(exc),
            "evidence_keys": [response.evidence_key for response in responses],
            "request_fingerprints": [response.request_fingerprint for response in responses],
            "response_sha256": [response.response_sha256 for response in responses],
            "network_attempts": sum(response.network_attempts for response in responses),
            "pit_receipt_claim": False,
        }


def _massive_candidates(
    client: _Transport,
    session: CandidateSession,
    asset: str,
    spot: float,
    base_key: str,
) -> tuple[tuple[HistoricalOptionContract, ...], list[_CachedResponse]]:
    as_of = date.fromisoformat(session.date)
    common_params: dict[str, str | int | float | bool] = {
        "underlying_ticker": asset,
        "as_of": session.date,
        "expiration_date.gte": (as_of + timedelta(days=30)).isoformat(),
        "expiration_date.lte": (as_of + timedelta(days=60)).isoformat(),
        "strike_price.gte": round(spot * 0.975, 4),
        "strike_price.lte": round(spot * 1.025, 4),
        "limit": 1000,
        "sort": "expiration_date",
        "order": "asc",
    }
    responses: list[_CachedResponse] = []
    rows: list[Mapping[str, object]] = []
    search_index = 0
    for expired in (True, False):
        if rows:
            break
        next_url: str | None = f"{MASSIVE_BASE_URL}/v3/reference/options/contracts"
        next_params: dict[str, str | int | float | bool] = {**common_params, "expired": expired}
        while next_url is not None:
            if search_index >= 3:
                raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_PAGINATION_CAP_EXCEEDED")
            search_index += 1
            response = client.json_request(
                provider="massive",
                operation_id=f"massive:contract_search:{session.date}:{asset}:{search_index}",
                evidence_key=f"{base_key}/search_medium_atm_v3_{search_index}.json",
                url=next_url,
                params=next_params,
            )
            responses.append(response)
            if response.status_code != 200 or not isinstance(response.payload, Mapping):
                raise B1V3PreflightError(f"MASSIVE_SEARCH_HTTP_{response.status_code}")
            page_rows = response.payload.get("results", [])
            if not isinstance(page_rows, list) or not all(
                isinstance(row, Mapping) for row in page_rows
            ):
                raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_CONTRACT_SCHEMA_INVALID")
            rows.extend(cast(list[Mapping[str, object]], page_rows))
            raw_next = response.payload.get("next_url")
            if raw_next is None:
                next_url = None
            elif isinstance(raw_next, str) and raw_next:
                next_url, next_params = _normalized_massive_next_url(raw_next)
            else:
                raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_NEXT_URL_INVALID")
    if not rows:
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_NO_HISTORICAL_CONTRACT")
    return tuple(_historical_contract(row) for row in rows), responses


def _historical_contract(row: Mapping[str, object]) -> HistoricalOptionContract:
    try:
        contract_id = row["ticker"]
        underlying = row["underlying_ticker"]
        expiry = row["expiration_date"]
        strike = row["strike_price"]
        option_type = row["contract_type"]
        if (
            not isinstance(contract_id, str)
            or not isinstance(underlying, str)
            or not isinstance(expiry, str)
            or isinstance(strike, bool)
            or not isinstance(strike, int | float)
            or not isinstance(option_type, str)
        ):
            raise TypeError
        return HistoricalOptionContract(
            contract_id=contract_id,
            underlying_ticker=underlying,
            expiry=date.fromisoformat(expiry),
            strike=float(strike),
            option_type=option_type,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_CONTRACT_SCHEMA_INVALID") from exc


def _select_preflight_contract(grid: tuple[SelectedContract, ...]) -> SelectedContract:
    for option_type in ("call", "put"):
        for contract in grid:
            if (
                contract.bucket == "medium"
                and contract.target_moneyness == 1.0
                and contract.option_type == option_type
            ):
                return contract
    raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_ATM_MEDIUM_CONTRACT_MISSING")


def _validate_massive_reference(
    response: _CachedResponse,
    *,
    asset: str,
    contract_id: str,
) -> None:
    if response.status_code != 200 or not isinstance(response.payload, Mapping):
        raise B1V3PreflightError(f"MASSIVE_REFERENCE_HTTP_{response.status_code}")
    result = response.payload.get("results")
    if not isinstance(result, Mapping):
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_REFERENCE_SCHEMA_INVALID")
    if result.get("ticker") != contract_id or result.get("underlying_ticker") != asset:
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_REFERENCE_MISMATCH")


def _blocked_massive_record(
    *,
    asset: str,
    session_date: str,
    reason: str,
) -> dict[str, object]:
    return {
        "provider": "massive",
        "asset": asset,
        "session_date": session_date,
        "pass": False,
        "status": "BLOCKED",
        "reason": reason,
        "evidence_keys": [],
        "request_fingerprints": [],
        "response_sha256": [],
        "network_attempts": 0,
        "pit_receipt_claim": False,
    }


def _failure_record(
    *,
    provider: str,
    asset: str | None,
    session_date: str,
    evidence_key: str,
    reason: str,
    response: object,
) -> dict[str, object]:
    cached = response if isinstance(response, _CachedResponse) else None
    return {
        "provider": provider,
        "asset": asset,
        "session_date": session_date,
        "pass": False,
        "status": "BLOCKED",
        "reason": reason,
        "evidence_key": evidence_key,
        "request_fingerprint": cached.request_fingerprint if cached else None,
        "response_sha256": cached.response_sha256 if cached else None,
        "network_attempts": cached.network_attempts if cached else 0,
        "pit_claim": False,
    }


def _append_blocker(record: Mapping[str, object], blockers: list[str]) -> None:
    if record.get("pass") is True:
        return
    provider = record.get("provider")
    session_date = record.get("session_date")
    asset = record.get("asset") or "shared"
    reason = record.get("reason") or "UNKNOWN"
    blockers.append(f"{provider}:{session_date}:{asset}:{reason}")


def _cached_response(decoded: Mapping[str, object], *, evidence_key: str) -> _CachedResponse:
    provider = decoded.get("provider")
    fingerprint = decoded.get("request_fingerprint")
    status_code = decoded.get("status_code")
    headers = decoded.get("headers")
    response_sha256 = decoded.get("response_sha256")
    attempts = decoded.get("network_attempts")
    if (
        not isinstance(provider, str)
        or not isinstance(fingerprint, str)
        or isinstance(status_code, bool)
        or not isinstance(status_code, int)
        or not isinstance(headers, Mapping)
        or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
        )
        or not isinstance(response_sha256, str)
        or isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or attempts < 1
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_CACHE_INVALID")
    return _CachedResponse(
        provider=provider,
        evidence_key=evidence_key,
        request_fingerprint=fingerprint,
        status_code=status_code,
        headers=cast(Mapping[str, str], headers),
        payload=decoded.get("payload"),
        response_sha256=response_sha256,
        network_attempts=attempts,
    )


def _request_fingerprint(
    *,
    provider: str,
    method: str,
    url: str,
    params: Mapping[str, object],
    headers: Mapping[str, str],
) -> str:
    parsed = urlsplit(url)
    safe_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"apiKey", "apikey"}
    ]
    safe_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    normalized_params = {
        key: value for key, value in params.items() if key not in {"apiKey", "apikey"}
    }
    return _sha256_hex(
        {
            "provider": provider,
            "method": method,
            "url": safe_url,
            "url_query": sorted(safe_query),
            "params": normalized_params,
            "headers": dict(sorted(headers.items())),
        }
    )


def _sanitized_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in {"authorization", "apikey", "api-key"}
    }


def _sanitized_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        "content-type",
        "content-length",
        "x-request-id",
        "request-id",
        "retry-after",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-reset",
    }
    return {key.lower(): value for key, value in headers.items() if key.lower() in allowed}


def _normalized_massive_next_url(
    next_url: str,
) -> tuple[str, dict[str, str | int | float | bool]]:
    parsed = urlsplit(next_url)
    if parsed.scheme != "https" or parsed.netloc != "api.massive.com":
        raise B1V3PreflightError("B1V3_PREFLIGHT_MASSIVE_NEXT_URL_INVALID")
    params: dict[str, str | int | float | bool] = {
        key: value
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "apiKey"
    }
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")), params


def _retry_delay(headers: Mapping[str, str], attempt: int) -> float:
    raw = headers.get("retry-after")
    if raw is not None:
        try:
            return min(max(float(raw), 0.0), 60.0)
        except ValueError:
            pass
    return float(min(0.5 * 2 ** (attempt - 1), 60.0))


def _record_attempt_count(record: Mapping[str, object]) -> int:
    value = record.get("network_attempts", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise B1V3PreflightError("B1V3_PREFLIGHT_NETWORK_ATTEMPT_COUNT_INVALID")
    return value


def _validate_execution_plan(plan: CandidatePreflightPlan) -> None:
    if (
        plan.status != "FROZEN_TARGET_BLIND_PENDING_PROVIDER_EXECUTION"
        or plan.target_blind is not True
        or plan.outcome_read_count != 0
        or not plan.assets
        or not plan.sessions
        or len({session.date for session in plan.sessions}) != len(plan.sessions)
        or len(plan.plan_sha256) != 64
    ):
        raise B1V3PreflightError("B1V3_PREFLIGHT_EXECUTION_PLAN_INVALID")


def _sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
