[CmdletBinding()]
param(
    [string]$EvidenceRoot = $env:MDS650_EVIDENCE_ROOT,
    [string]$DataRoot = $env:MDS650_DATA_ROOT
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

if ([string]::IsNullOrWhiteSpace($EvidenceRoot)) {
    throw 'MDS650_EVIDENCE_ROOT_REQUIRED'
}
if ([string]::IsNullOrWhiteSpace($DataRoot)) {
    throw 'MDS650_DATA_ROOT_REQUIRED'
}
if (-not (Test-Path -LiteralPath $EvidenceRoot -PathType Container)) {
    throw 'MDS650_EVIDENCE_ROOT_UNAVAILABLE'
}
if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
    throw 'MDS650_DATA_ROOT_UNAVAILABLE'
}

$env:MDS650_EVIDENCE_ROOT = (Resolve-Path -LiteralPath $EvidenceRoot).Path
$env:MDS650_DATA_ROOT = (Resolve-Path -LiteralPath $DataRoot).Path

Push-Location -LiteralPath $repositoryRoot
try {
    uv run python scripts/audit_phase6_source_recovery.py `
        --evidence-root $env:MDS650_EVIDENCE_ROOT `
        --repository-root $repositoryRoot `
        --output artifacts/canonical_validation_v1/phase6_source_recovery.json
    uv run python scripts/run_canonical_validation.py `
        --block phase6 `
        --evidence-root $env:MDS650_EVIDENCE_ROOT `
        --data-root $env:MDS650_DATA_ROOT `
        --output artifacts/canonical_validation_v1
    uv run python scripts/run_canonical_validation.py `
        --block independent_replication `
        --evidence-root $env:MDS650_EVIDENCE_ROOT `
        --data-root $env:MDS650_DATA_ROOT `
        --output artifacts/canonical_validation_v1
    uv run python scripts/report_canonical_validation.py `
        --evidence-root $env:MDS650_EVIDENCE_ROOT `
        --data-root $env:MDS650_DATA_ROOT `
        --input artifacts/canonical_validation_v1 `
        --output artifacts/canonical_validation_v1
    uv run python scripts/build_canonical_evidence_index.py `
        --repository-root $repositoryRoot `
        --data-root $env:MDS650_DATA_ROOT `
        --output artifacts/canonical_validation_v1/evidence_index.csv
}
finally {
    Pop-Location
}
