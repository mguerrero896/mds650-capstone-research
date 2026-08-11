# Provider Timing PIT Claim Matrix v2.1

Each conclusion is limited to its evidence class. Documentation bodies are not
stored; the official body SHA-256 identifies the reviewed content.

| Claim | Evidence class | Permitted conclusion |
| --- | --- | --- |
| fmp_bar_start_or_close | UNVERIFIED | Do not claim whether the raw bar label marks start or close. |
| fmp_completed_bar_latency | UNVERIFIED | Do not claim a numeric completed-bar availability latency. |
| fmp_dst_behavior | UNVERIFIED | Do not claim provider-documented DST conversion behavior. |
| fmp_exact_iana_timezone | UNVERIFIED | Do not claim an exact provider IANA timezone implementation. |
| fmp_intraday_exchange_region_timezone | PROVIDER_DOCUMENTED | FMP documents endpoint time zones at the exchange country or region level. |
| fmp_plus_one_minute | STUDY_CONSERVATIVE_RULE | Use raw timestamp plus one minute as a conservative rule. |
| massive_shifted_asof_selection | STUDY_CONSERVATIVE_RULE | Reselect the last SIP quote no later than each shifted cutoff. |
| uw_created_at_operational_proxy | STUDY_CONSERVATIVE_RULE | Treat created_at only as an operational availability proxy. |
| uw_full_tape_created_at_field | PAYLOAD_OBSERVED | Acquired Full Tape partitions contain a UTC created_at field. |
| uw_full_tape_created_at_semantics | UNVERIFIED | Do not transfer Kafka field semantics to Full Tape REST solely from a field-name match. |
| uw_full_tape_endpoint | PROVIDER_DOCUMENTED_REST | The documented endpoint returns a ZIP of transactions for a date. |
| uw_kafka_created_at | PROVIDER_DOCUMENTED_KAFKA | Kafka defines created_at as trade-record creation time in Unix milliseconds. |
| uw_kafka_executed_at | PROVIDER_DOCUMENTED_KAFKA | Kafka defines executed_at as trade execution time in Unix milliseconds. |
| uw_zero_activity_semantics | NOT_PERMITTED_WITHOUT_AVAILABILITY_SIDECAR | Do not interpret zero as no activity where source availability is confounded. |
| uw_zero_coding_availability | PAYLOAD_OBSERVED | A numeric B2 zero is a coding state, not automatically no activity. |
