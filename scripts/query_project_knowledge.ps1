[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Query,

    [ValidateSet("Both", "GBrain", "Graphify")]
    [string]$Engine = "Both",

    [ValidateRange(1, 100)]
    [int]$Limit = 20,

    [ValidateRange(200, 10000)]
    [int]$GraphBudget = 2500
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$sourceId = (Get-Content -LiteralPath (Join-Path $repoRoot ".gbrain-source") -Raw).Trim()
if ($sourceId -ne "mds650-research") {
    throw "La consulta fue rechazada porque la fuente no es mds650-research."
}

$env:GBRAIN_HOME = Join-Path $env:USERPROFILE ".mds650"
Set-Location -LiteralPath $repoRoot

$gbrainOutput = @()
$gbrainSeedOutput = @()
if ($Engine -in @("Both", "GBrain")) {
    foreach ($source in @("mds650-research", "mds650-code")) {
        Write-Output "=== GBRAIN $($source.ToUpperInvariant()) ==="
        $sourceOutput = @(
            & (Get-Command gbrain -ErrorAction Stop).Source search $Query `
                --source $source --limit $Limit --mode tokenmax
        )
        $sourceOutput | Write-Output
        $gbrainOutput += $sourceOutput
        $gbrainSeedOutput += @($sourceOutput | Select-Object -First 3)
        if ($LASTEXITCODE -ne 0) {
            throw "GBrain search de $source terminó con código $LASTEXITCODE."
        }
    }
}

if ($Engine -in @("Both", "Graphify")) {
    if ($gbrainOutput.Count -eq 0) {
        foreach ($source in @("mds650-research", "mds650-code")) {
            $sourceOutput = @(
                & (Get-Command gbrain -ErrorAction Stop).Source search $Query `
                    --source $source --limit 5 --mode tokenmax
            )
            $gbrainOutput += $sourceOutput
            $gbrainSeedOutput += @($sourceOutput | Select-Object -First 3)
            if ($LASTEXITCODE -ne 0) {
                throw "La expansión local de $source para Graphify terminó con código $LASTEXITCODE."
            }
        }
    }

    $seedSlugs = @(
        $gbrainSeedOutput |
            ForEach-Object {
                if ($_ -match "\b(?:function|class)\s+([A-Za-z_][A-Za-z0-9_]*)") {
                    $Matches[1]
                }
                elseif ($_ -match "^\[[^\]]+\]\s+([^\s]+)\s+--") {
                    Split-Path -Leaf $Matches[1]
                }
            } |
            Select-Object -First 5 -Unique
    )
    $graphQuery = (($Query, ($seedSlugs -join " ")) -join " ").Trim()

    Write-Output "=== GRAPHIFY MDS650 ==="
    & (Get-Command graphify -ErrorAction Stop).Source query $graphQuery --budget $GraphBudget
    if ($LASTEXITCODE -ne 0) {
        throw "Graphify query terminó con código $LASTEXITCODE."
    }
}
