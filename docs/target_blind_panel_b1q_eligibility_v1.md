# Target-blind panel B1Q eligibility v1

This gate is a provenance decision, not a model or forecast result. It reads
only the registered v2.4 target-blind panel manifest and the target-free
corrected-development source-coverage ledger. It does not read RV30 targets,
metrics, fitted models, holdout artifacts, or provider payloads.

The current decision is `PANEL_NOT_ELIGIBLE_FOR_EVALUATION`. The materialized
panel remains target-blind, but every registered B1Q origin is unresolved in
the source ledger (`34,080` origins) because exogenous-input provenance has not
been demonstrated at the required point-in-time boundary. A target-blind
panel is therefore not allowed to bypass the B1Q gate.

The gate binds the exact SHA-256 bytes and semantic hashes of both registered
inputs. It is fail-closed: changing an input, rehashing a positive decision,
or writing divergent output raises an error. The decision explicitly keeps
reconciliation and OOS evaluation disabled. Resolving this gate requires a
new, documented PIT provenance package; it does not authorize downloading,
model fitting, QLIKE, or opening the holdout.
