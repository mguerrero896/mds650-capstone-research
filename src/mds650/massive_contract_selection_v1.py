"""Deterministic, target-blind selection of Massive historical option contracts.

The module deliberately contains no HTTP transport, cache path, credential, target, or
model logic. It turns schema-validated contract reference rows into a fixed contract grid
that a separately governed transport may resolve with as_of.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Final

RULE_ID: Final[str] = "massive-contract-grid-v1-asof-dte-moneyness-tiebreak"
DTE_BUCKETS: Final[tuple[tuple[str, int, int], ...]] = (
    ("short", 7, 21),
    ("medium", 30, 60),
    ("long", 90, 180),
)
TARGET_MONEYNESS: Final[tuple[float, ...]] = (0.95, 0.975, 1.0, 1.025, 1.05)
OPTION_TYPES: Final[tuple[str, ...]] = ("call", "put")
MAX_ABSOLUTE_MONEYNESS_DISTANCE: Final[float] = 0.04


class MassiveContractSelectionError(ValueError):
    """Raised when an input cannot support deterministic historical selection."""


@dataclass(frozen=True, slots=True)
class HistoricalOptionContract:
    """A schema-validated Massive contract candidate.

    Parameters
    ----------
    contract_id
        Massive option ticker in canonical O: form.
    underlying_ticker
        Exact underlying ticker returned by Massive.
    expiry
        Contract expiration as a calendar date.
    strike
        Positive strike price in underlying-price units.
    option_type
        Canonical call or put value.

    Raises
    ------
    MassiveContractSelectionError
        If the candidate is malformed. A caller must retain malformed-row evidence
        rather than silently converting it into a missing option state.
    """

    contract_id: str
    underlying_ticker: str
    expiry: date
    strike: float
    option_type: str

    def __post_init__(self) -> None:
        """Reject noncanonical candidate metadata at the selection boundary."""
        if (
            not isinstance(self.contract_id, str)
            or not self.contract_id.startswith("O:")
            or not isinstance(self.underlying_ticker, str)
            or not self.underlying_ticker
            or type(self.expiry) is not date
            or isinstance(self.strike, bool)
            or not isinstance(self.strike, (int, float))
            or not isfinite(float(self.strike))
            or float(self.strike) <= 0.0
            or self.option_type not in OPTION_TYPES
        ):
            raise MassiveContractSelectionError("MASSIVE_CONTRACT_CANDIDATE_INVALID")


@dataclass(frozen=True, slots=True)
class SelectedContract:
    """One deterministic option-grid slot selected before quote retrieval.

    The absence of a slot means missing for that slot; it is never a zero-valued
    option-state observation.
    """

    contract_id: str
    bucket: str
    target_moneyness: float
    option_type: str
    expiry: date
    strike: float
    dte: int
    moneyness: float


def select_contract_grid(
    candidates: Iterable[HistoricalOptionContract],
    *,
    asset: str,
    as_of: date,
    spot: float,
) -> tuple[SelectedContract, ...]:
    """Select deterministic DTE/moneyness/option-type slots from reference candidates.

    Parameters
    ----------
    candidates
        Schema-validated candidates from one Massive historical as_of response.
    asset
        Exact uppercase underlying ticker requested from Massive.
    as_of
        Historical contract-reference date, not a target or evaluation date.
    spot
        Positive, pre-origin underlying spot used only to calculate moneyness.

    Returns
    -------
    tuple[SelectedContract, ...]
        Slots ordered by DTE bucket, target moneyness, and option type. Candidates must
        be no more than 0.04 moneyness units from the target. Missing slots are omitted
        so that their caller can record an explicit missing reason.

    Raises
    ------
    MassiveContractSelectionError
        If request-level inputs are invalid or one contract identifier carries
        conflicting metadata.

    Notes
    -----
    Ties are broken by absolute moneyness distance, distance to the midpoint of the DTE
    bucket, expiration, strike, then contract identifier. The rule is target-blind and
    uses no quote, IV, RV30, QLIKE, model, or outcome value.
    """
    _validate_request(asset=asset, as_of=as_of, spot=spot)
    unique_candidates = _unique_candidates(candidates)
    selected: dict[
        tuple[str, float, str],
        tuple[tuple[float, float, str, float, str], SelectedContract],
    ] = {}

    for candidate in unique_candidates:
        if candidate.underlying_ticker != asset:
            continue
        dte = (candidate.expiry - as_of).days
        bucket = _bucket_for_dte(dte)
        if bucket is None:
            continue
        bucket_name, lower_dte, upper_dte = bucket
        moneyness = float(candidate.strike) / float(spot)
        for target_moneyness in TARGET_MONEYNESS:
            distance = abs(moneyness - target_moneyness)
            if distance > MAX_ABSOLUTE_MONEYNESS_DISTANCE:
                continue
            slot = (bucket_name, target_moneyness, candidate.option_type)
            candidate_row = SelectedContract(
                contract_id=candidate.contract_id,
                bucket=bucket_name,
                target_moneyness=target_moneyness,
                option_type=candidate.option_type,
                expiry=candidate.expiry,
                strike=float(candidate.strike),
                dte=dte,
                moneyness=moneyness,
            )
            rank = (
                distance,
                abs(dte - ((lower_dte + upper_dte) / 2.0)),
                candidate.expiry.isoformat(),
                float(candidate.strike),
                candidate.contract_id,
            )
            current = selected.get(slot)
            if current is None or rank < current[0]:
                selected[slot] = (rank, candidate_row)

    return tuple(
        selected[slot][1]
        for slot in sorted(
            selected,
            key=lambda item: (
                _bucket_order(item[0]),
                TARGET_MONEYNESS.index(item[1]),
                OPTION_TYPES.index(item[2]),
            ),
        )
    )


def _validate_request(*, asset: str, as_of: date, spot: float) -> None:
    """Reject noncanonical request inputs before any candidate can be selected."""
    if (
        not isinstance(asset, str)
        or not asset
        or asset != asset.upper()
        or type(as_of) is not date
        or isinstance(spot, bool)
        or not isinstance(spot, (int, float))
        or not isfinite(float(spot))
        or float(spot) <= 0.0
    ):
        raise MassiveContractSelectionError("MASSIVE_CONTRACT_SELECTION_INPUT_INVALID")


def _unique_candidates(
    candidates: Iterable[HistoricalOptionContract],
) -> tuple[HistoricalOptionContract, ...]:
    """Deduplicate identical candidates and fail closed on conflicting identifiers."""
    unique: dict[str, HistoricalOptionContract] = {}
    for candidate in candidates:
        if not isinstance(candidate, HistoricalOptionContract):
            raise MassiveContractSelectionError("MASSIVE_CONTRACT_CANDIDATE_INVALID")
        prior = unique.get(candidate.contract_id)
        if prior is not None and prior != candidate:
            raise MassiveContractSelectionError("MASSIVE_CONTRACT_ID_CONFLICT")
        unique[candidate.contract_id] = candidate
    return tuple(unique[contract_id] for contract_id in sorted(unique))


def _bucket_for_dte(dte: int) -> tuple[str, int, int] | None:
    """Return the unique inclusive DTE bucket for a positive day count."""
    for bucket in DTE_BUCKETS:
        _, lower_dte, upper_dte = bucket
        if lower_dte <= dte <= upper_dte:
            return bucket
    return None


def _bucket_order(bucket_name: str) -> int:
    """Return the registered ordering index for a DTE bucket."""
    for index, (name, _, _) in enumerate(DTE_BUCKETS):
        if name == bucket_name:
            return index
    raise MassiveContractSelectionError("MASSIVE_CONTRACT_BUCKET_INVALID")
