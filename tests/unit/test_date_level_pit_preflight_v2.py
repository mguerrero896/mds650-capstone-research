from __future__ import annotations

import importlib
import importlib.util
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_plan_v1.json"
CATALOG_PATH = ROOT / "config/date_level_pit_preflight_endpoint_catalog_v2.json"
BUDGET_PATH = ROOT / "artifacts/preflight/date_level_pit_preflight_request_budget_v2.json"
MODULE_NAME = "mds650.date_level_pit_preflight_v2"
MODULE_PATH = ROOT / "src/mds650/date_level_pit_preflight_v2.py"


def _json_mapping(path: Path) -> dict[str, object]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(decoded, dict)
    return cast(dict[str, object], decoded)


def _module() -> ModuleType:
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "date-level PIT v2 operation planner module is required"
    )
    return importlib.import_module(MODULE_NAME)


def _operation_plan() -> object:
    return _module().build_operation_plan(
        _json_mapping(PLAN_PATH),
        _json_mapping(CATALOG_PATH),
        _json_mapping(BUDGET_PATH),
    )


def test_build_operation_plan_derives_bounded_initial_operations_and_attempt_cap() -> None:
    candidate = getattr(_module(), "build_operation_plan", None)
    assert callable(candidate), "v2 operation-plan builder is required"

    operation_plan = _operation_plan()

    assert operation_plan.logical_request_cap == 343
    assert operation_plan.max_attempts_per_logical_request == 3
    assert operation_plan.http_attempt_cap == 343
    assert (
        operation_plan.source_fingerprint.plan_sha256
        == _json_mapping(PLAN_PATH)["semantic_self_hash"]
    )
    assert (
        operation_plan.source_fingerprint.budget_sha256
        == _json_mapping(BUDGET_PATH)["semantic_self_hash"]
    )
    assert operation_plan.source_fingerprint.composite_sha256.startswith("sha256:")
    assert operation_plan.contract_selection_rule_id is None

    operations = operation_plan.initial_operations
    assert len(operations) == 119
    fmp_operations = [
        operation for operation in operations if operation.kind.value == "minute_bars"
    ]
    assert len(fmp_operations) == 56
    assert {(operation.session_date, operation.asset) for operation in fmp_operations} == {
        (session["date"], asset)
        for session in _json_mapping(PLAN_PATH)["sentinel_sessions"]
        for asset in _json_mapping(PLAN_PATH)["assets"]
    }
    assert {operation.disposition.value for operation in fmp_operations} == {
        "DATE_BOUNDED_ONLY_NO_PIT_CLAIM"
    }
    assert all(operation.execution_permitted is False for operation in fmp_operations)

    uw_operations = [
        operation for operation in operations if operation.kind.value == "full_tape_zip_download"
    ]
    assert len(uw_operations) == 7
    assert all(operation.asset is None for operation in uw_operations)
    assert all(operation.shared_across_assets for operation in uw_operations)
    assert {operation.disposition.value for operation in uw_operations} == {
        "DOCUMENTED_ROUTE_EXECUTION_GATED"
    }
    contract_searches = [
        operation for operation in operations if operation.kind.value == "contract_search"
    ]
    assert len(contract_searches) == 56
    assert {operation.page for operation in contract_searches} == {1}
    assert all(
        operation.origin_ns is not None and len(str(operation.origin_ns)) == 19
        for operation in contract_searches
    )
    assert {operation.disposition.value for operation in contract_searches} == {
        "CONTRACT_UNRESOLVED_NO_EXECUTION"
    }
    assert not [
        operation for operation in operations if operation.kind.value == "contract_reference"
    ]
    assert not [operation for operation in operations if operation.kind.value == "quote_as_of"]


