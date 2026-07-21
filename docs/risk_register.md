# Risk register (recovery iteration)

| ID | Risk | Evidence/status | Impact | Mitigation/gate |
|---|---|---|---|---|
| R-001 | Exposed provider credentials | Values were supplied in chat; no values committed | Secret misuse | Rotate before any request; presence-only checks; approved secret store |
| R-002 | v0 manifest is exploratory and has personal Temp provenance | Exact v0 copied byte-for-byte; raw root is non-distributable | Evidence cannot be published as v1 | Preserve v0, migrate raw evidence to restricted persistent storage in T031A, emit sanitized v1 |
| R-003 | Duplicate `underlying_1min_depth_probe` records for eight assets | Same requests/hashes repeat in v0 | Non-idempotent audit and false counts | T018B/T031C composite-key and idempotency tests; retain defect |
| R-004 | FMP timestamp semantics unresolved | Naive timestamp sample only | RV30 origin/target leakage or off-by-one | T025C/T025E calendar, DST, start/close and early-close probes; fail closed |
| R-005 | AMZN/TSLA depth probe has one missing minute each | v0 records 1169 vs 1170 | False completeness | T025F locate minute and classify halt/provider/calendar/process |
| R-006 | UW alias and PIT confusion | Raw fields are `iv_start`/`iv_end`; v0 expected camelCase | False schema failure or false B1 | Alias map and separate event-IV/PIT-state statuses |
| R-007 | UW history/PIT option state unverified | v1n official term-structure fields cover all eight assets; old/oldest UW probes remain unauthorized, the cursor repeats, and only a market date is returned | B1 look-ahead risk | Preserve field coverage, require availability timestamp or defensible as-of contract, and block B1 until verified |
| R-008 | Massive host/contract format ambiguity | Initial raw-ticker/legacy-host probe returned 404/403; corrected `O:` ticker on `api.massive.com` returned 200 with trade conditions, bid/ask fields, two-page quotes pagination and a valid empty window in v1r | Broader contract-level history and licensing remain uncertain | Preserve all runs, use canonical `O:` identifiers, test additional directed windows only after license/entitlement acceptance |
| R-009 | Earnings ETF applicability | SPY/QQQ responses may not be company earnings | Invalid joins | T025D symbol equality and applicability enum |
| R-010 | Runtime/package drift | 3.12/3.13/3.14 resolve on Windows and Linux target; approved Python 3.12.12 lock installs cleanly and runs 75 tests, Ruff and Mypy on Windows | Installation failure in Colab/Windows | Keep `requires-python >=3.12,<3.13`, regenerate lock only through `uv`, and repeat the clean-install gate after dependency changes |
| R-011 | Literature claims unverified | No accepted ten-study matrix yet | Unsupported model/benchmark claims | Phase 3B parallel verification before freezing design |
| R-012 | Multiple testing/MDE/regime hindsight | Final-test policy not frozen | Inflated evidence | Benchmark contract pre-registers Delta_Q, daily bootstrap, corrections, MDE and regimes |
