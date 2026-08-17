# Gate 6 — Regime/event composition (v1)

Compiled 2026-08-17. Code: `scripts/run_gate6_regimes.py`; artifact
`artifacts/gate6_regimes/results.json` (+ sha256). Frozen-artifact re-analysis plus the
public ^VIX end-of-day series; decision-52 compliant.

## Regime table

| Campaign | Window | VIX median | VIX max | Mean daily RV30 | Named events inside |
|---|---|---|---|---|---|
| C1 dev | 2026-05-20..07-17 | 16.7 | 22.2 | 1.84e−05 | — |
| C2 holdout | 2026-07-20..07-31 | 18.4 | 20.7 | 1.74e−05 | FOMC 2026-07-29 |
| C4c replication | 2025-05-21..07-03 | 18.2 | 22.3 | 1.43e−05 | 2025-06-13 risk-off |
| C5-A 2024 | 2024-08-02..09-13 | 17.6 | **38.6** | 2.47e−05 | 2024-08-05 vol shock |
| C5-B 2024 | 2024-10-01..11-11 | 19.6 | 23.2 | 1.25e−05 | 2024-11-05 election |
| C6 B1v3 conf. | 2024-10-28..12-09 | **15.1** | 23.2 | 1.58e−05 | 2024-11-05 election |

## Leave-event-week-out (Gamma B2 contrast, frozen evaluators)

| Campaign | Full sample | Without event week | Verdict |
|---|---|---|---|
| C5-A (drop 2024-08-04..08) | +0.0784 (p 6.5e−05) | +0.0581 (p 2.4e−04, wild 1e−04) | Shrinks ~26%, survives |
| C5-B (drop election week) | +0.0348 (p 2.2e−05) | +0.0404 (p 1.4e−05) | **Increases** |
| C6 (drop election week) | +0.0532 (p 8.9e−08) | +0.0600 (p 1.3e−07) | **Increases** |

## Reading

The alternative hypothesis — "the Gamma B2 signal exists only around exceptional macro
events and every calm window is a true null" — is **rejected** for the retrospective
samples: removing the event weeks leaves every contrast significant, and two of three
get larger. The composition confound also fails to explain the decay: C6, the calmest
window by VIX median (15.1), carries the largest effect, while the 2026 windows (VIX
17–18, unremarkable) are null. The decay pattern remains time-linked, not regime-linked
— consistent with a signal that existed in the 2024–mid-2025 provider/market
configuration and has since disappeared, whatever its cause.

Registration for the prospective read: the Gate 4 amendment already fixes the TOST
bound; a regime-conditional secondary (top lagged-RV tercile) is unnecessary as a
rescue device given the rejection above, and adding new subgroup outcomes days before
the read would recreate the forking-paths problem — explicitly NOT added
(`no_subgroup_selection = True` in the frozen method stands).
