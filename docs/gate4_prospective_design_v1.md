# Gate 4 — Decay-aware design for the Phase 8 prospective read (v1)

Compiled 2026-08-17, **before** the Phase 8 one-shot read (30/30 completes 2026-08-29).
Code: `scripts/run_gate4_decay_power.py`; artifact `artifacts/gate4_decay_power/`
(input sha256s recorded). Companion amendment: pre-read interpretation section added to
`docs/phase8_one_shot_protocol_v1.md`. The frozen method hash `87c818be…` is untouched.

## The decay is now a measured trend, not a narrative

Pooled per-day B2 loss differentials from all five frozen campaigns (170 Gamma days),
regressed on calendar time (wild-bootstrap inference on the slope):

| Family | Slope per year | Wild p | Predicted effect at Phase 8 midpoint (2026-08-08) |
|---|---|---|---|
| Gamma (confirmatory lineage) | **−0.0277** | 1e−04 | +0.0053 [−0.0091, +0.0197] |
| LightGBM (tree challenger) | +0.0097 | 1e−04 | +0.0051 [−0.0009, +0.0111] |

The Gamma-specific effect decays sharply toward the present (the two families converge
toward ≈ +0.005 from opposite directions). The campaign-level random-effects
meta-analysis (DerSimonian-Laird, per-campaign estimates and heterogeneity Q/I²/τ²) is
in the artifact.

## Power at n = 30 sessions

Using the recent (C4c + C6) daily standard deviations:

| Family proxy | Achieved MDE (80% power) | Powered for predicted effect? | Powered for TOST at δ_eq = 0.005035? |
|---|---|---|---|
| Gamma-style | 0.01786 | **No** (predicted +0.0053) | No |
| Tree-style (frozen primary is hist-gradient-boosting) | 0.00484 | Borderline | **Yes** |

## Design conclusions (pre-stated)

1. Running Phase 8 as designed is correct: for the frozen tree-family primary the TOST
   equivalence test at δ_eq = 0.005035 is adequately powered, so the most probable
   outcome (a null) becomes affirmative, publishable evidence of absence.
2. For Gamma-sized effects the read is underpowered; the precommitment recorded in the
   protocol amendment interprets a null as prospective confirmation of the decay trend —
   not as an inconclusive shrug and not as grounds for new retrospective campaigns
   (decision-52 moratorium stands).
3. Ex-ante predictions are on record before the read; whatever lands on 2026-08-29 is
   reported against them under the decision-53 hierarchy.
