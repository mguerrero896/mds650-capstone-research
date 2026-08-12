# Provider Timing Clarification Requests v1

## Purpose

These copy-ready technical questions request facts required by the local
point-in-time contract. They do not request data, credentials, account details,
historical bulk downloads, or a subscription change. Do not include an API key
in a support ticket.

After receiving a response, retain the original only in the approved restricted
location. Create a sanitized evidence submission through
[`provider-timing-semantics-evidence-intake-v1`](provider_timing_semantics_evidence_intake_v1.md).
Completeness of that intake is review-only and does not automatically open a
network, B1Q, reconciliation, model, or OOS gate.

## Required response format

Ask the provider to answer every numbered item with:

1. a direct factual statement;
2. an official documentation URL and version/date, or a support-case identifier;
3. the exact endpoint and field name to which the statement applies; and
4. an explicit description of corrections, revisions, or backfills if they occur.

An endpoint description, HTTP status, or general claim that the data are
historical is not sufficient.

## FMP: one-minute bars and B1Q exogenous inputs

**Subject:** Request for timestamp, availability, revision, Treasury and
dividend semantics for historical research

```text
We are documenting a non-trading academic point-in-time study. We do not need
account information or data delivery. Please provide a written answer, with an
official documentation reference or case identifier, for the following.

1. For /stable/historical-chart/1min, does the response timestamp label the
   start of the one-minute bar or the completed close of the bar?
2. What timezone is used by that timestamp? Does it change with US daylight
   saving time, and how are early-close regular sessions represented?
3. After a one-minute US-equity bar is complete, when can that bar first be
   returned by the historical REST endpoint? Please distinguish exchange close,
   vendor ingestion, and customer-visible REST availability.
4. Can an already returned historical one-minute bar later be corrected,
   adjusted, backfilled, deleted, or reordered? If so, how can a customer
   identify the revision and its availability time?
5. For the historical Treasury-rates endpoint, what does each returned date
   mean: observation date, publication date, or another date? When did that
   value first become customer-visible, and can it later be revised?
6. For /stable/dividends?symbol=..., which field records the earliest
   customer-known declaration or announcement date? Can prior records be
   revised or backfilled, and how can that revision be identified?

Please answer each item separately. A generic statement that historical data
are available is not sufficient for our timing audit.
```

Claims required by the intake: `FMP_RESPONSE_TIMESTAMP_TIMEZONE`,
`FMP_BAR_INTERVAL_LABEL`, `FMP_REST_AVAILABILITY_LATENCY`,
`FMP_HISTORICAL_CORRECTION_BEHAVIOR`,
`FMP_TREASURY_OBSERVATION_DATE_SEMANTICS`,
`FMP_TREASURY_HISTORICAL_AVAILABILITY_OR_REVISION_SEMANTICS`,
`FMP_DIVIDEND_DECLARATION_DATE_SEMANTICS`, and
`FMP_DIVIDEND_HISTORICAL_AVAILABILITY_OR_REVISION_SEMANTICS`.

## Unusual Whales: Full Tape event timing

**Subject:** Request for historical Full Tape field and customer-availability
semantics

```text
We are documenting a non-trading academic point-in-time study. We do not need
account information or data delivery. Please provide a written answer, with an
official documentation reference or case identifier, for the historical Full
Tape download endpoint /api/option-trades/full-tape/{date}.

1. What does executed_at mean precisely? Is it the exchange execution time,
   a provider-normalized event time, or another event time? State timezone and
   precision.
2. What does created_at mean precisely? Is it database record creation,
   ingestion, alert creation, publication, or customer-visible availability?
3. Which field or process, if any, proves the earliest time a historical Full
   Tape record became visible to a customer through the API?
4. Can a Full Tape file or a record within it be backfilled, corrected, removed,
   or reissued after the event/session? If yes, how is a revision identified
   and timestamped?
5. Is there a stable unique event identifier that persists across corrections
   and re-downloads? If yes, name the field and its invariants.

Please distinguish execution, provider ingestion, record creation, alert
generation, file generation, and customer-visible availability. We will not
interpret created_at as publication time without an explicit confirmation.
```

Claims required by the intake: `UW_EXECUTED_AT_SEMANTICS`,
`UW_CREATED_AT_SEMANTICS`, `UW_CUSTOMER_VISIBLE_AVAILABILITY`,
`UW_ARCHIVE_CORRECTION_BEHAVIOR`, and `UW_STABLE_EVENT_IDENTIFIER`.

## Massive: historical contract and quote as-of semantics

**Subject:** Request for historical options contract and quote as-of semantics

```text
We are documenting a non-trading academic point-in-time study. We do not need
account information or data delivery. Please provide a written answer, with an
official documentation reference or case identifier, for:

- GET /v3/reference/options/contracts with as_of; and
- GET /v3/quotes/{optionsTicker} with timestamp.lte, sort=timestamp,
  order=desc and limit=1.

1. Does as_of return the contract universe as it was known on that date? State
   the handling of later contract corrections, symbol changes and expired
   contracts.
2. What pagination guarantees apply to historical contract search? State how a
   client can tell that all pages have been received.
3. What deterministic rule is recommended to select one historical ATM/OTM
   contract from a resolved universe without using future information?
4. What exact wire formats are accepted by timestamp.lte, including integer
   nanoseconds and ISO timestamps? Is the comparison inclusive?
5. If multiple quotes share a timestamp, what ordering or tie-break rule applies
   under sort=timestamp and order=desc?
6. Does sip_timestamp represent SIP receipt time, and what timezone and unit
   does it use? Can historical quote records be corrected or backfilled?
```

Claims required by the intake: `MASSIVE_CONTRACT_AS_OF_SEMANTICS`,
`MASSIVE_CONTRACT_PAGINATION_SEMANTICS`,
`MASSIVE_CONTRACT_CORRECTION_BEHAVIOR`,
`MASSIVE_CONTRACT_SELECTION_RULE`, `MASSIVE_QUOTE_LTE_WIRE_FORMAT`,
`MASSIVE_QUOTE_LTE_INCLUSIVITY`, `MASSIVE_QUOTE_ORDERING_TIE_BREAK`, and
`MASSIVE_SIP_TIMESTAMP_SEMANTICS`.

## What changes after a reply

A support reply first becomes a sanitized, hash-bound evidence submission and
then an `EVIDENCE_COMPLETE_REQUIRES_INDEPENDENT_TECHNICAL_REVIEW` assessment.
It does not by itself prove the claim, alter a preflight status, permit a new
provider request, change the B1Q methodology, reconcile legacy results, or
open the holdout. A separate independent technical review and explicit gate
amendment are still required.
