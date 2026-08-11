# B2 mechanism audit v1

Status: `PASS_DEVELOPMENT_MECHANISM_AUDIT`

The search was frozen before fitting and used only the Phase 5 80-session development panel. The sealed independent samples were not read or used for selection. B2 was evaluated as a residual correction to B1, not as a trade-presence label.

Primary residual variants evaluated: 25.

Variants retained by the frozen rule: [].

The historical JSON field `all_variants_retained` is a legacy naming defect: its
value indicates that every registered variant was written to the ledger, not
that every candidate passed. The authoritative retention fields are
`retained_candidates` and each `candidate_records[*].retained`; both show zero
retained residual candidates. This ambiguity is recorded rather than silently
rewriting the original development evidence.

The residual learner was genuinely B2-only: it fitted cross-fitted
`RV30 - B1 forecast` residuals using only the nine B2 increment features, with
no independent sample read (`oos_read_count = 0`). The primary residual search
had 25 variants (five mechanism families × five registered estimators), plus
25 target-permutation placebos and 25 one-session-lag sensitivities. Every
residual candidate failed at least one frozen gate; the most common failures
were non-positive estimate, confidence interval not above zero, and failure to
clear the Holm-adjusted threshold. The direct B2 protocol was therefore frozen
as the registered fallback before opening the two independent historical blocks.

Gamma–LightGBM divergence is diagnosed with calibration, residual dispersion, train/test PSI drift, feature redundancy and residual interactions; a positive Gamma result alone is not global confirmation.

Observed diagnostics are consistent with that interpretation: maximum B2 pair
correlation was 0.8651, maximum train/test PSI was 0.6204 (expiry
concentration), and the largest global feature-to-B1-residual correlation was
0.0570 in the LightGBM diagnostic. Gamma residual variants also showed extreme
forecast-to-actual ratios (median about 9.0 for residual variants), and their
signed corrections reached the forecast floor; this explains why the residual
learner was not retained. These are diagnostics, not post-hoc reasons to hide
the adverse LightGBM result.

Diagnostics artifact: `artifacts/methodology/b2_mechanism_diagnostics.json`.
