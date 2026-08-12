"""Target-blind contracts for deterministic Massive grid selection."""

from __future__ import annotations

from datetime import date

from mds650.massive_contract_selection_v1 import (
    HistoricalOptionContract,
    select_contract_grid,
)


def test_select_contract_grid_uses_expiry_distance_to_break_equal_moneyness_ties() -> None:
    """A selector that retains provider order instead of the documented tie-break must fail."""
    as_of = date(2025, 1, 2)
    candidates = (
        HistoricalOptionContract(
            contract_id="O:AAPL250202C00100000",
            underlying_ticker="AAPL",
            expiry=date(2025, 2, 2),
            strike=100.0,
            option_type="call",
        ),
        HistoricalOptionContract(
            contract_id="O:AAPL250216C00100000",
            underlying_ticker="AAPL",
            expiry=date(2025, 2, 16),
            strike=100.0,
            option_type="call",
        ),
    )

    selected = select_contract_grid(
        reversed(candidates),
        asset="AAPL",
        as_of=as_of,
        spot=100.0,
    )

    atm_medium_call = next(
        row
        for row in selected
        if row.bucket == "medium" and row.target_moneyness == 1.0 and row.option_type == "call"
    )
    assert atm_medium_call.contract_id == "O:AAPL250216C00100000"
    assert atm_medium_call.dte == 45
