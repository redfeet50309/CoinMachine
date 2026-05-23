# One-shot installer: registers a Windows scheduled task that runs
# scripts/run_local.ps1 every weekday at 22:00 local time (Taipei).
# 22:00 (vs former 23:30) leaves enough buffer for TWSE/TPEx data
# settlement after 13:30 close, and lands LINE pushes before sleep.
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

$trigger = New-ScheduledTaskTrigger `
  -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
  -At '22:00'

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
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description 'CoinMachine daily indicator update + LINE notify at 22:00 (weekdays)'

Write-Host ""
Write-Host "Registered scheduled task '$taskName'"
Write-Host "  - Runs Mon-Fri at 22:00"
Write-Host "  - Wakes PC if asleep, runs on battery"
Write-Host "  - To test now:    Start-ScheduledTask -TaskName '$taskName'"
Write-Host "  - To see log:     Get-Content data\last_run.log -Tail 30"
Write-Host "  - To unregister:  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
