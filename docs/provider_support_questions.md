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
2. Is `created_at` a trade-record creation time, an ingestion time, an alert
   creation time, or a customer-visible publication time?
3. Can a historical Full Tape record be revised after `created_at`? If yes, is
   there a version, update timestamp or correction feed?
4. Is there a documented event identifier that is stable between live delivery
   and the subsequently archived Full Tape file?
5. Which live transport, if any, delivers the same option-trade records, and is
   client receipt time available for audit?

Until written provider confirmation exists, these questions preserve the
distinction between an operational availability proxy and a verified provider
publication or client-receipt timestamp.
