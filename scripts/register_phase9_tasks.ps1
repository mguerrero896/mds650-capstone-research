# Phase 9 scheduled tasks (decision 59 activation). Idempotent.
# NY close 16:00 = 06:00 AEST next day; collector fires 08:10 local (2h+ after close),
# is XNYS-aware (no-op on non-sessions), and the post-check verifies the manifest at
# 13:30 local (the Massive sweep takes ~90-100 minutes at 5 req/min pacing).

$ErrorActionPreference = "Stop"
$repo = "C:\Users\mguer\Dev\MDS650-Capstone"
$uv = (Get-Command uv).Source

function Register-P9Task {
    param([string]$Name, [string]$Arguments, [string]$Time)
    $action = New-ScheduledTaskAction -Execute $uv -Argument $Arguments -WorkingDirectory $repo
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 5) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "registered $Name"
}

Register-P9Task -Name "MDS650_Phase9_Collector" `
    -Arguments "run python scripts/phase9_collect.py" -Time "08:10"
Register-P9Task -Name "MDS650_Phase9_PostCheck" `
    -Arguments "run python scripts/phase9_verify.py" -Time "13:30"

Get-ScheduledTask -TaskName "MDS650_Phase9_*" | Select-Object TaskName, State
