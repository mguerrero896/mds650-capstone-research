# Secondary unusualness definition (not calibrated in Pilot V2)

`unusual_event` is a secondary, interpretable label. It MUST NOT be derived from five Pilot V2
sessions alone and MUST NOT replace the continuous B2 variables.

## Provisional calibration contract

- Minimum trailing history: 15 prior trading sessions.
- Preferred history: 20 or more prior sessions.
- Candidate threshold: trailing 95th percentile, recorded as indicative only.
- Robust alternatives: trailing median and MAD, with parameters estimated separately by asset,
  interval of day, and calls/puts where economically appropriate.
- Every trailing statistic uses dates strictly earlier than the forecast origin; no same-day
  future information is permitted.
- Natural prevalence is preserved in validation and final testing; any training-only weighting
  or subsampling must be documented.

Calibration is deferred until Pilot V2 passes its data, PIT, coverage and reproducibility gates.
