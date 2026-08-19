# STATUS — canonical project state

> AUTO-GENERATED from `data/CANONICAL_STATE.json` by
> `scripts/generate_canonical_state.py`. Never edit by hand; CI fails on drift.
> This file supersedes any narrative document that disagrees with it.

- Governance: decision 80 is the latest (80 recorded).
- Frozen evidence: 61 artifacts pinned in `data/FROZEN_ARTIFACTS.json` (physical tripwire on every CI run).
- Gated data: 15 files in private storage (`data/GATED_DATA_POINTERS.json`).

## Active protocols

- **phase8-one-shot** — `docs/phase8_one_shot_protocol_v1.md`: frozen; owner authorization gate 2026-08-29
- **phase9-total-contribution** — `docs/phase9_total_contribution_protocol_v1.md`: frozen; collection active for sessions strictly after 2026-08-18, 60-session clock, evaluation authorization ~Nov 2026

## Canonical results (citation rule: decision 53)

- B2-over-B1 activity increment: prospectively null, model-family-bound, calibration-linked (decisions 48/53); the Gamma family never enters any canonical Model Confidence Set at any bootstrap block length.
- Total option-state contribution (B0 to B2): cross-family positive on the 2024 blocks and both 2025 eras under the uniform ladder, decaying to null by 2026 (decision 56, EXPLORATORY_DESCRIPTIVE; decay -0.0277/yr).
- Registered model name har_rv is a log-linear fixed extension, NOT the Gate-3 intraday HAR/HARQ (decision 60, docs/model_naming_note_v1.md).

## Future campaigns

- Phase 8 one-shot confirmation (single authorized read, after 2026-08-29)
- Phase 9 total-contribution evaluation (after 60 collected sessions, ~Nov 2026)

## CI

- Required checks: quality, hermetic (coverage >= 80%).
- Tier 2 (licensed evidence): `scripts/run_local_evidence_gates.py`; scripts/publish_mirror.sh refuses to push unless tier-2 passes.

## Superseded documents (do not cite as current)

- `docs/architecture.md` — pre-pilot boundary description; current state lives in STATUS.md and docs/INDEX.md
- `reports/remaining_work_investigation_20260818.md` — point-in-time snapshot from 2026-08-18 morning; thesis prose, hosted test CI and alerting listed there as missing were delivered the same day — see STATUS.md
