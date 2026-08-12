from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import re
import socket
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_plan_v1.json"
CATALOG_PATH = ROOT / "config/date_level_pit_preflight_endpoint_catalog_v1.json"
ARTIFACT_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_request_budget_v1.json"
SCHEMA_PATH = ROOT / "config/date_level_pit_preflight_request_budget_v1.schema.json"
DOC_PATH = ROOT / "docs/date_level_pit_preflight_request_budget_v1.md"
MODULE_NAME = "mds650.date_level_pit_preflight_request_budget_v1"


def _json_mapping(path: Path) -> dict[str, object]:
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(decoded, dict)
    return cast(dict[str, object], decoded)


def _module() -> ModuleType:
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "date-level PIT request-budget planner module is required"
    )
    return importlib.import_module(MODULE_NAME)


def _build_request_budget() -> dict[str, object]:
    candidate = getattr(_module(), "build_request_budget", None)
    assert callable(candidate), "build_request_budget contract is required"
    output = candidate(_json_mapping(PLAN_PATH), _json_mapping(CATALOG_PATH))
    assert isinstance(output, dict)
    return cast(dict[str, object], output)


def _render_request_budget(budget: Mapping[str, object]) -> bytes:
    candidate = getattr(_module(), "render_request_budget", None)
    assert callable(candidate), "render_request_budget contract is required"
    output = candidate(budget)
    assert isinstance(output, bytes)
    return output


def test_build_request_budget_derives_session_asset_counts_and_uw_cache() -> None:
    budget = _build_request_budget()

    assert budget["dimensions"] == {
        "asset_count": 8,
        "session_count": 7,
        "asset_day_count": 56,
    }
    assert budget["catalog_descriptor_status"] == {
        "fmp": "CONFIGURED",
        "unusual_whales": "CONFIGURED",
        "massive": "CONFIGURED",
    }
    assert budget["request_budget"] == {
        "fmp_one_minute_requests": 56,
        "unusual_whales_range_metadata_probe_requests": 7,
        "massive_initial_contract_search_requests": 56,
        "massive_initial_contract_reference_conditional_max": 56,
        "massive_initial_quote_as_of_conditional_max": 56,
        "initial_request_count": 119,
        "initial_request_upper_bound_if_all_contracts_resolve": 231,
        "cap_request_count": 343,
    }
    assert budget["unusual_whales_cache_policy"] == {
        "scope": "PER_SESSION_ACROSS_ASSETS",
        "request_count": 7,
    }


def test_build_request_budget_counts_contract_reference_before_quote_as_of() -> None:
    catalog = _json_mapping(CATALOG_PATH)
    endpoints = catalog["endpoints"]
    assert isinstance(endpoints, list)
    massive = endpoints[2]
    assert isinstance(massive, dict)
    routes = massive["routes"]
    assert isinstance(routes, list)
    assert [route["operation"] for route in routes] == [
        "contract_reference",
        "quote_as_of",
    ]

    budget = _build_request_budget()
    request_budget = budget["request_budget"]
    assert isinstance(request_budget, dict)
    massive_contract_pagination = budget["massive_contract_pagination"]
    assert isinstance(massive_contract_pagination, dict)

    assert request_budget.get("massive_initial_contract_reference_conditional_max") == 56
    assert request_budget["initial_request_count"] == 119
    assert request_budget["initial_request_upper_bound_if_all_contracts_resolve"] == 231
    assert request_budget["cap_request_count"] == 343
    assert massive_contract_pagination.get("contract_stage_order") == [
        "contract_search",
        "contract_reference",
        "quote_as_of",
    ]
    assert massive_contract_pagination.get("contract_reference_max_per_asset_day") == 1
    assert massive_contract_pagination.get(
        "contract_reference_only_after_contract_resolution"
    ) is True
    assert massive_contract_pagination.get("quote_as_of_only_after_contract_reference") is True


