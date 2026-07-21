# Recovery requirements quality checklist

This checklist tests the written requirements, not implementation behavior.

## Completeness and clarity

- [x] CHK001 [Completeness] Does the specification state that the v0 manifest is exploratory and byte-preserved rather than accepted as v1?
- [x] CHK002 [Clarity] Does FR-011 identify `C(i,t)`, the 30 future closes, exactly 30 returns and the formula without ambiguous “following closes” wording?
- [x] CHK003 [Edge Case] Are missing prices, halts, early closes, bar start/close semantics and the last valid origin defined as fail-closed decisions?
- [x] CHK004 [Consistency] Do spec, data model, pilot contract and benchmark contract use the same RV30 formula and natural-prevalence event/no-event wording?
- [x] CHK005 [Completeness] Does the manifest contract require request IDs, timestamps, applicability, PIT status and separate authentication/endpoint/schema/entitlement diagnostics?
- [x] CHK006 [Clarity] Is the composite uniqueness key explicit and is repeated-key failure distinguished from duplicate hashes under different requests?
- [x] CHK007 [Completeness] Are `iv_start`/`iv_end` aliases and the distinction between event IV fields and ordinary PIT option state written in every relevant artifact?
- [x] CHK008 [Consistency] Does no artifact claim `executed_at` without observed raw evidence or infer B1 from alert-level IV fields?
- [x] CHK009 [Completeness] Are FMP ETF earnings applicability and returned/requested symbol equality specified?
- [x] CHK010 [Completeness] Are provider audit and literature verification explicitly parallel and are all ten studies required before freeze decisions?
- [x] CHK011 [Clarity] Is Python 3.12.12 selected by compatibility evidence and owner approval, with the applied runtime metadata and lockfile recorded?
- [x] CHK012 [Completeness] Are Delta_Q, day-clustered bootstrap, multiple-testing policy, MDE provenance and predeclared regimes required before final evaluation?
