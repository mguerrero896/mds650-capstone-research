# 20-session calibration decision

Decision: `REVISE_B1_AGAIN`

The twenty-session availability probe is metadata-only and does not authorize a
download. Authorization remains withheld because corrected B1Q ATM coverage is
46.55% globally, four assets have zero B1Q coverage, and the controlled trace
shows that at least some of those zeroes are inconsistent with direct contract
and quote observations. B1T remains diagnostic because it shares the Full Tape
source with B2. No model, QLIKE, backfill, asset freeze or Word update is
authorized by this artifact.

The probe may be considered for `AUTHORIZE_20_SESSION_CALIBRATION` only after
the nested invariants remain green, at least four assets satisfy the declared
B1a coverage and session-segment gates, the historical availability artifact
contains all twenty sessions, the literature evidence ledger is complete, and
the storage margin gate passes.
