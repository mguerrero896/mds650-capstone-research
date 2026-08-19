# Block 11b — what the forecast is worth on a contract somebody could trade

**Status:** `EXECUTED — 2026-08-19` · label `EXPLORATORY_MECHANISM_DISCOVERY`
**Artifact:** `artifacts/rp2_block11b_forward/forward_economics.json`
(`forward_sha256 = d0276d65a1217d48e9a5ad898daf53594b4dbee3efcba4d16d374b1a64f8c0dc`)
**Code:** `scripts/rp2_block11b_forward_economics.py`, `src/mds650/rp2/economics.py`
**Decision:** 78

---

## 1. Why the proxy was not enough

Block 11 answers the economic question with a variance-carry proxy: a synthetic short-variance
position marked at annualised implied minus realised variance, charged half the option spread.
Its own document records that it trades in **100 % of periods**, which means it measures
unconditional variance carry rather than anything the forecast contributed. It reports a Sharpe
near **+77**.

That number is not a strategy. It is what being short variance in every period earns in a era
when variance was on average dear — and it never buys a contract.

## 2. The instrument

For every evaluated origin this block selects **one option contract** and holds it for the
forecast horizon:

* **Selection is point-in-time.** The contract is the one nearest the money in the expiry
  closest to 30 days, chosen from what was quoted at entry. Requiring
  a contract to have an exit quote would condition the position on the future, so a contract
  with no newer quote is marked at its last observation and counted — the stale-exit share is
  1.9% in discovery.
* **Nothing is marked at the mid.** The entry pays the ask, the exit receives the bid. Fees are
  $0.65 per contract per side and slippage is
  25% of the half spread.
* **The hedge is struck at the entry delta and held**, which is what a discrete hedger achieves;
  marking it continuously would credit a rebalancing that never happened.
* **The book is capped** at 250 contracts per name and
  1000 gross, per name first.

## 3. The result

5,758 legs in discovery, 954 in validation, from
30,365 built.

| universe | model | information set | net Sharpe | traded | cost / gross | deflated Sharpe p |
|---|---|---|---|---|---|---|
| D | log_ols | B0 | -23.92 | 1.00 | 0.709 | 0.000 |
| D | log_ols | B0+B1+B2 | -23.94 | 1.00 | 0.709 | 0.000 |
| D | gamma_glm | B0 | -23.79 | 1.00 | 0.709 | 0.000 |
| D | gamma_glm | B0+B1+B2 | -23.88 | 1.00 | 0.710 | 0.000 |
| D | lightgbm | B0 | -23.84 | 1.00 | 0.708 | 0.000 |
| D | lightgbm | B0+B1+B2 | -24.11 | 1.00 | 0.707 | 0.000 |
| V | log_ols | B0 | -39.51 | 1.00 | 1.478 | 0.000 |
| V | log_ols | B0+B1+B2 | -39.92 | 1.00 | 1.482 | 0.000 |
| V | gamma_glm | B0 | -38.76 | 1.00 | 1.471 | 0.000 |
| V | gamma_glm | B0+B1+B2 | -38.93 | 1.00 | 1.468 | 0.000 |
| V | lightgbm | B0 | -39.83 | 1.00 | 1.468 | 0.000 |
| V | lightgbm | B0+B1+B2 | -41.28 | 1.00 | 1.472 | 0.000 |

**Every net Sharpe is negative.** Execution cost is
71% of gross P&L in discovery and
148% in validation — in the second universe
the cost of trading exceeds the entire gross move. Every deflated Sharpe probability is 0.000.
Adding B1 and B2 makes the result marginally *worse*, not better.

The proxy's +77 and this -24 are not two
estimates of one quantity. They are different quantities, and only one of them pays a spread on
a contract somebody could buy.

## 4. Advance rule

**"Economic value": FAIL, and now on an instrument rather than an abstraction.** The mechanism
Block 7 measures is real and survives a market control. It does not survive contact with a bid
and an ask.
