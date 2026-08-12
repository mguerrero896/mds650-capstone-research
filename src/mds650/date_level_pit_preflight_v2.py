"""Fail-closed, target-free date-level PIT preflight v2 planning primitives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from threading import Lock
from typing import Final, Protocol, cast

from mds650.date_level_pit_preflight_v1 import PreflightError, derive_forecast_origin

EXPECTED_PROVIDERS: Final[frozenset[str]] = frozenset({"fmp", "unusual_whales", "massive"})
EXPECTED_ASSET_COUNT: Final[int] = 8
EXPECTED_SESSION_COUNT: Final[int] = 7
MAX_CONTRACT_SEARCH_PAGES: Final[int] = 3
LOGICAL_REQUEST_CAP: Final[int] = 343
MAX_ATTEMPTS_PER_LOGICAL_REQUEST: Final[int] = 3
GLOBAL_HTTP_ATTEMPT_CAP: Final[int] = LOGICAL_REQUEST_CAP
MIN_NINETEEN_DIGIT_NS: Final[int] = 1_000_000_000_000_000_000
MAX_NINETEEN_DIGIT_NS: Final[int] = 9_999_999_999_999_999_999
ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PLAN_SCHEMA_PATH: Final[Path] = (
    ROOT / "specs/001-pit-options-rv30/contracts/date-level-pit-preflight-plan-v1.schema.json"
)
CATALOG_SCHEMA_PATH: Final[Path] = (
    ROOT / "specs/001-pit-options-rv30/contracts/"
    "date-level-pit-preflight-endpoint-catalog-v2.schema.json"
)
BUDGET_SCHEMA_PATH: Final[Path] = (
    ROOT / "config/date_level_pit_preflight_request_budget_v2.schema.json"
)


class PitPreflightV2Error(RuntimeError):
    """Fail-closed error for an invalid v2 planning or evidence contract."""


class AttemptBudgetError(PitPreflightV2Error):
    """Fail-closed error raised before a retry budget can be exceeded."""


class _SchemaValidator(Protocol):
    def iter_errors(self, instance: object) -> Iterable[object]: ...


class _SchemaValidatorFactory(Protocol):
    def __call__(
        self,
        schema: Mapping[str, object],
        *,
        format_checker: object,
    ) -> _SchemaValidator: ...

    def check_schema(self, schema: Mapping[str, object]) -> None: ...


class Provider(StrEnum):
    """Provider identities retained without transport targets or credentials."""

    FMP = "fmp"
    UNUSUAL_WHALES = "unusual_whales"
    MASSIVE = "massive"


class OperationKind(StrEnum):
    """Bounded logical stages; none is a transport request by itself."""

    MINUTE_BARS = "minute_bars"
    FULL_TAPE_ZIP_DOWNLOAD = "full_tape_zip_download"
    CONTRACT_SEARCH = "contract_search"
    CONTRACT_REFERENCE = "contract_reference"
    QUOTE_AS_OF = "quote_as_of"


class OperationDisposition(StrEnum):
    """Evidence-constrained state for an operation, never a success claim."""

    DATE_BOUNDED_ONLY_NO_PIT_CLAIM = "DATE_BOUNDED_ONLY_NO_PIT_CLAIM"
    DOCUMENTED_ROUTE_EXECUTION_GATED = "DOCUMENTED_ROUTE_EXECUTION_GATED"
    CONTRACT_UNRESOLVED_NO_EXECUTION = "CONTRACT_UNRESOLVED_NO_EXECUTION"
    LOCAL_CONTRACT_PENDING_OFFICIAL_MACHINE_READABLE_CONFIRMATION = (
        "LOCAL_CONTRACT_PENDING_OFFICIAL_MACHINE_READABLE_CONFIRMATION"
    )
    FAIL_CLOSED = "FAIL_CLOSED"


class FailureClassification(StrEnum):
    """Every externally observed error class fails closed rather than completing."""

    NON_2XX = "NON_2XX"
    ENTITLEMENT_ERROR = "ENTITLEMENT_ERROR"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    PAGINATION_ERROR = "PAGINATION_ERROR"
    CONTRACT_SELECTION_UNRESOLVED = "CONTRACT_SELECTION_UNRESOLVED"


class MassiveStage(StrEnum):
    """Allowed Massive order: search, reference, quote, then terminal."""

    CONTRACT_SEARCH = "contract_search"
    CONTRACT_REFERENCE = "contract_reference"
    QUOTE_AS_OF = "quote_as_of"
    TERMINAL = "terminal"


class NetworkGateStatus(StrEnum):
    """Current v2 has an explicit non-executable network gate."""

    NETWORK_BLOCKED = "NETWORK_BLOCKED"


class HistoricalAvailabilityStatus(StrEnum):
    """Availability status deliberately separate from point-in-time semantics."""

    PASS_SEPARATE_FROM_PIT = "PASS_SEPARATE_FROM_PIT_TIMESTAMP_SEMANTICS"


class ProviderHistoricalAvailability(StrEnum):
    """Evidence-bound historical availability findings for the two source providers."""

    FMP_PASS_90_OF_90_SESSIONS = "PASS_90_OF_90_SESSIONS"
    UW_PASS_90_OF_90_FILE_METADATA = "PASS_90_OF_90_FILE_METADATA"


class ContractEvidenceStatus(StrEnum):
    """Current evidence constraints that prohibit any provider transport."""

    FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM = "FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM"
    UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED = (
        "UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED"
    )
    MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION = (
        "MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION"
    )
    MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED = (
        "MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED"
    )


class ApprovalStatus(StrEnum):
    """Approval comparison result after source validation has completed."""

    MISSING = "MISSING"
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True, slots=True)
class SourceSchemas:
    """The immutable plan v1 plus documented endpoint and budget v2 schemas."""

    plan: Mapping[str, object]
    catalog: Mapping[str, object]
    budget: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Content identities rederived from the three immutable source mappings."""

    plan_sha256: str
    catalog_sha256: str
    budget_sha256: str
    composite_sha256: str


