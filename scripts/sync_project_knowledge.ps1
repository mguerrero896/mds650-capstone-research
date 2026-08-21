[CmdletBinding()]
param(
    [string]$RepoRoot,
    [switch]$SkipGraphify,
    [switch]$SkipGBrain,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

$resolvedRoot = [System.IO.Path]::GetFullPath($RepoRoot)
$sourceMarker = Join-Path $resolvedRoot ".gbrain-source"
if (-not (Test-Path -LiteralPath $sourceMarker -PathType Leaf)) {
    throw "Falta .gbrain-source; se rechaza una sincronización sin fuente explícita."
}

$primarySourceId = (Get-Content -LiteralPath $sourceMarker -Raw).Trim()
if ($primarySourceId -ne "mds650-research") {
    throw "Fuente GBrain inesperada: $primarySourceId"
}

$projectHome = Join-Path $env:USERPROFILE ".mds650"
$projectConfig = Join-Path $projectHome ".gbrain\config.json"
if (-not (Test-Path -LiteralPath $projectConfig -PathType Leaf)) {
    throw "Falta el perfil GBrain aislado de MDS650: $projectConfig"
}

$codeIndexRoot = Join-Path $projectHome "code-index"
$resolvedCodeIndexRoot = [System.IO.Path]::GetFullPath($codeIndexRoot)
if (-not $resolvedCodeIndexRoot.StartsWith(
        [System.IO.Path]::GetFullPath($projectHome),
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "La ruta del índice de código salió del perfil aislado: $resolvedCodeIndexRoot"
}

$logPath = Join-Path $projectHome "knowledge-sync.log"
function Write-SyncLog {
    param([string]$Message)
    "{0:o} {1}" -f (Get-Date), $Message |
        Out-File -LiteralPath $logPath -Append -Encoding utf8
}

$mutex = [System.Threading.Mutex]::new($false, "Local\MDS650KnowledgeSync")
if (-not $mutex.WaitOne(0)) {
    Write-SyncLog "SKIP_ALREADY_RUNNING"
    Write-Output "SKIP_ALREADY_RUNNING"
    exit 0
}

try {
    Write-SyncLog "START dry_run=$DryRun skip_graphify=$SkipGraphify skip_gbrain=$SkipGBrain"
    $env:GBRAIN_HOME = $projectHome
    $env:PYTHONHASHSEED = "0"
    Set-Location -LiteralPath $resolvedRoot

    if (-not $SkipGraphify) {
        $graphify = Get-Command graphify -ErrorAction Stop
        if ($DryRun) {
            & $graphify.Source check-update .
        }
        else {
            & $graphify.Source update .
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Graphify update terminó con código $LASTEXITCODE."
        }
    }

    if (-not $SkipGBrain) {
        if (-not $DryRun) {
            New-Item -ItemType Directory -Path $resolvedCodeIndexRoot -Force | Out-Null
            foreach ($directory in @("src", "scripts", "tests")) {
                $sourcePath = Join-Path $resolvedRoot $directory
                $targetPath = Join-Path $resolvedCodeIndexRoot $directory
                New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
                & robocopy $sourcePath $targetPath `
                    *.py *.ps1 *.toml *.yaml *.yml *.sql `
                    /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP `
                    /XD __pycache__ .pytest_cache | Out-Null
                if ($LASTEXITCODE -ge 8) {
                    throw "No se pudo actualizar el espejo de código $directory (robocopy=$LASTEXITCODE)."
                }
            }

            if (-not (Test-Path -LiteralPath (Join-Path $resolvedCodeIndexRoot ".git"))) {
                & git -C $resolvedCodeIndexRoot init --quiet
                & git -C $resolvedCodeIndexRoot config user.name "MDS650 Knowledge Sync"
                & git -C $resolvedCodeIndexRoot config user.email "mds650-knowledge@local.invalid"
            }
            & git -C $resolvedCodeIndexRoot add -A
            & git -C $resolvedCodeIndexRoot diff --cached --quiet
            $diffExitCode = $LASTEXITCODE
            if ($diffExitCode -eq 1) {
                & git -C $resolvedCodeIndexRoot commit --quiet -m "sync MDS650 code"
                if ($LASTEXITCODE -ne 0) {
                    throw "No se pudo crear el checkpoint local del índice de código."
                }
            }
            elseif ($diffExitCode -ne 0) {
                throw "No se pudo verificar el checkpoint local del índice de código."
            }
        }
        elseif (-not (Test-Path -LiteralPath (Join-Path $resolvedCodeIndexRoot ".git"))) {
            throw "Falta el espejo de código aislado: $resolvedCodeIndexRoot"
        }

        $gbrain = Get-Command gbrain -ErrorAction Stop
        $sourceSpecs = @(
            [pscustomobject]@{ Id = $primarySourceId; Path = $resolvedRoot; Strategy = "markdown" },
            [pscustomobject]@{ Id = "mds650-code"; Path = $resolvedCodeIndexRoot; Strategy = "code" }
        )

        foreach ($source in $sourceSpecs) {
            if (-not (Test-Path -LiteralPath $source.Path -PathType Container)) {
                throw "Falta la ruta de la fuente $($source.Id): $($source.Path)"
            }
            $syncArgs = @(
                "sync",
                "--source", $source.Id,
                "--repo", $source.Path,
                "--strategy", $source.Strategy,
                "--no-pull",
                "--workers", "4",
                "--yes",
                "--json"
            )
            if ($DryRun) {
                $syncArgs += @("--dry-run", "--no-embed", "--no-extract")
            }

            & $gbrain.Source @syncArgs
            if ($LASTEXITCODE -ne 0) {
                throw "GBrain sync de $($source.Id) terminó con código $LASTEXITCODE."
            }
        }

        if (-not $DryRun) {
            & $gbrain.Source extract --stale
            if ($LASTEXITCODE -ne 0) {
                throw "GBrain extract --stale terminó con código $LASTEXITCODE."
            }
        }
    }
    Write-SyncLog "PASS"
}
catch {
    Write-SyncLog "FAIL type=$($_.Exception.GetType().Name) message=$($_.Exception.Message)"
    throw
}
finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
