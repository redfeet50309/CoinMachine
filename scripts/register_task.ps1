# One-shot installer: registers a Windows scheduled task that runs
# scripts/run_local.ps1 every weekday at 22:00 local time (Taipei), PLUS an
# at-logon catch-up trigger so a missed 22:00 run (PC off) executes after the
# next logon. 22:00 leaves enough buffer for TWSE/TPEx data settlement after
# the 13:30 close, and lands LINE pushes before sleep.
#
# Usage (PowerShell as your normal user):
#   .\scripts\register_task.ps1
#
# Unregister:
#   Unregister-ScheduledTask -TaskName 'CoinMachine-daily' -Confirm:$false

$ErrorActionPreference = 'Stop'

$taskName = 'CoinMachine-daily'
$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $repo 'scripts\run_local.ps1'

if (-not (Test-Path $script)) {
  throw "run_local.ps1 not found at $script"
}

$action = New-ScheduledTaskAction `
  -Execute 'powershell.exe' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$triggerDaily = New-ScheduledTaskTrigger `
  -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
  -At '22:00'

# Catch-up: if the PC was off at 22:00, a logon afterwards runs the missed job.
# run_local.ps1's guard skips weekends, same-day repeats, and any logon before
# 22:00 (so a morning logon won't pre-empt the evening fetch with stale data).
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$triggerLogon.Delay = 'PT3M'  # let network + git credentials settle after logon

$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -WakeToRun `
  -DontStopOnIdleEnd `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal `
  -UserId $env:USERNAME `
  -LogonType Interactive `
  -RunLevel Limited

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
  Write-Host "Replacing existing task: $taskName"
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask `
  -TaskName $taskName `
  -Action $action `
  -Trigger $triggerDaily, $triggerLogon `
  -Settings $settings `
  -Principal $principal `
  -Description 'CoinMachine daily indicator update + LINE notify at 22:00 (weekdays)'

Write-Host ""
Write-Host "Registered scheduled task '$taskName'"
Write-Host "  - Runs Mon-Fri at 22:00"
Write-Host "  - Catch-up: also runs at logon (3-min delay) if a 22:00 run was missed"
Write-Host "  - Wakes PC if asleep, runs on battery"
Write-Host "  - To test now:    Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  - To see log:     Get-Content data\last_run.log -Tail 30"
Write-Host "  - To unregister:  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
