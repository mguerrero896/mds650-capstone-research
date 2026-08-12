"""Pure, target-free request-budget planning for the date-level PIT preflight."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Final, cast

EXPECTED_PROVIDERS: Final[tuple[str, ...]] = ("fmp", "unusual_whales", "massive")
EXPECTED_ASSET_COUNT: Final[int] = 8
EXPECTED_SESSION_COUNT: Final[int] = 7
MAX_CONTRACT_SEARCH_PAGES_PER_ASSET_DAY: Final[int] = 3
PAGINATION_CAP_EXCEEDED_STATUS: Final[str] = "FAILED_CLOSED_CONTRACT_PAGINATION_CAP_EXCEEDED"


class RequestBudgetError(RuntimeError):
    """Fail-closed error for an invalid static request-budget input."""


def canonical_json(value: Mapping[str, object]) -> bytes:
    """Encode a mapping deterministically without filesystem or network access."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def build_request_budget(
    plan: Mapping[str, object], endpoint_catalog: Mapping[str, object]
) -> dict[str, object]:
    """Build static request bounds from fixed dimensions and safe catalog descriptors."""
    asset_count, session_count = _plan_dimensions(plan)
    descriptor_status = _catalog_descriptor_status(endpoint_catalog)
    asset_day_count = asset_count * session_count
    fmp_request_count = asset_day_count
    unusual_whales_request_count = session_count
    massive_initial_contract_search_count = asset_day_count
    massive_initial_quote_conditional_max = asset_day_count
    initial_request_count = (
        fmp_request_count + unusual_whales_request_count + massive_initial_contract_search_count
    )
    initial_request_upper_bound = initial_request_count + massive_initial_quote_conditional_max
    massive_contract_search_cap = MAX_CONTRACT_SEARCH_PAGES_PER_ASSET_DAY * asset_day_count
    cap_request_count = (
        fmp_request_count
        + unusual_whales_request_count
        + massive_contract_search_cap
        + massive_initial_quote_conditional_max
    )

    budget: dict[str, object] = {
        "artifact_type": "date_level_pit_preflight_request_budget_v1",
        "schema_version": "1.0.0",
        "status": "CANDIDATE_AUTHORIZATION_REQUIRED",
        "flags": {
            "NO_PROVIDER_CALLS_EXECUTED": True,
            "NOT_AUTHORIZATION_FOR_ACQUISITION": True,
            "NOT_A_BILLING_CLAIM": True,
        },
        "dimensions": {
            "asset_count": asset_count,
            "session_count": session_count,
            "asset_day_count": asset_day_count,
        },
        "catalog_descriptor_status": descriptor_status,
        "unusual_whales_cache_policy": {
            "scope": "PER_SESSION_ACROSS_ASSETS",
            "request_count": unusual_whales_request_count,
        },
        "massive_contract_pagination": {
            "max_contract_pages_per_asset_day": MAX_CONTRACT_SEARCH_PAGES_PER_ASSET_DAY,
            "contract_search_request_cap": massive_contract_search_cap,
            "quote_as_of_max_per_asset_day": 1,
            "quote_as_of_only_after_contract_resolution": True,
            "pagination_exceed_status": PAGINATION_CAP_EXCEEDED_STATUS,
        },
        "request_budget": {
            "fmp_one_minute_requests": fmp_request_count,
            "unusual_whales_range_metadata_probe_requests": unusual_whales_request_count,
            "massive_initial_contract_search_requests": massive_initial_contract_search_count,
            "massive_initial_quote_as_of_conditional_max": massive_initial_quote_conditional_max,
            "initial_request_count": initial_request_count,
            "initial_request_upper_bound_if_all_contracts_resolve": initial_request_upper_bound,
            "cap_request_count": cap_request_count,
        },
        "cost_authorization": {
            "status": "EXTERNAL_AUTHORIZATION_REQUIRED_NOT_A_BILLING_CLAIM",
            "cost_amount_claimed": False,
        },
        "security": {
            "secret_values_emitted": False,
            "personal_paths_emitted": False,
            "raw_endpoint_details_emitted": False,
        },
        "semantic_hash_scope": "canonical-json-excluding-semantic_self_hash",
    }
    budget["semantic_self_hash"] = _semantic_self_hash(budget)
    return budget


def plan_massive_asset_day_requests(
    *, required_contract_pages: int, contract_resolution_succeeds: bool
) -> dict[str, object]:
    """Return one asset-day's bounded Massive request plan without making requests."""
    if (
        isinstance(required_contract_pages, bool)
        or not isinstance(required_contract_pages, int)
        or required_contract_pages < 1
        or not isinstance(contract_resolution_succeeds, bool)
    ):
        raise RequestBudgetError("REQUEST_BUDGET_PAGINATION_INPUT_INVALID")
    if required_contract_pages > MAX_CONTRACT_SEARCH_PAGES_PER_ASSET_DAY:
        return {
            "status": PAGINATION_CAP_EXCEEDED_STATUS,
            "contract_search_request_count": MAX_CONTRACT_SEARCH_PAGES_PER_ASSET_DAY,
            "quote_as_of_request_count": 0,
        }
    return {
        "status": (
            "CONTRACT_RESOLVED_WITHIN_PAGE_CAP"
            if contract_resolution_succeeds
            else "CONTRACT_UNRESOLVED_WITHIN_PAGE_CAP"
        ),
        "contract_search_request_count": required_contract_pages,
        "quote_as_of_request_count": 1 if contract_resolution_succeeds else 0,
    }


