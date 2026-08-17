# Gate 7 — Noise-robust target sensitivity (v1)

Compiled 2026-08-17. Code: `scripts/run_gate7_noise_robust.py`; artifact
`artifacts/gate7_noise_robust/results.json` (+ sha256; forecast and bar input hashes
recorded). Frozen C6 forecasts unchanged; only the evaluation proxy varies. Registered
as a target-definition sensitivity parallel to the timing sensitivities.

## Why

Trade-price RV is biased by bid-ask bounce, and Patton (2011) shows QLIKE rankings are
proxy-robust only for conditionally unbiased proxies — the Gamma-vs-LightGBM
disagreement could in principle live inside proxy error.

## Diagnostics (C6 sessions, fresh FMP bars, 11,399 matched origins)

Per-asset AC(1) of 1-minute returns is tiny — from −0.033 (META) to +0.015 (NVDA) —
and the implied Zhou/Hansen-Lunde noise-bias share of RV peaks at 6.5% (META), an
order of magnitude below the +0.05 QLIKE deltas under examination. The uncorrected
target reconstruction matches the frozen panel `rv30` with log-correlation 0.9956
(not bit-exact: the b1v3 acquisition path applied its own bar-quality repairs; stated
as a sensitivity caveat).

## Contrasts under the AC(1)-corrected target RV30* = max(RV30 + 2·Σ rₜrₜ₊₁, floor)

| Model | Frozen target Δ(B2) | AC(1)-corrected Δ(B2) |
|---|---|---|
| Gamma | +0.0528 (p 9.8e−08) | **+0.0522 (p 1.1e−07, wild 1e−04)** |
| LightGBM | −0.0070 (p 0.0042) | **−0.0050 (p 0.0045, wild 0.0054)** |

## Verdict

Signs, magnitudes and significance are unchanged under the noise-robust proxy: the
Gamma-specific positive increment and the LightGBM reversal are **not** microstructure
artifacts. This limitation is retired for C6; the residual (trade-price proxy in the
other campaigns) is inherited by the threats-to-validity matrix with this result as
the representative sensitivity.