def test_operation_plan_binds_the_versioned_documented_uw_zip_contract() -> None:
    """The v2 planner must reject the retired, undocumented Range-only contract."""
    module = _module()

    operation_plan = module.build_operation_plan(
        _json_mapping(PLAN_PATH),
        _json_mapping(CATALOG_PATH),
        _json_mapping(BUDGET_PATH),
    )

    unusual_whales = [
        operation
        for operation in operation_plan.initial_operations
        if operation.provider is module.Provider.UNUSUAL_WHALES
    ]
    assert len(unusual_whales) == 7
    assert {operation.kind.value for operation in unusual_whales} == {"full_tape_zip_download"}
    assert all(
        operation.disposition is module.OperationDisposition.DOCUMENTED_ROUTE_EXECUTION_GATED
        for operation in unusual_whales
    )


def test_source_fingerprint_validates_all_three_immutable_sources() -> None:
    candidate = getattr(_module(), "validate_source_fingerprint", None)
    assert callable(candidate), "v2 source-fingerprint validator is required"
    plan = _json_mapping(PLAN_PATH)
    catalog = _json_mapping(CATALOG_PATH)
    budget = _json_mapping(BUDGET_PATH)
    operation_plan = _module().build_operation_plan(plan, catalog, budget)

    assert candidate(operation_plan.source_fingerprint, plan, catalog, budget) is None

    changed_catalog = _json_mapping(CATALOG_PATH)
    endpoints = changed_catalog["endpoints"]
    assert isinstance(endpoints, list)
    changed_catalog["endpoints"] = list(reversed(endpoints))

    error_type = _module().PitPreflightV2Error
    with pytest.raises(error_type, match="PREFLIGHT_V2_SOURCE_FINGERPRINT_MISMATCH"):
        candidate(operation_plan.source_fingerprint, plan, changed_catalog, budget)


def test_approval_matching_revalidates_schema_before_comparing_composite_identity() -> None:
    module = _module()
    plan = _json_mapping(PLAN_PATH)
    catalog = _json_mapping(CATALOG_PATH)
    budget = _json_mapping(BUDGET_PATH)
    fingerprint = module.build_source_fingerprint(plan, catalog, budget)

    assert (
        module.match_approved_composite_fingerprint(
            fingerprint.composite_sha256,
            plan,
            catalog,
            budget,
        )
        is module.ApprovalStatus.MATCH
    )

    invalid_plan = dict(plan)
    invalid_plan["status"] = "INVALID"
    with pytest.raises(module.PitPreflightV2Error, match="PREFLIGHT_V2_PLAN_SCHEMA_INVALID"):
        module.match_approved_composite_fingerprint(
            fingerprint.composite_sha256,
            invalid_plan,
            catalog,
            budget,
        )


def test_massive_search_stays_unresolved_without_a_catalog_selection_rule() -> None:
    module = _module()
    operation_plan = _operation_plan()
    search = next(
        operation
        for operation in operation_plan.initial_operations
        if operation.kind is module.OperationKind.CONTRACT_SEARCH
    )
    state = module.initial_massive_asset_session_state(search)
    resolution = module.ContractResolution(
        rule_id="typed-contract-selection",
        contract_candidate="contract-candidate",
    )

    transition = module.resolve_massive_contract_candidate(
        operation_plan,
        state,
        resolution,
    )

    assert transition.next_operation is None
    assert transition.state.disposition is (
        module.OperationDisposition.CONTRACT_UNRESOLVED_NO_EXECUTION
    )
    assert transition.state.contract_candidate_count == 0
    assert transition.state.contract_reference_count == 0
    assert transition.state.quote_count == 0


def test_massive_state_machine_bounds_search_pages_and_fails_closed_before_page_four() -> None:
    module = _module()
    operation_plan = _operation_plan()
    search = next(
        operation
        for operation in operation_plan.initial_operations
        if operation.kind is module.OperationKind.CONTRACT_SEARCH
    )
    state = module.initial_massive_asset_session_state(search)

    second_page = module.advance_massive_contract_search_page(state, requires_next_page=True)
    assert second_page.next_operation is not None
    assert second_page.next_operation.page == 2

    third_page = module.advance_massive_contract_search_page(
        second_page.state,
        requires_next_page=True,
    )
    assert third_page.next_operation is not None
    assert third_page.next_operation.page == 3

    cap_failure = module.advance_massive_contract_search_page(
        third_page.state,
        requires_next_page=True,
    )
    assert cap_failure.next_operation is None
    assert cap_failure.state.disposition is module.OperationDisposition.FAIL_CLOSED
    assert cap_failure.failure is module.FailureClassification.PAGINATION_ERROR
    assert cap_failure.state.contract_candidate_count == 0
    assert cap_failure.state.contract_reference_count == 0
    assert cap_failure.state.quote_count == 0