def render_request_budget(budget: Mapping[str, object]) -> bytes:
    """Render a deterministic JSON artifact without timestamps or external state."""
    return canonical_json(budget) + os.linesep.encode("ascii")


def _plan_dimensions(plan: Mapping[str, object]) -> tuple[int, int]:
    raw_assets = plan.get("assets")
    raw_sessions = plan.get("sentinel_sessions")
    if not isinstance(raw_assets, list) or not isinstance(raw_sessions, list):
        raise RequestBudgetError("REQUEST_BUDGET_DIMENSIONS_INVALID")
    assets = [asset for asset in raw_assets if isinstance(asset, str) and asset]
    if len(assets) != len(raw_assets) or len(set(assets)) != EXPECTED_ASSET_COUNT:
        raise RequestBudgetError("REQUEST_BUDGET_DIMENSIONS_INVALID")
    session_dates: list[str] = []
    for session in raw_sessions:
        if not isinstance(session, Mapping):
            raise RequestBudgetError("REQUEST_BUDGET_DIMENSIONS_INVALID")
        session_date = session.get("date")
        if not isinstance(session_date, str) or not session_date:
            raise RequestBudgetError("REQUEST_BUDGET_DIMENSIONS_INVALID")
        session_dates.append(session_date)
    if (
        len(assets) != EXPECTED_ASSET_COUNT
        or len(session_dates) != EXPECTED_SESSION_COUNT
        or len(set(session_dates)) != EXPECTED_SESSION_COUNT
    ):
        raise RequestBudgetError("REQUEST_BUDGET_DIMENSIONS_INVALID")
    return len(assets), len(session_dates)


def _catalog_descriptor_status(endpoint_catalog: Mapping[str, object]) -> dict[str, str]:
    raw_endpoints = endpoint_catalog.get("endpoints")
    if not isinstance(raw_endpoints, list):
        raise RequestBudgetError("REQUEST_BUDGET_CATALOG_DESCRIPTOR_INVALID")
    descriptors: dict[str, Mapping[str, object]] = {}
    for raw_descriptor in raw_endpoints:
        if not isinstance(raw_descriptor, Mapping):
            raise RequestBudgetError("REQUEST_BUDGET_CATALOG_DESCRIPTOR_INVALID")
        provider = raw_descriptor.get("provider")
        if not isinstance(provider, str) or provider in descriptors:
            raise RequestBudgetError("REQUEST_BUDGET_CATALOG_DESCRIPTOR_INVALID")
        descriptors[provider] = cast(Mapping[str, object], raw_descriptor)
    if set(descriptors) != set(EXPECTED_PROVIDERS):
        raise RequestBudgetError("REQUEST_BUDGET_CATALOG_DESCRIPTOR_INVALID")
    if not _is_fmp_descriptor(descriptors["fmp"]):
        raise RequestBudgetError("REQUEST_BUDGET_CATALOG_DESCRIPTOR_INVALID")
    if not _is_unusual_whales_descriptor(descriptors["unusual_whales"]):
        raise RequestBudgetError("REQUEST_BUDGET_CATALOG_DESCRIPTOR_INVALID")
    if not _is_massive_descriptor(descriptors["massive"]):
        raise RequestBudgetError("REQUEST_BUDGET_CATALOG_DESCRIPTOR_INVALID")
    return {provider: "CONFIGURED" for provider in EXPECTED_PROVIDERS}


def _is_fmp_descriptor(descriptor: Mapping[str, object]) -> bool:
    return (
        descriptor.get("endpoint_id") == "fmp-underlying-1min"
        and descriptor.get("method") == "GET"
        and descriptor.get("metadata_only") is False
    )


def _is_unusual_whales_descriptor(descriptor: Mapping[str, object]) -> bool:
    range_probe = descriptor.get("range_probe")
    return (
        descriptor.get("endpoint_id") == "uw-full-tape-historical-range-probe"
        and descriptor.get("method") == "METADATA_ONLY"
        and descriptor.get("metadata_only") is True
        and isinstance(range_probe, Mapping)
        and range_probe.get("dataset") == "full_tape_historical"
        and range_probe.get("mode") == "metadata_only"
    )


def _is_massive_descriptor(descriptor: Mapping[str, object]) -> bool:
    routes = descriptor.get("routes")
    if not isinstance(routes, list):
        return False
    operations: list[str] = []
    for route in routes:
        if not isinstance(route, Mapping):
            return False
        operation = route.get("operation")
        if not isinstance(operation, str):
            return False
        operations.append(operation)
    return (
        descriptor.get("endpoint_id") == "massive-contract-reference-and-quote-asof"
        and descriptor.get("method") == "GET"
        and descriptor.get("metadata_only") is False
        and tuple(operations) == ("contract_reference", "quote_as_of")
    )


def _semantic_self_hash(payload: Mapping[str, object]) -> str:
    normalized = dict(payload)
    normalized.pop("semantic_self_hash", None)
    return f"sha256:{hashlib.sha256(canonical_json(normalized)).hexdigest()}"
