# Model naming note (v1, 2026-08-18 — reviewer correction)

The registered name `har_rv` / `har_rv_fixed_extension` in the frozen canonical and C5
artifacts does **not** denote the dedicated intraday HAR model. Binding clarification
for every citation:

| Registered name (frozen artifacts) | Actual specification | Where |
|---|---|---|
| `har_rv_fixed_extension` → `har_rv` | **Log-linear fixed extension**: `LinearRegression` on the log target over the frozen `phase6_information_sets()` columns — no intraday/daily/weekly RV components, no realized quarticity | Canonical validation (`src/mds650/canonical_validation.py`), C5 two-block evaluation (`artifacts/b2_confirmation/`) |
| HAR / HARQ (Gate 3+) | **True intraday HAR(Q)**: lagged 30-minute RV, session-to-date RV, previous-session and 5-session components, intraday periodicity, and the BPQ realized-quarticity attenuation term (`src/mds650/har.py`), built from 1-minute bars | `docs/gate3_har_harq_ladder_v1.md`, Gate 12 hardening, era-map HAR-augmented ladders |

Rules:

1. Frozen artifacts keep their registered names verbatim (immutability); the label in a
   sealed parquet is never rewritten.
2. Every document citing the C5/canonical `har_rv` numbers must call it the
   *log-linear fixed extension registered as `har_rv`* — never "HAR-RV" bare, and never
   in a way that implies the Gate-3 HAR sits inside the canonical Model Confidence Sets.
   The two are different specifications; conclusions about one do not transfer to the
   other.
3. The true HAR/HARQ results live exclusively in the Gate 3/11/12 artifacts, where the
   ladder HAR → HARQ → +B1 → +B2 was walk-forward validated with a pre-stated winner
   rule (HARQ).
