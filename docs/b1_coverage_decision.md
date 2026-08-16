# B1 coverage decision

This document is generated only after the B1Q/B1T matrices and PIT checks are
complete. The decision is based on route, coverage, missingness and timestamp
quality, never predictive performance.

## Gate

An `AUTHORIZE_20_SESSION_CALIBRATION` request requires B1a global coverage of at
least 70%, at least 50% for every asset, at least 40% in each session tercile,
valid PIT, no close-only concentration, common-history evidence for at least
four assets, resumable checkpoints, passing tests/schemas, and P95 storage with
a 30% margin. B1b and B1c may remain robustness levels.

Pilot V2 closure evidence (2,840 origins) gives B1Q Massive coverage of
B1a=46.55%, B1b=22.85% and B1c=44.01%. B1Q tercile coverage is 40.00% in the
first tercile, 46.57% in the middle and 49.58% in the last. B1T reaches 100%
for the three levels, but it is derived from the same Full Tape provenance as
B2 and is therefore diagnostic/fallback only, not an independent primary
benchmark. The status is `REVISE_B1`; the 20-session request remains
unissued. No predictive performance was used in this decision.