@dataclass(frozen=True, slots=True)
class QuoteAsOfParameters:
    """Fixed local quote-as-of parameter contract without an endpoint string."""

    origin_ns: int

    def __post_init__(self) -> None:
        _validate_origin_ns(self.origin_ns)

    def as_mapping(self) -> dict[str, int | str]:
        """Return the complete bounded parameter set for a future adapter."""
        return {
            "timestamp.lte": self.origin_ns,
            "sort": "timestamp",
            "order": "desc",
            "limit": 1,
        }


@dataclass(frozen=True, slots=True)
class PreflightOperation:
    """Typed logical operation with no URL, secret, or execution capability."""

    operation_id: str
    provider: Provider
    kind: OperationKind
    session_date: str
    asset: str | None
    origin_ns: int | None
    page: int | None
    shared_across_assets: bool
    disposition: OperationDisposition
    execution_permitted: bool
    contract_candidate: str | None = None
    quote_parameters: QuoteAsOfParameters | None = None

    def __post_init__(self) -> None:
        if not self.operation_id or not self.session_date or self.execution_permitted:
            raise PitPreflightV2Error("PREFLIGHT_V2_OPERATION_INVALID")
        if self.kind is OperationKind.MINUTE_BARS:
            if self.provider is not Provider.FMP or not self.asset or self.shared_across_assets:
                raise PitPreflightV2Error("PREFLIGHT_V2_OPERATION_INVALID")
        elif self.kind is OperationKind.FULL_TAPE_ZIP_DOWNLOAD:
            if (
                self.provider is not Provider.UNUSUAL_WHALES
                or self.asset is not None
                or not self.shared_across_assets
            ):
                raise PitPreflightV2Error("PREFLIGHT_V2_OPERATION_INVALID")
        elif self.kind is OperationKind.CONTRACT_SEARCH:
            if (
                self.provider is not Provider.MASSIVE
                or not self.asset
                or self.page is None
                or not 1 <= self.page <= MAX_CONTRACT_SEARCH_PAGES
            ):
                raise PitPreflightV2Error("PREFLIGHT_V2_OPERATION_INVALID")
            _validate_origin_ns(self.origin_ns)
        elif self.kind is OperationKind.CONTRACT_REFERENCE:
            if (
                self.provider is not Provider.MASSIVE
                or not self.asset
                or not self.contract_candidate
            ):
                raise PitPreflightV2Error("PREFLIGHT_V2_OPERATION_INVALID")
            _validate_origin_ns(self.origin_ns)
        elif self.kind is OperationKind.QUOTE_AS_OF:
            if (
                self.provider is not Provider.MASSIVE
                or not self.asset
                or not self.contract_candidate
                or self.quote_parameters is None
                or self.quote_parameters.origin_ns != self.origin_ns
            ):
                raise PitPreflightV2Error("PREFLIGHT_V2_OPERATION_INVALID")
            _validate_origin_ns(self.origin_ns)


@dataclass(frozen=True, slots=True)
class NetworkGate:
    """Hard current gate: no provider transport and no attempts sent."""

    status: NetworkGateStatus
    execution_permitted: bool
    attempts_sent: int
    evidence_statuses: tuple[ContractEvidenceStatus, ...]


@dataclass(frozen=True, slots=True)
class HistoricalSourceAvailability:
    """Immutable availability findings that cannot upgrade the PIT execution gate.

    Notes
    -----
    The two hashes identify the evidence bound in the official-docs audit. They
    establish only observed historical source availability and intentionally do
    not claim FMP bar-label semantics, Unusual Whales row-level availability,
    provider publication, or customer receipt timing.
    """

    status: HistoricalAvailabilityStatus
    fmp_status: ProviderHistoricalAvailability
    unusual_whales_status: ProviderHistoricalAvailability
    fmp_evidence_sha256: str
    unusual_whales_evidence_sha256: str

    def __post_init__(self) -> None:
        """Reject a status combination that could silently upgrade PIT evidence.

        Raises
        ------
        PitPreflightV2Error
            If a provider availability status or evidence hash does not match
            the registered target-blind evidence boundary.
        """
        if (
            self.status is not HistoricalAvailabilityStatus.PASS_SEPARATE_FROM_PIT
            or self.fmp_status is not ProviderHistoricalAvailability.FMP_PASS_90_OF_90_SESSIONS
            or self.unusual_whales_status
            is not ProviderHistoricalAvailability.UW_PASS_90_OF_90_FILE_METADATA
            or self.fmp_evidence_sha256
            != "97c3b57707a953629ff57e485cde918e52ecdd1777a246e84072b5c4150771dc"
            or self.unusual_whales_evidence_sha256
            != "244690e15054f518e5d12083e6b81d2bcbfcd8f5f009304f4127cbb5c1c4a3f3"
        ):
            raise PitPreflightV2Error("PREFLIGHT_V2_HISTORICAL_AVAILABILITY_INVALID")


