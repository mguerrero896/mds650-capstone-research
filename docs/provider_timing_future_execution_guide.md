# Provider Timing Future Execution Guide

## Current status

`PENDING_PROSPECTIVE_MEASUREMENT_NOT_BLOCKING`

This status is pending and non-blocking. No market-open wait, provider HTTP
request, WebSocket connection or real-time capture was performed by this audit.

## Before a future authorized XNYS capture

1. Obtain explicit authorization for a prospective measurement window.
2. Synchronize the workstation clock and record the clock offset.
3. Store normalized provider messages in restricted storage, never in Git.
4. Ensure every persisted record includes when available: `event_id`, `trade_id`,
   `aggregated_trade_id`, `executed_at`, `created_at`, `received_at_utc`, `source`,
   `connection_type`, `local_clock_offset` and `raw_message_hash`.
5. Preserve raw payloads separately from sanitized receipt logs and never place
   API keys or personal paths in distributable artifacts.

## Local replay validation commands

```powershell
pwsh -NoProfile -File .\scripts\run_provider_timing_capture_once.ps1 -Mode Prepare

# Only after a future operator has saved local replay fixtures:
pwsh -NoProfile -File .\scripts\run_provider_timing_capture_once.ps1 `
  -Mode Replay -ReplayDirectory D:\MDS650\restricted\provider_timing_replay
```

`Prepare` is intentionally safe: it does not connect to a provider, wait for a
session or consume credentials. `Replay` validates only locally supplied replay
files through the three scripts below:

- `scripts/probe_fmp_bar_availability.py`
- `scripts/log_uw_option_trade_receipts.py`
- `scripts/reconcile_uw_live_vs_full_tape.py`

Successful replay proves schema handling and deterministic logging, not live
receipt latency, provider publication time or a universal provider latency rule.
