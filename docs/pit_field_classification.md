# PIT field classification for the bounded pilot

The pilot treats `executed_at` as the market event time and `created_at` as the vendor-record time. A Full Tape event is eligible for the primary B2 feature set only when `created_at <= forecast_origin - 60 seconds`; sensitivity cutoffs are 15 seconds and 0 seconds. No field is treated as available merely because it is present in a payload.

| Field group | Fields | Classification | Rule |
|---|---|---|---|
| Event-time safe after cutoff | `id`, `option_chain_id`, `executed_at`, `created_at`, `price`, `size`, `premium`, `nbbo_bid`, `nbbo_ask`, `strike`, `expiry`, `option_type`, `exchange`, `upstream_condition_detail`, `report_flags`, `tags` | Row-event fields | Use only rows satisfying the selected `created_at` cutoff. Preserve raw UTC and normalized New York time. |
| Conditionally safe | `implied_volatility` | Row-event field with nulls | Usable only when non-null and its derivation/availability is documented; missing values are not imputed. |
| Previous-session only | `open_interest` | Lagged state | Join only the last fully observed prior session; never use the contemporaneous event row as opening OI. |
| Excluded from primary | `volume`, `ask_vol`, `bid_vol`, `no_side_vol`, `mid_vol`, `multi_vol`, provider accumulators | State/aggregate fields | Excluded until monotonicity, reset time, and publication semantics are independently proven. Internal event counts and premium sums are retained as explicitly windowed aggregates. |

The pilot does not infer direction from ask-side tags, calls, sweeps, or premium/volume ratios. A volume greater than prior open interest is not treated as confirmed opening activity.

The Full Tape sample had zero negative `created_at - executed_at` latencies and zero duplicate IDs, but order regressions and out-of-session rows were observed; ordering and session filters therefore remain explicit transformations.
