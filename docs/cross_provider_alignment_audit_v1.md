# Cross-provider alignment audit v1

Evidence: `artifacts/audits/cross_provider_alignment_v1.json`. This is a
descriptive audit of the retained 25-session local inputs; it is not a provider
entitlement or predictive-performance claim.

## Global rates

| Provider | Rows audited | Alignment pass rate | Rule |
|---|---:|---:|---|
| FMP | 14,200 | 93.24% | exact asset/session/origin and conservative availability |
| Massive | 14,200 | 90.96% | historical contract plus `sip_timestamp <= origin` |
| Unusual Whales | 14,200 | 80.00% | exact asset/origin bin after operational cutoff |

The lower UW rate reflects retained event/asset alignment and is not evidence of
absence of market activity. Full Tape and B2 are not independent of one another.

## Join and normalization controls

- Underlying symbols are normalized to the eight approved roots.
- OCC/root, expiry, strike and call/put consistency are preserved from the
  prior B1 and Full Tape contracts.
- FMP and UW timestamps are normalized to UTC while retaining New York session
  labels; XNYS defines regular-session boundaries.
- Massive is joined as-of, not by unconstrained nearest neighbour.
- UW is joined to the exact five-minute origin bin after the chosen cutoff.
- Duplicates, out-of-order records, crossed markets, stale quotes and missing
  underlying prices are exclusions, not silent repairs.
- Corporate actions, splits and special-dividend coverage remain a limitation
  requiring provider-level follow-up; they are not inferred from the sample.
- The prior `expired=true`/`expired=false` behavior is retained as an explicit
  audit observation, not hidden as proof of entitlement.

## Consequence

The alignment artifacts are adequate for engineering diagnostics and lineage.
They do not establish a continuous historical common window or grant permission
to run a final B0/B1Q/B2 comparison. The strict matrix is therefore a local
readiness artifact only.
