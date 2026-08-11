[CmdletBinding()]
param(
    [ValidateSet('Prepare', 'Replay')]
    [string]$Mode = 'Prepare',
    [string]$ReplayDirectory = '',
    [string]$OutputDirectory = '.\artifacts\provider_timing\prospective_replay'
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $PSCommandPath
$repoRoot = Split-Path -Parent $scriptRoot

if ($Mode -eq 'Prepare') {
    @(
        'status=PENDING_PROSPECTIVE_MEASUREMENT_NOT_BLOCKING',
        'This command does not open a provider connection, wait for XNYS, or consume a secret.',
        'Future XNYS operator sequence (after an explicit prospective-capture authorization):',
        '1. Synchronize the workstation clock and record its offset.',
        '2. Save normalized provider messages to a restricted local replay JSONL source.',
        '3. Run this script with -Mode Replay against that local source to validate schema and reconciliation.',
        '4. Review artifacts before making any historical or universal-latency claim.'
    ) | ForEach-Object { Write-Output $_ }
    exit 0
}

if ([string]::IsNullOrWhiteSpace($ReplayDirectory)) {
    throw 'REPLAY_DIRECTORY_REQUIRED'
}

$fmpReplay = Join-Path $ReplayDirectory 'fmp_bar_replay.jsonl'
$uwReplay = Join-Path $ReplayDirectory 'uw_option_trade_replay.jsonl'
$receiptOutput = Join-Path $OutputDirectory 'uw_receipts.jsonl'
$fmpOutput = Join-Path $OutputDirectory 'fmp_probe.json'
$reconciliationOutput = Join-Path $OutputDirectory 'uw_reconciliation.json'

foreach ($required in @($fmpReplay, $uwReplay)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "REPLAY_INPUT_MISSING:$required"
    }
}

Push-Location $repoRoot
try {
    uv run python scripts/probe_fmp_bar_availability.py --replay $fmpReplay --output $fmpOutput
    uv run python scripts/log_uw_option_trade_receipts.py --replay $uwReplay --output $receiptOutput
    uv run python scripts/reconcile_uw_live_vs_full_tape.py `
        --receipt-replay $receiptOutput --full-tape-replay $uwReplay --output $reconciliationOutput
}
finally {
    Pop-Location
}

Write-Output 'status=REPLAY_VALIDATED_NOT_LIVE'
