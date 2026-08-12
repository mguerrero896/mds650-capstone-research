# Provider Support Questions — Timing Semantics

## Financial Modeling Prep

1. For `stable/historical-chart/1min`, what timezone is carried by the returned
   `date`/timestamp field for US equities and ETFs?
2. Does that timestamp label the start of the one-minute interval, its completed
   close, or another convention?
3. After an XNYS one-minute interval completes, what is the documented or
   measured availability latency of the completed OHLCV bar through this endpoint?
4. Are historical intraday bars ever corrected after initial availability? If so,
   how are corrections timestamped and versioned?

## Unusual Whales

1. In historical Full Tape, what precisely do `executed_at` and `created_at`
   represent, including their clock source and UTC convention?
2. The public Kafka `OptionTrade` definition describes `created_at` as the time
   the trade record was created. Does the historical Full Tape preserve that
   exact semantic identity, including during ingestion, correction and archive
   generation?
3. Does creating the trade record make it synchronously visible through the
   historical Full Tape or any documented live transport? If not, what field or
   receipt event represents customer-visible availability?
4. Can a historical Full Tape record be revised after `created_at`? If yes, is
   there a version, update timestamp or correction feed?
5. Is there a documented event identifier that is stable between live delivery
   and the subsequently archived Full Tape file?
6. Which live transport, if any, delivers the same option-trade records, and is
   client receipt time available for audit?

## Massive

1. For `GET /v3/quotes/{optionsTicker}`, does `timestamp.lte` use an inclusive
   comparison when supplied as a 19-digit nanosecond Unix timestamp? Please
   confirm the accepted wire format for the range modifier itself, not only the
   base `timestamp` field.
2. Does `order=desc&sort=timestamp&limit=1` return the final quote at or before
   that inclusive cutoff, with `sequence_number` resolving ties at the same
   `sip_timestamp`? If a tie rule is not guaranteed by the endpoint, what is
   the documented deterministic ordering?
3. For `GET /v3/reference/options/contracts`, what exactly does `as_of` mean
   for historical contract metadata: listing eligibility on that date, a
   versioned snapshot, or the current reference record filtered by date?
4. Can contract reference records or historical quote records be corrected after
   their original publication? If so, are correction/version timestamps exposed
   and can a customer reproduce the state that was visible at a past origin?
5. Is there any documented server-publication, API-availability or customer
   receipt timestamp for historical quote responses distinct from
   `sip_timestamp`? If none exists, please confirm that limitation explicitly.

## Evidence acceptance rule

An answer can close a timing-semantic gate only if it is a written provider
response linked to a support case, a versioned official specification, or a
provider technical document that addresses the exact field and endpoint above.
It must state the timestamp clock, time zone, semantics, correction behavior
and availability relationship relevant to the question. A plan description,
marketing statement, endpoint existence, HTTP 200 response or generic verbal
assurance is not sufficient.

Any accepted clarification will be retained in sanitized form with its source
URL or support-case identifier, reviewed against an authenticated but bounded
probe, and then assessed by the PIT gate. It does not by itself authorize
backfill, OOS evaluation, model training or a claim of a positive edge.

Until written provider confirmation exists, these questions preserve the
distinction between an operational availability proxy and a verified provider
publication or client-receipt timestamp.

## Sanitized intake after a response

Do not commit the raw support email, authorization headers, customer identity,
local path, or provider payload. Retain the original in restricted storage,
then create a sanitized, hash-bound submission using
[`provider-timing-semantics-evidence-submission-v1.schema.json`](../specs/001-pit-options-rv30/contracts/provider-timing-semantics-evidence-submission-v1.schema.json).
Assess it locally with
`scripts/assess_provider_timing_semantics_evidence_v1.py`. A complete intake
remains review-only and cannot itself enable provider network access, backfill,
sealed-result reconciliation, OOS evaluation, or model fitting.
