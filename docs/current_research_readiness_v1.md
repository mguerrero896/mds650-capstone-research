# Current Research Readiness v1

This target-blind ledger binds five immutable local artifacts as of 12 August
2026.  It answers a narrow operational question: whether the project may move
from frozen method design to a B0/B1/B2 evaluation.

The answer is **no**.  The ledger deliberately records both of these facts:

- FMP has observed minute-bar availability for 90 of 90 planned sessions and
  Unusual Whales has observed Full Tape file metadata for 90 of 90 sessions.
- Availability does not establish point-in-time timestamp semantics.  B1Q's
  rate/dividend provenance is unresolved and the date-level PIT preflight is
  `FAILED_CLOSED` with zero network attempts.

Consequently, it does not authorize historical acquisition, sealed-result
reconciliation, OOS access, model fitting, metric evaluation, or a B0/B1/B2
comparison.  The exact blockers are retained in the generated JSON rather
than inferred from this narrative.

Regenerate or verify the immutable record locally:

```powershell
uv run --offline python -c "from pathlib import Path; from mds650.current_research_readiness_v1 import write_current_research_readiness_v1 as w; root=Path('.'); w(input_paths={'policy_gate': root/'artifacts/provider_timing_v22/provider_timing_evidence_policy_gate_v1_20260812.json', 'preflight': root/'artifacts/preflight/date_level_pit_preflight_status_v2_1_current.json', 'source_coverage': root/'artifacts/corrected_development_v1/source_coverage_ledger.json', 'fmp_docs_review': root/'artifacts/provider_timing_v21/fmp_b1q_exogenous_docs_review_v1_20260812.json', 'confirmation_readiness': root/'artifacts/target_blind_v24_sourcebound_20260812/confirmation_readiness_v3.json'}, output_path=root/'artifacts/current_research_readiness_v1/current_research_readiness_v1_20260812.json')"
```

The writer accepts only byte-identical replays.  A changed input or divergent
output fails closed.
