[CmdletBinding()]
param(
    [string]$RepoRoot
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    throw "No se pudo resolver la raíz Git del repositorio."
}

$resolvedRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$sourceMarker = Join-Path $resolvedRoot ".gbrain-source"
if (-not (Test-Path -LiteralPath $sourceMarker -PathType Leaf)) {
    throw "Falta .gbrain-source; se rechaza una sincronización sin fuente explícita."
}

$sourceId = (Get-Content -LiteralPath $sourceMarker -Raw).Trim()
if ($sourceId -notmatch "^[a-z0-9][a-z0-9._-]{1,63}$") {
    throw "Identificador de fuente GBrain inválido: $sourceId"
}

$gbrain = Get-Command gbrain -ErrorAction Stop
& $gbrain.Source sync `
    --source $sourceId `
    --repo $resolvedRoot `
    --no-pull `
    --no-embed `
    --no-extract `
    --yes `
    --json

if ($LASTEXITCODE -ne 0) {
    throw "GBrain sync terminó con código $LASTEXITCODE."
}
