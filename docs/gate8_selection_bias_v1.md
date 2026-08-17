# Gate 8 — Common-complete selection bias (v1)

Compiled 2026-08-17. Code: `scripts/run_gate8_selection.py`; artifact
`artifacts/gate8_selection/results.json` (+ sha256; input hashes recorded). C6 only —
its bars are on disk from Gate 7; the same design applies to C4c when its bars are
fetched (deferred, stated in the artifact).

## Design

Nominal origin grid (30 confirmation sessions × 6 assets × the observed grid times,
11,880 cells) with target-blind covariates from independently downloaded bars (lagged
30-minute RV, session minute, asset); logistic inclusion model for
P(common_complete); stabilized IPW weights (clipped at 20; observed max 1.05);
frozen per-origin QLIKE losses reweighted and re-tested.

## Results

- **Inclusion is 11,577 / 11,880 = 97.4%** on the binding C6 sample. The 67.5%
  strict-sample figure from the pilot audit belonged to earlier panel eras; it does not
  describe C6. Excluded cells are well separated by the model (mean fitted probability
  0.987 for included vs 0.498 for excluded), yet they are only 2.6% of the grid.
- IPW moves nothing:

| Contrast | Model | Unweighted | IPW-weighted |
|---|---|---|---|
| B1v3a vs B0 | Gamma | +0.04984 (p 3.6e−07) | +0.04989 (p 3.6e−07) |
| B2 vs B1v3a | Gamma | +0.05280 (p 1.0e−07) | +0.05290 (p 9.9e−08) |
| B1v3a vs B0 | LightGBM | +0.01618 (p 0.054) | +0.01613 (p 0.054) |
| B2 vs B1v3a | LightGBM | −0.00741 (p 0.0023) | −0.00739 (p 0.0023) |

## Verdict

On the binding sample, the common-complete join can bias estimates by at most a few
units in the fourth decimal — the selection-bias objection (including against the
adverse B1-worse-than-B0 finding) is **bounded at negligible for C6** and moves to the
threats-to-validity matrix as resolved-there / residual-elsewhere.