@dataclass(frozen=True, slots=True)
class OperationPlan:
    """Deterministic initial plan with a hard no-network gate."""

    source_fingerprint: SourceFingerprint
    initial_operations: tuple[PreflightOperation, ...]
    logical_request_cap: int
    max_attempts_per_logical_request: int
    http_attempt_cap: int
    contract_selection_rule_id: str | None
    historical_availability: HistoricalSourceAvailability
    network_gate: NetworkGate


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    """Sanitized classification inputs from a future transport adapter."""

    http_status: int
    entitlement_error: bool
    schema_valid: bool
    pagination_valid: bool

    def __post_init__(self) -> None:
        if (
            isinstance(self.http_status, bool)
            or not isinstance(self.http_status, int)
            or not 100 <= self.http_status <= 599
            or not isinstance(self.entitlement_error, bool)
            or not isinstance(self.schema_valid, bool)
            or not isinstance(self.pagination_valid, bool)
        ):
            raise PitPreflightV2Error("PREFLIGHT_V2_PROVIDER_OBSERVATION_INVALID")


@dataclass(frozen=True, slots=True)
class OperationAssessment:
    """Outcome classification which intentionally has no completed state."""

    disposition: OperationDisposition
    failure: FailureClassification | None


@dataclass(frozen=True, slots=True)
class ContractResolution:
    """Typed candidate selected only by a registered machine-readable rule."""

    rule_id: str
    contract_candidate: str

    def __post_init__(self) -> None:
        if not self.rule_id or not self.contract_candidate:
            raise PitPreflightV2Error("PREFLIGHT_V2_CONTRACT_RESOLUTION_INVALID")


@dataclass(frozen=True, slots=True)
class MassiveAssetSessionState:
    """Bounded state for one Massive asset-session, without transport state."""

    asset: str
    session_date: str
    origin_ns: int
    stage: MassiveStage
    current_page: int
    contract_candidate: str | None
    contract_candidate_count: int
    contract_reference_count: int
    quote_count: int
    reference_validated: bool
    disposition: OperationDisposition
    failure: FailureClassification | None

    def __post_init__(self) -> None:
        _validate_origin_ns(self.origin_ns)
        if (
            not self.asset
            or not self.session_date
            or not 1 <= self.current_page <= MAX_CONTRACT_SEARCH_PAGES
            or not 0 <= self.contract_candidate_count <= 1
            or not 0 <= self.contract_reference_count <= 1
            or not 0 <= self.quote_count <= 1
        ):
            raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_STATE_INVALID")
        if self.contract_candidate_count == 0 and self.contract_candidate is not None:
            raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_STATE_INVALID")
        if self.contract_candidate_count == 1 and not self.contract_candidate:
            raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_STATE_INVALID")
        if self.contract_reference_count > self.contract_candidate_count:
            raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_STATE_INVALID")
        if self.quote_count > self.contract_reference_count:
            raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_STATE_INVALID")
        if self.reference_validated != (self.contract_reference_count == 1):
            raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_STATE_INVALID")


@dataclass(frozen=True, slots=True)
class MassiveTransition:
    """A state transition that may expose one next logical operation."""

    state: MassiveAssetSessionState
    next_operation: PreflightOperation | None
    failure: FailureClassification | None


@dataclass(frozen=True, slots=True)
class AttemptReservation:
    """Atomic admission record for exactly one logical HTTP attempt."""

    operation_id: str
    attempt_number: int
    global_attempt_number: int


@dataclass(frozen=True, slots=True)
class AttemptLedgerSnapshot:
    """Read-only ledger state for audit and retry planning."""

    reserved_logical_request_count: int
    reserved_http_attempt_count: int
    remaining_http_attempt_count: int


class AttemptLedger:
    """Thread-safe in-memory cap; every retry spends one of 343 total attempts."""

    def __init__(
        self,
        *,
        http_attempt_cap: int = GLOBAL_HTTP_ATTEMPT_CAP,
        max_attempts_per_logical_request: int = MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
    ) -> None:
        if (
            isinstance(http_attempt_cap, bool)
            or not isinstance(http_attempt_cap, int)
            or http_attempt_cap < 1
            or isinstance(max_attempts_per_logical_request, bool)
            or not isinstance(max_attempts_per_logical_request, int)
            or max_attempts_per_logical_request < 1
        ):
            raise AttemptBudgetError("PREFLIGHT_V2_ATTEMPT_LEDGER_CONFIGURATION_INVALID")
        self._http_attempt_cap = http_attempt_cap
        self._max_attempts_per_logical_request = max_attempts_per_logical_request
        self._attempt_count_by_operation: dict[str, int] = {}
        self._reserved_http_attempt_count = 0
        self._lock = Lock()

    def reserve_attempt(self, operation_id: str) -> AttemptReservation:
        """Atomically admit one first attempt or retry before it can be sent."""
        if not isinstance(operation_id, str) or not operation_id:
            raise AttemptBudgetError("PREFLIGHT_V2_OPERATION_ID_INVALID")
        with self._lock:
            prior_attempts = self._attempt_count_by_operation.get(operation_id, 0)
            if prior_attempts >= self._max_attempts_per_logical_request:
                raise AttemptBudgetError("PREFLIGHT_V2_PER_OPERATION_ATTEMPT_CAP_EXCEEDED")
            if self._reserved_http_attempt_count >= self._http_attempt_cap:
                raise AttemptBudgetError("PREFLIGHT_V2_HTTP_ATTEMPT_CAP_EXCEEDED")
            attempt_number = prior_attempts + 1
            global_attempt_number = self._reserved_http_attempt_count + 1
            self._attempt_count_by_operation[operation_id] = attempt_number
            self._reserved_http_attempt_count = global_attempt_number
            return AttemptReservation(
                operation_id=operation_id,
                attempt_number=attempt_number,
                global_attempt_number=global_attempt_number,
            )

    def snapshot(self) -> AttemptLedgerSnapshot:
        """Return a coherent ledger snapshot without exposing mutable internals."""
        with self._lock:
            return AttemptLedgerSnapshot(
                reserved_logical_request_count=len(self._attempt_count_by_operation),
                reserved_http_attempt_count=self._reserved_http_attempt_count,
                remaining_http_attempt_count=(
                    self._http_attempt_cap - self._reserved_http_attempt_count
                ),
            )


