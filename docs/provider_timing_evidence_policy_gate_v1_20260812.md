# Evidence-Scoped Provider-Timing Policy Gate v1

**Status:** `PASS_EVIDENCE_SCOPED_POLICY_FAIL_CLOSED`.

## Decision

`SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` remains current for sealed pre-v2.2
results. The corrected v2.2 sidecar is an immutable exclusion mask for a new
target-blind panel, not a repair of sealed output; the v2.3 source-bound panel
and preregistration prepare a successor method freeze but do not reconcile
legacy results. This gate therefore supplements the v1 evidence-scoped timing
amendment; it does not replace the literal reconciliation `NO` with `YES`.

## Target-blind compatibility matrix

| Scope | Evidence-supported state | Current authorization | Boundary |
|---|---|---|---|
| Existing frozen canonical evidence | `VALID_UNDER_REGISTERED_TIMING_ASSUMPTIONS` | Interpretation only | Registered FMP `+1/+2` study rules, Massive SIP as-of technical selection and UW `created_at` proxy remain bounded assumptions. |
| Existing sealed/pre-v2.2 result reconciliation | `BLOCKED` | `SAFE_TO_RECONCILE_EXISTING_RESULTS=NO` | v2.2 requires a new masked target-blind panel; v2.3 does not backpatch or reconcile legacy output. |
| OOS access/evaluation | `BLOCKED` | `SAFE_TO_OPEN_OR_EVALUATE_OOS=NO` | A separate successor method freeze, zero-OOS-read record and explicit human authorization remain required. |
| New historical acquisition | `GO_AFTER_DATE_LEVEL_PIT_PREFLIGHT` | `NO` now | Passing the timing preflight is a prerequisite, not OOS authority or permission to fit/evaluate a model. |
| Prospective capture | `GO_AFTER_RECEIPT_LOGGER_VALIDATED` | `NO` now | A validated receipt logger is a timing prerequisite, not OOS authority or permission to fit/evaluate a model. |

## Evidence and fail-closed behavior

The machine-readable record is
`artifacts/provider_timing_v22/provider_timing_evidence_policy_gate_v1_20260812.json`.
It self-hashes and binds the v2.1 reconciliation aggregate, v2.2 availability
manifest, official-documentation limitation audit, v2.3 source-bound manifest,
v3 preregistration and v2 readiness snapshot. It fails if any source gate,
self-hash, source binding or documentary boundary changes.

The policy makes no predictive, economic, provider-latency, model-fit, metric,
or OOS claim. It makes no provider request and reads no target or sealed-result
payload.

## Sources

- `docs/provider_timing_gate_amendment_v1.md`
- `docs/methodology_decisions.md` (Decisions 35–36)
- `docs/pit_reconciliation_gate_v21_addendum_20260812.md`
- `docs/provider_timing_pit_contract_v22.md`
- `docs/pit_v22_decision_ledger.md` (Decision 43)
- `docs/confirmation_protocol_v2_sourcebound.md`
