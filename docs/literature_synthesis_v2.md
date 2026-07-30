# Literature evidence synthesis v2

The machine-readable ledger is `docs/literature_evidence_ledger_v2.csv`; the
claim map is `docs/method_claim_source_map_v1.csv`. Ten empirical studies were
retained and classified into ordinary option state, option flow/informed trading,
intraday realised-volatility forecasting and benchmark comparisons.

## Verification boundary

Nine primary-source retrieval attempts were made for the ten DOI records using
publisher, working-paper or open-access routes. Five rows currently have
`VERIFIED_FULL_TEXT` evidence (LIT-001, LIT-002, LIT-003, LIT-006 and LIT-010); two are
`VERIFIED_ABSTRACT_ONLY` and three are
`VERIFIED_PUBLISHER_METADATA_ONLY`. The ledger therefore does **not** support
strong claims for every study. Exact numerical claims are permitted only for
full-text rows and only at the recorded page/section/table location.

Accessible primary links include:

- Caporin, Di Fonzo & Girolimetto (2024),
  `https://doi.org/10.1093/jjfinec/nbae014`;
- Zhang, Song, Peng et al. (2024), `https://doi.org/10.1002/for.3146`;
- Michael, Cucuringu & Howison (2025),
  `https://doi.org/10.1080/14697688.2025.2454623`;
- Díaz, Hansen & Cabrera (2024),
  `https://doi.org/10.1016/j.irfa.2024.103286`;
- Li & Tang (2024), `https://doi.org/10.1287/mnsc.2023.01520`;
- Kiliç (2025), `https://doi.org/10.17016/FEDS.2025.061`;
- Li et al. (2024), `https://doi.org/10.1016/j.iref.2024.05.008`;
- Puke & Schweikert (2026), `https://doi.org/10.1002/for.70114`;
- Asencio et al. (2026), `https://doi.org/10.1016/j.jeconom.2025.106131`;
- Omer et al. (2026), `https://doi.org/10.1002/for.70107`.

## Method implications

The verified full-text rows support using named candidates rather than generic
claims: HAR/OLS and forecast-reconciliation benchmarks; signed-jump LSTM versus
named econometric and machine-learning comparators; option-surface components and
model-derived IV features; THAR/STHAR versus ARFIMA, XGBoost and neural candidates;
and RF/regularisation/ANN comparisons in commodity RV. These markets, frequencies
and horizons differ from this project's five-minute equity RV30 target, so they
justify candidate inclusion and controls, not expected performance.

The ledger does not establish that unusual options activity is causal, that any
specific ML model dominates in this project, or that a vendor timestamp is PIT.
Those claims remain outside the evidence base. HAR and QLIKE are therefore
motivated as candidates, not frozen methods.

Status: **PARTIAL / insufficient for a strong final methodology claim**. At least
six full-text rows must be verified, with page/section/table evidence, before the
literature gate can become YES.
