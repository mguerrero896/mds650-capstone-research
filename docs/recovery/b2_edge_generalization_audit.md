# B2 Edge Generalization Audit

**Audit date:** 2026-08-10  
**Scope:** development evidence and already sealed Phase 6 evidence only. No new outcomes were read by this audit.

## What the MDE means

The minimum detectable effect (MDE) is a planning quantity: the smallest paired daily QLIKE improvement that the preregistered bootstrap/Holm design is expected to detect with 80% power under the training-only dispersion observed before the relevant outcome read. It is not an economic threshold, a claim that smaller effects are zero, or a value that may be redefined after observing OOS results. The frozen Phase 6 values are `0.021685775175972016` for B1v2 and `0.005035098377136471` for B2v2.

## Existing training audit

The original Phase 5 development artifact remains `PASS_DEVELOPMENT_ONLY` with
15,548 common origins and 93,288 frozen forecast rows. The current
generalization comparison derives 233,220 paired forecast rows from those same
origins so that all five registered model families are evaluated on the same
B0/B1/B2 panel. Both artifacts record zero independent/OOS reads. Phase 6
training-only MDE uses 11,841 training origins, 35,523 forecast rows and 60
initial-training sessions with `oos_read_count=0` in its training ledger.

The development-only comparison required for this goal is now complete in a
separate, target-preserving ledger. It executes persistence, HAR-RV, Ridge,
Gamma GLM and LightGBM on the same B0/B1/B2 origins; Elastic Net is registered
but explicitly marked `REGISTERED_NOT_RUN_RUNTIME_BUDGET`. The comparison has
15,548 origins, 233,220 paired forecast rows and zero independent/OOS reads.
Its results are descriptive: HAR-RV and Ridge show the largest development B2
improvement, Gamma is positive with a smaller effect, and LightGBM is not
uniformly positive. No model is promoted on sign alone.

## Existing evidence retained

Phase 5 development found B1 neutral/slightly negative under Gamma (`-0.000288269454701238`) and positive under LightGBM (`+0.004830681758071913`); B2 was positive under both (`+0.013117577107306001` Gamma and `+0.0021911878513316404` LightGBM). Its ten-day holdout was not globally confirmatory: Gamma B1 `-0.007048655575142009`, Gamma B2 `+0.0006130677357146971`; LightGBM B1 `-0.01143678024629425`, LightGBM B2 `-0.0005273483218764497`.

Phase 6 is a separate sealed replication with 100 daily clusters. Its global Gamma deltas are positive (`+0.011802813503413103` B1v2 and `+0.004439122531545663` B2v2), and LightGBM has the same signs, but both are below their frozen MDE values. The recorded decision therefore remains `TARGETED_B2V2_REPLICATION_CONFIRMED`, not global confirmation.

## Integrity conclusion

The evidence supports an additional development comparison and a disjoint independent replication. It does not authorize changing the target, selecting a model from the existing OOS results, or promising a favourable sign.