def test_massive_pagination_gates_contract_reference_and_quote_and_fails_closed_beyond_cap(
) -> None:
    candidate = getattr(_module(), "plan_massive_asset_day_requests", None)
    assert callable(candidate), "plan_massive_asset_day_requests contract is required"
    plan_massive = cast(Callable[..., dict[str, object]], candidate)

    resolved = plan_massive(required_contract_pages=1, contract_resolution_succeeds=True)
    unresolved = plan_massive(required_contract_pages=3, contract_resolution_succeeds=False)
    cap_exceeded = plan_massive(required_contract_pages=4, contract_resolution_succeeds=True)

    assert resolved == {
        "status": "CONTRACT_RESOLVED_WITHIN_PAGE_CAP",
        "contract_search_request_count": 1,
        "contract_reference_request_count": 1,
        "quote_as_of_request_count": 1,
    }
    assert unresolved == {
        "status": "CONTRACT_UNRESOLVED_WITHIN_PAGE_CAP",
        "contract_search_request_count": 3,
        "contract_reference_request_count": 0,
        "quote_as_of_request_count": 0,
    }
    assert cap_exceeded == {
        "status": "FAILED_CLOSED_CONTRACT_PAGINATION_CAP_EXCEEDED",
        "contract_search_request_count": 3,
        "contract_reference_request_count": 0,
        "quote_as_of_request_count": 0,
    }


def test_build_request_budget_rejects_catalog_descriptor_contract_drift() -> None:
    candidate = getattr(_module(), "RequestBudgetError", None)
    assert isinstance(candidate, type), "RequestBudgetError contract is required"
    error_type = cast(type[Exception], candidate)
    catalog = _json_mapping(CATALOG_PATH)
    endpoints = catalog["endpoints"]
    assert isinstance(endpoints, list)
    unusual_whales = endpoints[1]
    assert isinstance(unusual_whales, dict)
    unusual_whales["metadata_only"] = False

    with pytest.raises(error_type, match="REQUEST_BUDGET_CATALOG_DESCRIPTOR_INVALID"):
        _module().build_request_budget(_json_mapping(PLAN_PATH), catalog)


def test_request_budget_render_is_deterministic_schema_valid_and_matches_artifact() -> None:
    first = _build_request_budget()
    second = _build_request_budget()
    output = _render_request_budget(first)
    schema = _json_mapping(SCHEMA_PATH)
    payload = dict(first)
    semantic_self_hash = payload.pop("semantic_self_hash")
    expected_self_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    )

    assert first == second
    assert output == _render_request_budget(second)
    assert output == ARTIFACT_PATH.read_bytes()
    assert output.endswith(os.linesep.encode("ascii"))
    assert semantic_self_hash == expected_self_hash
    assert list(Draft202012Validator(schema).iter_errors(first)) == []


def test_request_budget_materials_emit_no_personal_paths_secrets_or_raw_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def network_forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("network access is forbidden for request-budget planning")

    monkeypatch.setattr(socket, "create_connection", network_forbidden)
    output = _render_request_budget(_build_request_budget()).decode("utf-8")

    assert re.search(r"(?:[A-Za-z]:\\Users\\|/Users/)", output) is None
    assert "request_target" not in output
    assert "/stable/" not in output
    assert "/v3/" not in output
    assert "apiKey=" not in output
    assert "apikey=" not in output
    assert "FMP_API_KEY" not in output
    assert "UNUSUALWHALES_API_KEY" not in output
    assert "MASSIVE_API_KEY" not in output

    for path in (ARTIFACT_PATH, SCHEMA_PATH, DOC_PATH):
        content = path.read_text(encoding="utf-8")
        assert re.search(r"(?:[A-Za-z]:\\Users\\|/Users/)", content) is None, path
        assert "request_target" not in content, path
        assert "/stable/" not in content, path
        assert "/v3/" not in content, path
        assert "apiKey=" not in content, path
        assert "apikey=" not in content, path
