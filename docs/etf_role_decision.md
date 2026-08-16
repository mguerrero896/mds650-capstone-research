# ETF role decision

Status: `MARKET_CONTROL_ONLY_FOR_CURRENT_PHASE`

SPY and QQQ remain in the candidate audit and may remain B0 market controls.
They are not eligible target assets while B1Q coverage is zero in the full
matrix and the controlled/full reconciliation is unresolved. This classification
uses only quote coverage, PIT integrity, instrument type and integration
complexity; no RV30, QLIKE or predictive statistic was used.

If the repaired B1Q route reaches the same thresholds as equities, the target
role may be reconsidered. Until then:

- `market_control_only`: SPY, QQQ
- `eligible_target_candidates`: AAPL, AMZN, META, MSFT, TSLA (B1a and IV
  success gates pass; provisional only)
- `excluded_due_to_data_quality`: NVDA (IV success rate below 80%) and SPY/QQQ
  as targets (ETF coverage/IV quality); this is not a predictive exclusion.