def canonical_json(value: object) -> bytes:
    """Serialize source content deterministically without filesystem paths or data."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def load_source_schemas() -> SourceSchemas:
    """Load only the already-versioned v1 source schemas."""
    return SourceSchemas(
        plan=_load_schema(PLAN_SCHEMA_PATH),
        catalog=_load_schema(CATALOG_SCHEMA_PATH),
        budget=_load_schema(BUDGET_SCHEMA_PATH),
    )


def build_source_fingerprint(
    immutable_plan: Mapping[str, object],
    endpoint_catalog: Mapping[str, object],
    request_budget: Mapping[str, object],
) -> SourceFingerprint:
    """Validate schemas and source hashes before composing their shared identity."""
    schemas = load_source_schemas()
    _validate_source_schema(immutable_plan, schemas.plan, "PREFLIGHT_V2_PLAN_SCHEMA_INVALID")
    _validate_source_schema(
        endpoint_catalog,
        schemas.catalog,
        "PREFLIGHT_V2_CATALOG_SCHEMA_INVALID",
    )
    _validate_source_schema(request_budget, schemas.budget, "PREFLIGHT_V2_BUDGET_SCHEMA_INVALID")
    plan_sha256 = _validated_self_hash(
        immutable_plan,
        artifact_type="date_level_pit_preflight_plan_v1",
        error_code="PREFLIGHT_V2_PLAN_HASH_INVALID",
    )
    budget_sha256 = _validated_self_hash(
        request_budget,
        artifact_type="date_level_pit_preflight_request_budget_v2",
        error_code="PREFLIGHT_V2_BUDGET_HASH_INVALID",
    )
    catalog_sha256 = _sha256(endpoint_catalog)
    composite_sha256 = _sha256(
        {
            "budget_sha256": budget_sha256,
            "catalog_sha256": catalog_sha256,
            "plan_sha256": plan_sha256,
        }
    )
    return SourceFingerprint(
        plan_sha256=plan_sha256,
        catalog_sha256=catalog_sha256,
        budget_sha256=budget_sha256,
        composite_sha256=composite_sha256,
    )


def validate_source_fingerprint(
    fingerprint: SourceFingerprint,
    immutable_plan: Mapping[str, object],
    endpoint_catalog: Mapping[str, object],
    request_budget: Mapping[str, object],
) -> None:
    """Revalidate schemas and hashes before accepting an existing composite ID."""
    expected = build_source_fingerprint(
        immutable_plan,
        endpoint_catalog,
        request_budget,
    )
    if fingerprint != expected:
        raise PitPreflightV2Error("PREFLIGHT_V2_SOURCE_FINGERPRINT_MISMATCH")


def match_approved_composite_fingerprint(
    approved_composite_sha256: str | None,
    immutable_plan: Mapping[str, object],
    endpoint_catalog: Mapping[str, object],
    request_budget: Mapping[str, object],
) -> ApprovalStatus:
    """Compare approval only after full schema and source-fingerprint validation."""
    fingerprint = build_source_fingerprint(
        immutable_plan,
        endpoint_catalog,
        request_budget,
    )
    if approved_composite_sha256 is None:
        return ApprovalStatus.MISSING
    return (
        ApprovalStatus.MATCH
        if approved_composite_sha256 == fingerprint.composite_sha256
        else ApprovalStatus.MISMATCH
    )


def build_operation_plan(
    immutable_plan: Mapping[str, object],
    endpoint_catalog: Mapping[str, object],
    request_budget: Mapping[str, object],
) -> OperationPlan:
    """Build a deterministic, target-free and non-executable initial operation plan."""
    fingerprint = build_source_fingerprint(
        immutable_plan,
        endpoint_catalog,
        request_budget,
    )
    assets, sessions = _plan_dimensions(immutable_plan)
    _validate_catalog_semantics(endpoint_catalog)
    _validate_budget_semantics(
        request_budget,
        asset_count=len(assets),
        session_count=len(sessions),
    )
    operations: list[PreflightOperation] = []
    for session_date, _ in sessions:
        for asset in assets:
            operations.append(
                _operation(
                    provider=Provider.FMP,
                    kind=OperationKind.MINUTE_BARS,
                    session_date=session_date,
                    asset=asset,
                    origin_ns=None,
                    page=None,
                    shared_across_assets=False,
                    disposition=OperationDisposition.DATE_BOUNDED_ONLY_NO_PIT_CLAIM,
                )
            )
    for session_date, _ in sessions:
        operations.append(
            _operation(
                provider=Provider.UNUSUAL_WHALES,
                kind=OperationKind.FULL_TAPE_ZIP_DOWNLOAD,
                session_date=session_date,
                asset=None,
                origin_ns=None,
                page=None,
                shared_across_assets=True,
                disposition=OperationDisposition.DOCUMENTED_ROUTE_EXECUTION_GATED,
            )
        )
    for session_date, origin_ns in sessions:
        for asset in assets:
            operations.append(
                _operation(
                    provider=Provider.MASSIVE,
                    kind=OperationKind.CONTRACT_SEARCH,
                    session_date=session_date,
                    asset=asset,
                    origin_ns=origin_ns,
                    page=1,
                    shared_across_assets=False,
                    disposition=OperationDisposition.CONTRACT_UNRESOLVED_NO_EXECUTION,
                )
            )
    if len(operations) != 119:
        raise PitPreflightV2Error("PREFLIGHT_V2_INITIAL_OPERATION_COUNT_INVALID")
    return OperationPlan(
        source_fingerprint=fingerprint,
        initial_operations=tuple(operations),
        logical_request_cap=LOGICAL_REQUEST_CAP,
        max_attempts_per_logical_request=MAX_ATTEMPTS_PER_LOGICAL_REQUEST,
        http_attempt_cap=GLOBAL_HTTP_ATTEMPT_CAP,
        contract_selection_rule_id=None,
        historical_availability=current_historical_source_availability(),
        network_gate=current_network_gate(),
    )


def current_historical_source_availability() -> HistoricalSourceAvailability:
    """Return registered availability evidence without upgrading PIT semantics.

    Returns
    -------
    HistoricalSourceAvailability
        The two verified 90-session historical availability findings bound to
        the evidence hashes recorded in the official-docs audit.

    Notes
    -----
    This function is intentionally static and target-blind. A positive return
    cannot authorize network transport, reconcile existing results, or assert
    timestamp, publication, or receipt semantics.
    """
    return HistoricalSourceAvailability(
        status=HistoricalAvailabilityStatus.PASS_SEPARATE_FROM_PIT,
        fmp_status=ProviderHistoricalAvailability.FMP_PASS_90_OF_90_SESSIONS,
        unusual_whales_status=(ProviderHistoricalAvailability.UW_PASS_90_OF_90_FILE_METADATA),
        fmp_evidence_sha256=("97c3b57707a953629ff57e485cde918e52ecdd1777a246e84072b5c4150771dc"),
        unusual_whales_evidence_sha256=(
            "244690e15054f518e5d12083e6b81d2bcbfcd8f5f009304f4127cbb5c1c4a3f3"
        ),
    )


def current_network_gate() -> NetworkGate:
    """Return current evidence states that keep transport disabled."""
    return NetworkGate(
        status=NetworkGateStatus.NETWORK_BLOCKED,
        execution_permitted=False,
        attempts_sent=0,
        evidence_statuses=(
            ContractEvidenceStatus.FMP_DATE_BOUNDED_ONLY_NO_PIT_CLAIM,
            ContractEvidenceStatus.UW_FULL_TAPE_ZIP_ROUTE_DOCUMENTED_EXECUTION_GATED,
            ContractEvidenceStatus.MASSIVE_CONTRACT_SELECTION_RULE_UNRESOLVED_NO_EXECUTION,
            ContractEvidenceStatus.MASSIVE_QUOTE_AS_OF_PARAMETERS_DOCUMENTED_LOCAL_SIP_CHECK_REQUIRED,
        ),
    )


def initial_massive_asset_session_state(
    operation: PreflightOperation,
) -> MassiveAssetSessionState:
    """Initialize one bounded Massive search state from an initial search operation."""
    if (
        operation.kind is not OperationKind.CONTRACT_SEARCH
        or operation.provider is not Provider.MASSIVE
        or operation.asset is None
        or operation.origin_ns is None
        or operation.page != 1
    ):
        raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_INITIAL_OPERATION_REQUIRED")
    return MassiveAssetSessionState(
        asset=operation.asset,
        session_date=operation.session_date,
        origin_ns=operation.origin_ns,
        stage=MassiveStage.CONTRACT_SEARCH,
        current_page=1,
        contract_candidate=None,
        contract_candidate_count=0,
        contract_reference_count=0,
        quote_count=0,
        reference_validated=False,
        disposition=OperationDisposition.CONTRACT_UNRESOLVED_NO_EXECUTION,
        failure=None,
    )


def advance_massive_contract_search_page(
    state: MassiveAssetSessionState,
    *,
    requires_next_page: bool,
) -> MassiveTransition:
    """Advance no farther than page three; a requested fourth page fails closed."""
    if state.stage is not MassiveStage.CONTRACT_SEARCH or not isinstance(requires_next_page, bool):
        raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_SEARCH_TRANSITION_INVALID")
    if not requires_next_page:
        return MassiveTransition(state=state, next_operation=None, failure=None)
    if state.current_page >= MAX_CONTRACT_SEARCH_PAGES:
        failed = replace(
            state,
            stage=MassiveStage.TERMINAL,
            disposition=OperationDisposition.FAIL_CLOSED,
            failure=FailureClassification.PAGINATION_ERROR,
        )
        return MassiveTransition(
            state=failed,
            next_operation=None,
            failure=FailureClassification.PAGINATION_ERROR,
        )
    next_page = state.current_page + 1
    advanced = replace(state, current_page=next_page)
    operation = _operation(
        provider=Provider.MASSIVE,
        kind=OperationKind.CONTRACT_SEARCH,
        session_date=state.session_date,
        asset=state.asset,
        origin_ns=state.origin_ns,
        page=next_page,
        shared_across_assets=False,
        disposition=OperationDisposition.CONTRACT_UNRESOLVED_NO_EXECUTION,
    )
    return MassiveTransition(state=advanced, next_operation=operation, failure=None)


def resolve_massive_contract_candidate(
    operation_plan: OperationPlan,
    state: MassiveAssetSessionState,
    resolution: ContractResolution,
) -> MassiveTransition:
    """Fail closed because current immutable inputs register no selection rule."""
    if state.stage is not MassiveStage.CONTRACT_SEARCH:
        raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_RESOLUTION_TRANSITION_INVALID")
    if operation_plan.contract_selection_rule_id != resolution.rule_id:
        unresolved = replace(
            state,
            stage=MassiveStage.TERMINAL,
            disposition=OperationDisposition.CONTRACT_UNRESOLVED_NO_EXECUTION,
            failure=FailureClassification.CONTRACT_SELECTION_UNRESOLVED,
        )
        return MassiveTransition(
            state=unresolved,
            next_operation=None,
            failure=FailureClassification.CONTRACT_SELECTION_UNRESOLVED,
        )
    if state.contract_candidate_count != 0:
        raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_CANDIDATE_COUNT_EXCEEDED")
    resolved = replace(
        state,
        stage=MassiveStage.CONTRACT_REFERENCE,
        contract_candidate=resolution.contract_candidate,
        contract_candidate_count=1,
        disposition=(
            OperationDisposition.LOCAL_CONTRACT_PENDING_OFFICIAL_MACHINE_READABLE_CONFIRMATION
        ),
    )
    operation = _operation(
        provider=Provider.MASSIVE,
        kind=OperationKind.CONTRACT_REFERENCE,
        session_date=resolved.session_date,
        asset=resolved.asset,
        origin_ns=resolved.origin_ns,
        page=None,
        shared_across_assets=False,
        disposition=(
            OperationDisposition.LOCAL_CONTRACT_PENDING_OFFICIAL_MACHINE_READABLE_CONFIRMATION
        ),
        contract_candidate=resolution.contract_candidate,
    )
    return MassiveTransition(state=resolved, next_operation=operation, failure=None)


def validate_massive_contract_reference(
    state: MassiveAssetSessionState,
    observation: ProviderObservation,
) -> MassiveTransition:
    """Create at most one non-executable quote stage after a valid reference."""
    if (
        state.stage is not MassiveStage.CONTRACT_REFERENCE
        or state.contract_candidate_count != 1
        or state.contract_reference_count != 0
        or state.quote_count != 0
        or state.contract_candidate is None
    ):
        raise PitPreflightV2Error("PREFLIGHT_V2_MASSIVE_REFERENCE_TRANSITION_INVALID")
    failure = _classify_provider_observation(observation)
    if failure is not None:
        failed = replace(
            state,
            stage=MassiveStage.TERMINAL,
            disposition=OperationDisposition.FAIL_CLOSED,
            failure=failure,
        )
        return MassiveTransition(state=failed, next_operation=None, failure=failure)
    quote_parameters = QuoteAsOfParameters(origin_ns=state.origin_ns)
    quoted = replace(
        state,
        stage=MassiveStage.QUOTE_AS_OF,
        contract_reference_count=1,
        quote_count=1,
        reference_validated=True,
        disposition=(
            OperationDisposition.LOCAL_CONTRACT_PENDING_OFFICIAL_MACHINE_READABLE_CONFIRMATION
        ),
        failure=None,
    )
    operation = _operation(
        provider=Provider.MASSIVE,
        kind=OperationKind.QUOTE_AS_OF,
        session_date=quoted.session_date,
        asset=quoted.asset,
        origin_ns=quoted.origin_ns,
        page=None,
        shared_across_assets=False,
        disposition=(
            OperationDisposition.LOCAL_CONTRACT_PENDING_OFFICIAL_MACHINE_READABLE_CONFIRMATION
        ),
        contract_candidate=quoted.contract_candidate,
        quote_parameters=quote_parameters,
    )
    return MassiveTransition(state=quoted, next_operation=operation, failure=None)


def evaluate_provider_observation(
    operation: PreflightOperation,
    observation: ProviderObservation,
) -> OperationAssessment:
    """Classify every transport failure as fail-closed without a completion state."""
    failure = _classify_provider_observation(observation)
    if failure is not None:
        return OperationAssessment(
            disposition=OperationDisposition.FAIL_CLOSED,
            failure=failure,
        )
    return OperationAssessment(disposition=operation.disposition, failure=None)


def _operation(
    *,
    provider: Provider,
    kind: OperationKind,
    session_date: str,
    asset: str | None,
    origin_ns: int | None,
    page: int | None,
    shared_across_assets: bool,
    disposition: OperationDisposition,
    contract_candidate: str | None = None,
    quote_parameters: QuoteAsOfParameters | None = None,
) -> PreflightOperation:
    return PreflightOperation(
        operation_id=_operation_id(provider, kind, session_date, asset, page),
        provider=provider,
        kind=kind,
        session_date=session_date,
        asset=asset,
        origin_ns=origin_ns,
        page=page,
        shared_across_assets=shared_across_assets,
        disposition=disposition,
        execution_permitted=False,
        contract_candidate=contract_candidate,
        quote_parameters=quote_parameters,
    )


def _operation_id(
    provider: Provider,
    kind: OperationKind,
    session_date: str,
    asset: str | None,
    page: int | None,
) -> str:
    asset_component = asset if asset is not None else "shared"
    page_component = str(page) if page is not None else "none"
    return ":".join((provider.value, kind.value, session_date, asset_component, page_component))


def _plan_dimensions(
    immutable_plan: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...]]:
    raw_assets = immutable_plan.get("assets")
    raw_sessions = immutable_plan.get("sentinel_sessions")
    if not isinstance(raw_assets, list) or not isinstance(raw_sessions, list):
        raise PitPreflightV2Error("PREFLIGHT_V2_PLAN_DIMENSIONS_INVALID")
    assets = tuple(raw_assets)
    if (
        len(assets) != EXPECTED_ASSET_COUNT
        or len(set(assets)) != EXPECTED_ASSET_COUNT
        or not all(isinstance(asset, str) and asset for asset in assets)
    ):
        raise PitPreflightV2Error("PREFLIGHT_V2_PLAN_DIMENSIONS_INVALID")
    sessions: list[tuple[str, int]] = []
    for raw_session in raw_sessions:
        if not isinstance(raw_session, Mapping):
            raise PitPreflightV2Error("PREFLIGHT_V2_PLAN_DIMENSIONS_INVALID")
        session_date = raw_session.get("date")
        calendar_metadata = raw_session.get("calendar_metadata")
        if not isinstance(session_date, str) or not isinstance(calendar_metadata, Mapping):
            raise PitPreflightV2Error("PREFLIGHT_V2_PLAN_DIMENSIONS_INVALID")
        try:
            origin_ns = derive_forecast_origin(calendar_metadata).forecast_origin_ns
        except PreflightError as exc:
            raise PitPreflightV2Error("PREFLIGHT_V2_PLAN_DIMENSIONS_INVALID") from exc
        _validate_origin_ns(origin_ns)
        sessions.append((session_date, origin_ns))
    if len(sessions) != EXPECTED_SESSION_COUNT or len({date for date, _ in sessions}) != 7:
        raise PitPreflightV2Error("PREFLIGHT_V2_PLAN_DIMENSIONS_INVALID")
    return cast(tuple[str, ...], assets), tuple(sessions)


def _validate_catalog_semantics(endpoint_catalog: Mapping[str, object]) -> None:
    raw_endpoints = endpoint_catalog.get("endpoints")
    if not isinstance(raw_endpoints, list):
        raise PitPreflightV2Error("PREFLIGHT_V2_CATALOG_INVALID")
    descriptors: dict[str, Mapping[str, object]] = {}
    for descriptor in raw_endpoints:
        if not isinstance(descriptor, Mapping):
            raise PitPreflightV2Error("PREFLIGHT_V2_CATALOG_INVALID")
        provider = descriptor.get("provider")
        if not isinstance(provider, str) or provider in descriptors:
            raise PitPreflightV2Error("PREFLIGHT_V2_CATALOG_INVALID")
        descriptors[provider] = descriptor
    if set(descriptors) != EXPECTED_PROVIDERS:
        raise PitPreflightV2Error("PREFLIGHT_V2_CATALOG_INVALID")
    if not _is_fmp_catalog_descriptor(descriptors[Provider.FMP.value]):
        raise PitPreflightV2Error("PREFLIGHT_V2_CATALOG_INVALID")
    if not _is_uw_catalog_descriptor(descriptors[Provider.UNUSUAL_WHALES.value]):
        raise PitPreflightV2Error("PREFLIGHT_V2_CATALOG_INVALID")
    if not _is_massive_catalog_descriptor(descriptors[Provider.MASSIVE.value]):
        raise PitPreflightV2Error("PREFLIGHT_V2_CATALOG_INVALID")


def _is_fmp_catalog_descriptor(descriptor: Mapping[str, object]) -> bool:
    parameters = descriptor.get("request_parameters")
    return (
        descriptor.get("endpoint_id") == "fmp-underlying-1min-date-bounded"
        and descriptor.get("method") == "GET"
        and descriptor.get("metadata_only") is False
        and isinstance(parameters, Mapping)
        and parameters.get("symbol") == "{asset}"
        and parameters.get("from") == "{session_date}"
        and parameters.get("to") == "{session_date}"
        and parameters.get("extended") is False
        and parameters.get("nonadjusted") is False
    )


def _is_uw_catalog_descriptor(descriptor: Mapping[str, object]) -> bool:
    return (
        descriptor.get("endpoint_id") == "uw-full-tape-zip-download"
        and descriptor.get("method") == "GET"
        and descriptor.get("request_target") == "/api/option-trades/full-tape/{session_date}"
        and descriptor.get("metadata_only") is False
        and descriptor.get("expected_content_type") == "application/zip"
        and descriptor.get("range_transport_status") == "NOT_DOCUMENTED_NOT_USED"
        and "range_probe" not in descriptor
    )


def _is_massive_catalog_descriptor(descriptor: Mapping[str, object]) -> bool:
    raw_routes = descriptor.get("routes")
    if not isinstance(raw_routes, list) or len(raw_routes) != 3:
        return False
    first, second, third = raw_routes
    if (
        not isinstance(first, Mapping)
        or not isinstance(second, Mapping)
        or not isinstance(third, Mapping)
    ):
        return False
    parameters = third.get("parameters")
    return (
        descriptor.get("endpoint_id") == "massive-contract-search-reference-and-quote-asof"
        and descriptor.get("method") == "GET"
        and descriptor.get("metadata_only") is False
        and first.get("operation") == "contract_search"
        and second.get("operation") == "contract_reference"
        and third.get("operation") == "quote_as_of"
        and third.get("timestamp_unit") == "nanoseconds"
        and isinstance(parameters, Mapping)
        and parameters.get("timestamp.lte") == "{as_of_timestamp_ns}"
        and parameters.get("sort") == "timestamp"
        and parameters.get("order") == "desc"
        and parameters.get("limit") == 1
    )


def _validate_budget_semantics(
    request_budget: Mapping[str, object],
    *,
    asset_count: int,
    session_count: int,
) -> None:
    dimensions = request_budget.get("dimensions")
    counts = request_budget.get("request_budget")
    pagination = request_budget.get("massive_contract_pagination")
    if (
        not isinstance(dimensions, Mapping)
        or not isinstance(counts, Mapping)
        or not isinstance(pagination, Mapping)
    ):
        raise PitPreflightV2Error("PREFLIGHT_V2_BUDGET_INVALID")
    expected_dimensions = {
        "asset_count": asset_count,
        "session_count": session_count,
        "asset_day_count": asset_count * session_count,
    }
    expected_counts = {
        "fmp_one_minute_requests": asset_count * session_count,
        "unusual_whales_full_tape_zip_requests": session_count,
        "massive_initial_contract_search_requests": asset_count * session_count,
        "massive_initial_contract_reference_conditional_max": asset_count * session_count,
        "massive_initial_quote_as_of_conditional_max": asset_count * session_count,
        "cap_request_count": LOGICAL_REQUEST_CAP,
    }
    if any(dimensions.get(key) != value for key, value in expected_dimensions.items()):
        raise PitPreflightV2Error("PREFLIGHT_V2_BUDGET_INVALID")
    if any(counts.get(key) != value for key, value in expected_counts.items()):
        raise PitPreflightV2Error("PREFLIGHT_V2_BUDGET_INVALID")
    if (
        pagination.get("max_contract_pages_per_asset_day") != MAX_CONTRACT_SEARCH_PAGES
        or pagination.get("contract_stage_order")
        != [
            OperationKind.CONTRACT_SEARCH.value,
            OperationKind.CONTRACT_REFERENCE.value,
            OperationKind.QUOTE_AS_OF.value,
        ]
        or pagination.get("contract_reference_max_per_asset_day") != 1
        or pagination.get("quote_as_of_max_per_asset_day") != 1
    ):
        raise PitPreflightV2Error("PREFLIGHT_V2_BUDGET_INVALID")


def _classify_provider_observation(
    observation: ProviderObservation,
) -> FailureClassification | None:
    if observation.entitlement_error:
        return FailureClassification.ENTITLEMENT_ERROR
    if not 200 <= observation.http_status < 300:
        return FailureClassification.NON_2XX
    if not observation.schema_valid:
        return FailureClassification.SCHEMA_ERROR
    if not observation.pagination_valid:
        return FailureClassification.PAGINATION_ERROR
    return None


def _validate_origin_ns(origin_ns: object) -> None:
    if (
        isinstance(origin_ns, bool)
        or not isinstance(origin_ns, int)
        or not MIN_NINETEEN_DIGIT_NS <= origin_ns <= MAX_NINETEEN_DIGIT_NS
    ):
        raise PitPreflightV2Error("PREFLIGHT_V2_ORIGIN_NS_INVALID")


def _load_schema(path: Path) -> dict[str, object]:
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PitPreflightV2Error("PREFLIGHT_V2_SOURCE_SCHEMA_UNAVAILABLE") from exc
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise PitPreflightV2Error("PREFLIGHT_V2_SOURCE_SCHEMA_UNAVAILABLE")
    return cast(dict[str, object], decoded)


def _validate_source_schema(
    source: Mapping[str, object],
    schema: Mapping[str, object],
    error_code: str,
) -> None:
    validator = _schema_validator(schema)
    if any(validator.iter_errors(source)):
        raise PitPreflightV2Error(error_code)


def _schema_validator(schema: Mapping[str, object]) -> _SchemaValidator:
    try:
        module = import_module("jsonschema")
        factory = cast(_SchemaValidatorFactory, module.Draft202012Validator)
        factory.check_schema(schema)
        return factory(schema, format_checker=module.FormatChecker())
    except Exception as exc:
        raise PitPreflightV2Error("PREFLIGHT_V2_SOURCE_SCHEMA_UNAVAILABLE") from exc


def _validated_self_hash(
    source: Mapping[str, object],
    *,
    artifact_type: str,
    error_code: str,
) -> str:
    declared_hash = source.get("semantic_self_hash")
    if source.get("artifact_type") != artifact_type or not _is_sha256(declared_hash):
        raise PitPreflightV2Error(error_code)
    normalized = dict(source)
    normalized.pop("semantic_self_hash", None)
    if _sha256(normalized) != declared_hash:
        raise PitPreflightV2Error(error_code)
    return declared_hash


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        return False
    return all(character in "0123456789abcdef" for character in value.removeprefix("sha256:"))


def _sha256(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"
