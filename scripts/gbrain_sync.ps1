[CmdletBinding()]
param(
    [string]$RepoRoot
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

$syncScript = Join-Path $PSScriptRoot "sync_project_knowledge.ps1"
& $syncScript -RepoRoot $RepoRoot -SkipGraphify
exit $LASTEXITCODE
