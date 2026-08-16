# 20-session calibration decision v2

Decision: `AUTHORIZE_20_SESSION_CALIBRATION`

The B1Q integration repair succeeded technically: bucket-scoped resolution
removed the 1,420 invalid-DTE rows, corrected the controlled/full selection
diagnosis and produced monotone nested coverage. The 20-session metadata probe
still contains 20 available session records without downloading ZIP payloads.

The literature ledger correctly limits rows without captured page/section/table
coordinates to `EXCLUDE_FROM_ARGUMENT`; no unsupported strong claim is used.
The controlled/full comparison now reconciles the same four contracts with no
divergent stage. This artifact authorizes only a future 20-session calibration
download after human approval. It does not authorize backfill, models, QLIKE,
asset freeze or Word/PowerPoint edits.
