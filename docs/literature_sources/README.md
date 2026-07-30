# Literature source register

Latest source-text audit for this register: 2026-07-31. Every matrix row has a DOI or stable
publisher/repository URL. The canonical claim-strength boundary is
`docs/literature_evidence_ledger_v2.csv`, not the broad bibliographic status in this
register. The matrix is a research-gate artifact, not permission to freeze a model or
benchmark. A publisher or repository record validates citation metadata; only a
`VERIFIED_FULL_TEXT` ledger row supports exact numerical or table-level claims.

## DOI resolution check

On 2026-07-21, a read-only Crossref lookup resolved all ten DOI strings to HTTP 200
metadata records. The returned publication years were LIT-001 2024, LIT-002 2024,
LIT-003 2025, LIT-004 2024, LIT-005 2025, LIT-006 2025, LIT-007 2024, LIT-008 2026,
LIT-009 2026 and LIT-010 2026. This validates identifier resolution and date-range
eligibility; it does not replace the row-level full-text and model-claim checks below.

| study_id | Primary source | Access/status | Verification note |
| --- | --- | --- | --- |
| LIT-001 | [Caporin, Di Fonzo & Girolimetto (2024)](https://doi.org/10.1093/jjfinec/nbae014) | Published; publisher version and repository copy | HAR/reconciliation, MSE, QLIKE and MCS claims are checked against the article record and repository metadata. |
| LIT-002 | [Zhang, Song, Peng & Wang (2024)](https://doi.org/10.1002/for.3146) | Published; author-provided full text with Wiley preview | Table 3, the 13-model comparison, jump ablations and multi-step robustness tables were checked. |
| LIT-003 | [Michael, Cucuringu & Howison (2025)](https://doi.org/10.1080/14697688.2025.2454623) | Published; publisher abstract/full text | Option-surface features, XGBoost, QLIKE, DM and MCS claims are checked against the publisher record. |
| LIT-004 | [Díaz, Hansen & Cabrera (2024)](https://doi.org/10.1016/j.irfa.2024.103286) | Published; publisher metadata and abstract record | Detailed model/horizon ranking claims remain metadata-level until full text is audited. |
| LIT-005 | [Li & Tang (2024)](https://doi.org/10.1287/mnsc.2023.01520) | Published online 2024; author SSRN working-paper record | High-level automated OOS forecasting claim is supported by the record; detailed tables remain metadata-level until the full text is auditable. |
| LIT-006 | [Kiliç (2025)](https://doi.org/10.17016/FEDS.2025.061) | Federal Reserve working paper | Exact econometric/ML model list and rolling-forecast result are verified from the primary paper; status is explicitly not peer-reviewed journal publication. |
| LIT-007 | [Li et al. (2024)](https://doi.org/10.1016/j.iref.2024.05.008) | Published; publisher/abstract record | Shrinkage-HAR framing and named regularizers are abstract-level evidence; detailed tables remain unresolved. |
| LIT-008 | [Puke & Schweikert (2026)](https://doi.org/10.1002/for.70114) | Published; Wiley open-access full article | Coherent-HAR method, rolling windows, QLIKE/MSE and individual/panel DMW design were checked; exact table counts remain excluded. |
| LIT-009 | [Asencio et al. (2026)](https://doi.org/10.1016/j.jeconom.2025.106131) | Published; ScienceDirect/IDEAS primary records | It motivates a delta/vega option-flow decomposition only; it is neither an RV forecast benchmark nor evidence of trader intent. |
| LIT-010 | [Omer, Månsson, Sjölander & Uddin (2026)](https://doi.org/10.1002/for.70107) | Published; Wiley/DiVA full text | RR, LASSO, ELNET, RT, RF, NN5, NN10, sg-LASSO, HAR/HAR-XX, rolling evaluation and the reported missing-value imputation are checked; MDS650 must not import that imputation policy. |

## Use restrictions

- Do not treat an abstract-only field as verified when the row marks a full-text follow-up.
- Do not use the LIT-009 informed-trading decomposition as proof of directional intent or
  as proof that unusual options activity forecasts RV.
- Foundational HAR and QLIKE citations remain separate from these ten recent empirical
  studies; the recent rows justify their application here without importing unverified
  claims.