def test_quote_as_of_requires_a_valid_reference_and_carries_fixed_ns_parameters() -> None:
    module = _module()
    operation_plan = _operation_plan()
    search = next(
        operation
        for operation in operation_plan.initial_operations
        if operation.kind is module.OperationKind.CONTRACT_SEARCH
    )
    assert search.asset is not None
    assert search.origin_ns is not None
    state = module.MassiveAssetSessionState(
        asset=search.asset,
        session_date=search.session_date,
        origin_ns=search.origin_ns,
        stage=module.MassiveStage.CONTRACT_REFERENCE,
        current_page=1,
        contract_candidate="contract-candidate",
        contract_candidate_count=1,
        contract_reference_count=0,
        quote_count=0,
        reference_validated=False,
        disposition=module.OperationDisposition.LOCAL_CONTRACT_PENDING_OFFICIAL_MACHINE_READABLE_CONFIRMATION,
        failure=None,
    )

    transition = module.validate_massive_contract_reference(
        state,
        module.ProviderObservation(
            http_status=200,
            entitlement_error=False,
            schema_valid=True,
            pagination_valid=True,
        ),
    )

    quote = transition.next_operation
    assert quote is not None
    assert quote.kind is module.OperationKind.QUOTE_AS_OF
    assert quote.origin_ns == search.origin_ns
    assert len(str(quote.origin_ns)) == 19
    assert quote.quote_parameters is not None
    assert quote.quote_parameters.as_mapping() == {
        "timestamp.lte": search.origin_ns,
        "sort": "timestamp",
        "order": "desc",
        "limit": 1,
    }
    assert quote.disposition is (
        module.OperationDisposition.LOCAL_CONTRACT_PENDING_OFFICIAL_MACHINE_READABLE_CONFIRMATION
    )
    assert quote.execution_permitted is False
    assert transition.state.contract_candidate_count == 1
    assert transition.state.contract_reference_count == 1
    assert transition.state.quote_count == 1


@pytest.mark.parametrize(
    ("observation", "expected_failure"),
    [
        (
            {
                "http_status": 503,
                "entitlement_error": False,
                "schema_valid": True,
                "pagination_valid": True,
            },
            "NON_2XX",
        ),
        (
            {
                "http_status": 403,
                "entitlement_error": True,
                "schema_valid": True,
                "pagination_valid": True,
            },
            "ENTITLEMENT_ERROR",
        ),
        (
            {
                "http_status": 200,
                "entitlement_error": False,
                "schema_valid": False,
                "pagination_valid": True,
            },
            "SCHEMA_ERROR",
        ),
        (
            {
                "http_status": 200,
                "entitlement_error": False,
                "schema_valid": True,
                "pagination_valid": False,
            },
            "PAGINATION_ERROR",
        ),
    ],
)
def test_provider_failures_are_fail_closed_not_completed(
    observation: dict[str, bool | int],
    expected_failure: str,
) -> None:
    module = _module()
    operation = next(
        operation
        for operation in _operation_plan().initial_operations
        if operation.kind is module.OperationKind.MINUTE_BARS
    )

    assessment = module.evaluate_provider_observation(
        operation,
        module.ProviderObservation(**observation),
    )

    assert assessment.disposition is module.OperationDisposition.FAIL_CLOSED
    assert assessment.failure is getattr(module.FailureClassification, expected_failure)


def test_successful_fmp_observation_remains_date_bounded_and_not_a_pit_completion() -> None:
    module = _module()
    operation = next(
        operation
        for operation in _operation_plan().initial_operations
        if operation.kind is module.OperationKind.MINUTE_BARS
    )

    assessment = module.evaluate_provider_observation(
        operation,
        module.ProviderObservation(
            http_status=200,
            entitlement_error=False,
            schema_valid=True,
            pagination_valid=True,
        ),
    )

    assert assessment.failure is None
    assert assessment.disposition is module.OperationDisposition.DATE_BOUNDED_ONLY_NO_PIT_CLAIM


