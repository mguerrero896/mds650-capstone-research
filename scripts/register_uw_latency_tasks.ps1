# Gate 5.3: register the UW latency scheduled tasks (idempotent).
# Times are LOCAL (AEST, UTC+10): the 09:30-16:05 NY session runs 23:30-06:05 local.
# The collector itself is XNYS-calendar aware and exits when there is no session,
# so weekend/holiday firings are harmless no-ops. All tasks StartWhenAvailable.

$ErrorActionPreference = "Stop"
$repo = "C:\Users\mguer\Dev\MDS650-Capstone"
$uv = (Get-Command uv).Source

function Register-MDSTask {
    param([string]$Name, [string]$Arguments, [string]$Time, [string]$Interval = $null)
    $action = New-ScheduledTaskAction -Execute $uv -Argument $Arguments -WorkingDirectory $repo
    if ($Interval) {
        $trigger = New-ScheduledTaskTrigger -Once -At $Time -RepetitionInterval (New-TimeSpan -Minutes $Interval) -RepetitionDuration (New-TimeSpan -Hours 7)
    } else {
        $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 8) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "registered $Name"
}

Register-MDSTask -Name "MDS650_UW_LatencyCollector" `
    -Arguments "run python scripts/uw_latency_collector.py" -Time "23:20"
Register-MDSTask -Name "MDS650_UW_LatencyWatchdog" `
    -Arguments "run python scripts/uw_latency_verify.py --watchdog" -Time "23:40" -Interval 30
Register-MDSTask -Name "MDS650_UW_LatencyPostCheck" `
    -Arguments "run python scripts/uw_latency_verify.py" -Time "06:20"
Register-MDSTask -Name "MDS650_UW_LatencyReconcile" `
    -Arguments "run python scripts/uw_latency_reconcile.py" -Time "07:00"

Get-ScheduledTask -TaskName "MDS650_UW_*" | Select-Object TaskName, State
