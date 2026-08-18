# Gate 12 + global Holm + economic significance (v1, 2026-08-18)

Three hardening deliverables from the remaining-work investigation. Labels:
EXPLORATORY_DESCRIPTIVE (Gate 12), conservative-bound (Holm), TOY/DESCRIPTIVE (econ).
Artifacts: `artifacts/gate12_harq_hardening/`, `artifacts/global_multiplicity/`,
`artifacts/economic_significance/` (+ sha256; inputs hashed inside).

## Gate 12 — the positive survives HAR-class baselines

`scripts/run_gate12_harq_hardening.py`. Design A: every era panel augmented with
target-blind daily/weekly HAR components; ladder B0+HAR → +B1 → +B2; families log-OLS
and LightGBM (Ridge dropped — it numerically duplicates log-OLS, per the 2026-08-18
caveat). Design B: true HARQ (bar-based realized quarticity) on the development era.

| Era | Family | B0HAR→B2 total | Verdict |
|---|---|---|---|
| 2025H1 | log-OLS / LightGBM | **+0.0574 (p 9.5e−04)** / **+0.0175 (p 0.0024)** | survives, both families |
| 2025H2–2026Q1 | log-OLS / LightGBM | **+0.0196 (p 0.002)** / **+0.0089 (p 9.2e−06)** | survives, both families |
| 2024H2 (B1v3) | log-OLS / LightGBM | +0.0293 (p 0.004) / +0.0027 ns | mixed (redesign era) |
| 2026H1 dev | log-OLS / LightGBM | −0.0030 ns / +0.0092 (p 0.012) | fade era; tree-only |

True HARQ on dev (Design B): all three contrasts null — identical to Gate 3. Conclusion:
**the 2025 cross-family total option-information gain survives HAR-augmented baselines in
both independent families**; the only place HAR-class baselines absorb everything is the
2026 development era, which was already the measured fade. The decision-56 centerpiece is
hardened, with the Ridge-duplication caveat honestly recorded.

## Global Holm — roadmap 4.4 closed

`scripts/run_global_multiplicity.py`: one Holm family across all 36 registered post-null
contrasts (Gate-1 wild-bootstrap p-values; C2 anchors the family). **21/36 survive at
5%**, including C6 Gamma B2 (adj. p 0.0036) and the cross-family 2024 B0→B1a set. The
mechanism search's 25 discarded variants and C3's sign aggregates are enumerated as
uncorrectable. Stated as a conservative bound: the campaign sequence was data-dependent,
so the clean answer remains the prospective reads. Exploratory decision-56 contrasts are
corrected in a separate 63-member family (19 survive).

## Economic significance — roadmap 5.4 closed

`scripts/run_economic_significance.py` (annualization 13×252 windows/year; toy $100k
notional; no execution/costs/profitability claim). Honest headline:

- **In calibrated families the effect is economically minuscule**: C6 Gamma B1→B2 =
  +3.1% annualized-vol RMSE ≈ **$0.02 per 30-minute window per $100k** toy notional;
  C4c Gamma +4.8% ≈ $0.09/window; LightGBM ≈ zero-to-negative everywhere.
- The spectacular numbers are diagnostic, not economic: C5 Gamma's "+98.9% RMSE
  reduction / $5.8bn per window saving" is the R-020 calibration explosion expressed in
  dollars — B2 was repairing a broken baseline, exactly as Gate 2 concluded.
- The C5 `har_rv` family (log-linear fixed extension, not the Gate-3 intraday HAR —
  see `docs/model_naming_note_v1.md`) in the 2024 blocks shows the era-value honestly:
  +36% vol-RMSE reduction
  (≈ $2,319/window at the block-A scale) — large in the era where the information was
  real, gone since.

One sentence for the thesis: *statistically hardened, economically small in calibrated
terms, and any headline-sized economic number in this project is a symptom of model
miscalibration rather than of exploitable information.*