def test_historical_availability_pass_does_not_override_the_pit_network_gate() -> None:
    """Availability and timestamp semantics remain distinct, fail-closed states."""
    module = _module()
    availability = module.current_historical_source_availability()
    operation_plan = _operation_plan()

    assert availability.status is module.HistoricalAvailabilityStatus.PASS_SEPARATE_FROM_PIT
    assert (
        availability.fmp_status is module.ProviderHistoricalAvailability.FMP_PASS_90_OF_90_SESSIONS
    )
    assert (
        availability.unusual_whales_status
        is module.ProviderHistoricalAvailability.UW_PASS_90_OF_90_FILE_METADATA
    )
    assert availability.fmp_evidence_sha256 == (
        "97c3b57707a953629ff57e485cde918e52ecdd1777a246e84072b5c4150771dc"
    )
    assert availability.unusual_whales_evidence_sha256 == (
        "244690e15054f518e5d12083e6b81d2bcbfcd8f5f009304f4127cbb5c1c4a3f3"
    )
    assert operation_plan.historical_availability == availability
    assert operation_plan.network_gate.execution_permitted is False
    assert operation_plan.network_gate.status is module.NetworkGateStatus.NETWORK_BLOCKED


def test_atomic_attempt_ledger_counts_each_retry_inside_the_inclusive_global_cap() -> None:
    module = _module()
    ledger = module.AttemptLedger()

    def reserve(operation_number: int) -> bool:
        try:
            ledger.reserve_attempt(f"operation-{operation_number}")
        except module.AttemptBudgetError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as executor:
        accepted = list(executor.map(reserve, range(350)))

    snapshot = ledger.snapshot()
    assert accepted.count(True) == 343
    assert accepted.count(False) == 7
    assert snapshot.reserved_logical_request_count == 343
    assert snapshot.reserved_http_attempt_count == 343
    assert snapshot.remaining_http_attempt_count == 0

    with pytest.raises(module.AttemptBudgetError, match="PREFLIGHT_V2_HTTP_ATTEMPT_CAP_EXCEEDED"):
        ledger.reserve_attempt("beyond-cap")


def test_attempt_ledger_refuses_the_fourth_attempt_for_one_logical_operation() -> None:
    module = _module()
    ledger = module.AttemptLedger()

    first = ledger.reserve_attempt("retrying-operation")
    second = ledger.reserve_attempt("retrying-operation")
    third = ledger.reserve_attempt("retrying-operation")

    assert [first.attempt_number, second.attempt_number, third.attempt_number] == [1, 2, 3]
    with pytest.raises(
        module.AttemptBudgetError,
        match="PREFLIGHT_V2_PER_OPERATION_ATTEMPT_CAP_EXCEEDED",
    ):
        ledger.reserve_attempt("retrying-operation")


def test_current_inputs_hard_block_network_without_recording_an_attempt() -> None:
    module = _module()
    gate = _operation_plan().network_gate

    assert gate.status is module.NetworkGateStatus.NETWORK_BLOCKED
    assert gate.attempts_sent == 0
    assert gate.execution_permitted is False
    assert gate.evidence_statuses == (
        module.ContractEvidenceStatus.FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM,
        module.ContractEvidenceStatus.UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED,
        module.ContractEvidenceStatus.MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION,
        module.ContractEvidenceStatus.MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED,
    )


def test_v2_source_emits_no_transport_urls_secrets_or_personal_paths() -> None:
    content = MODULE_PATH.read_text(encoding="utf-8")

    assert re.search(r"(?:[A-Za-z]:\\Users\\|/Users/)", content) is None
    assert "https://" not in content
    assert "http://" not in content
    assert "/v3/" not in content
    assert "FMP_API_KEY" not in content
    assert "UNUSUALWHALES_API_KEY" not in content
    assert "MASSIVE_API_KEY" not in content
