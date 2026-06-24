# Local daily-update runner for Windows Task Scheduler.
# TWSE / TPEx geo-block GitHub Actions runners (US IPs), so cron runs locally
# from a Taiwan IP. This script fetches data, then pushes the JSON to the repo.
#
# Setup:
#   1. Make sure 'git' and 'python' are on PATH
#   2. Make sure 'gh auth setup-git' has been run (so push works without prompt)
#   3. Register with Task Scheduler:  .\scripts\register_task.ps1
#
# Pass -Force to bypass the schedule guard (manual catch-up at any time / day).

param([switch]$Force)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$logFile = Join-Path $repo 'data\last_run.log'
$logDir = Split-Path -Parent $logFile
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

function Write-Log($msg) {
  $ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  $line = "[$ts] $msg"
  Write-Host $line
  Add-Content -Path $logFile -Value $line -Encoding utf8
}

# Run a native exe via Start-Process so PowerShell does not wrap stderr lines
# as ErrorRecord objects (which would trip ErrorActionPreference=Stop on the
# very first INFO log line from Python).
function Invoke-Native($exe, $argList, $label) {
  $tmpOut = Join-Path $env:TEMP "cm_$([guid]::NewGuid().ToString('N')).out"
  $tmpErr = Join-Path $env:TEMP "cm_$([guid]::NewGuid().ToString('N')).err"
  try {
    $proc = Start-Process -FilePath $exe -ArgumentList $argList `
      -NoNewWindow -Wait -PassThru `
      -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
    foreach ($f in @($tmpOut, $tmpErr)) {
      if (Test-Path $f) {
        Get-Content $f -Encoding utf8 -ErrorAction SilentlyContinue |
          Where-Object { $_ -ne $null -and $_.Trim() -ne '' } |
          ForEach-Object { Write-Log $_ }
      }
    }
    if ($proc.ExitCode -ne 0) {
      throw "$label exited with code $($proc.ExitCode)"
    }
    return $proc.ExitCode
  } finally {
    Remove-Item $tmpOut, $tmpErr -ErrorAction SilentlyContinue
  }
}

$marker = Join-Path $repo 'data\last_success_date.txt'

# The most recent trading day whose data should be settled & fetchable *now*.
# This is the date a run is responsible for having captured.
#   - Before 22:00 on a weekday, today's bar isn't settled yet -> use yesterday
#     (preserves the old "don't fetch an unsettled same-day bar" protection).
#   - Weekends (and a rolled-back Sat/Sun) step back to the preceding Friday.
$now = Get-Date
$target = $now.Date
if ($now.Hour -lt 22) { $target = $target.AddDays(-1) }
while (($target.DayOfWeek -eq 'Saturday') -or ($target.DayOfWeek -eq 'Sunday')) {
  $target = $target.AddDays(-1)
}
$targetStr = $target.ToString('yyyy-MM-dd')

# --- Schedule guard (bypass with -Force) ---
# Triggered by BOTH the 22:00 weekly schedule AND an at-logon catch-up trigger.
# The guard is DATA-aware, not calendar-crude: skip only when the most recent
# settled trading day is already captured. This lets a missed Friday run be
# recovered on a weekend, and a missed weekday run be recovered after midnight
# (cases the old blanket weekend / before-22:00 skips wrongly blocked) while
# still never fetching an unsettled same-day bar before 22:00. The marker holds
# the trading date captured ($targetStr), not the calendar run date, so the
# string compare is a correct date compare (ISO dates sort lexically).
if (-not $Force) {
  $captured = if (Test-Path $marker) { (Get-Content $marker -Raw).Trim() } else { '' }
  if ($captured -ge $targetStr) {
    Write-Log "skip: latest settled trading day already captured (have $captured, need $targetStr)"
    exit 0
  }
  Write-Log "run: trading day $targetStr not yet captured (have '$captured')"
}

Write-Log '--- run start ---'

try {
  # Auto-stash any unstaged changes so git pull --rebase can proceed.
  # No pop: build_dataset.py overwrites data/ next anyway. Recover manually
  # with `git stash list` + `git stash apply` if needed.
  $dirty = & git status --porcelain
  if (-not [string]::IsNullOrWhiteSpace($dirty)) {
    $stamp = (Get-Date).ToString('yyyy-MM-dd-HHmm')
    Write-Log "working tree dirty; stashing as auto-stash-$stamp"
    Invoke-Native -exe 'git' -argList @('stash', 'push', '-u', '-m', "auto-stash-$stamp") -label 'git stash' | Out-Null
  }

  Write-Log 'git pull --rebase'
  Invoke-Native -exe 'git' -argList @('pull', '--rebase') -label 'git pull' | Out-Null

  # Use py.exe launcher to find the system Python 3.11 (with pandas installed).
  # Plain `python` on PATH may resolve to a sandboxed venv that lacks deps.
  # UTF-8 IO so build_dataset's internal LINE-notify logging is safe on cp950
  $env:PYTHONIOENCODING = 'utf-8'
  Write-Log 'py -3 -X utf8 scripts/build_dataset.py'
  Invoke-Native -exe 'py' -argList @('-3', '-X', 'utf8', 'scripts\build_dataset.py') -label 'build_dataset.py' | Out-Null

  Write-Log 'git add data/'
  Invoke-Native -exe 'git' -argList @('add', 'data/') -label 'git add' | Out-Null

  # Use plumbing porcelain: rev-parse + diff-index instead of `diff --cached --quiet`
  # which exits non-zero (= "there are changes") and would trip our error trap.
  $stagedDiff = & git diff --cached --name-only
  if ([string]::IsNullOrWhiteSpace($stagedDiff)) {
    Write-Log 'no data changes; skipping push'
  } else {
    $date = (Get-Date).ToString('yyyy-MM-dd')
    Write-Log "git commit + push: $date"
    # No spaces in commit message — Start-Process doesn't quote multi-word args
    # reliably for native exes, so we use hyphens to keep it as a single token.
    Invoke-Native -exe 'git' -argList @('commit', '-m', "data:$date-daily-update") -label 'git commit' | Out-Null
    Invoke-Native -exe 'git' -argList @('push') -label 'git push' | Out-Null
  }

  # NOTE: LINE push is NOT called here — build_dataset.py already invokes
  # notify (send_daily_summary) at the end of its run. Adding a second call
  # here pushed the message twice (seen 2026-05-31 17:56). One push per build.

  # Record the trading date we captured ($targetStr, NOT the run date) so the
  # data-aware guard skips redundant re-runs yet still allows recovering an
  # older missed day. Written only on success -- a failed run retries.
  Set-Content -Path $marker -Value $targetStr -Encoding utf8 -NoNewline

  Write-Log '--- run ok ---'
  exit 0
} catch {
  Write-Log "ERROR: $_"
  if ($_.ScriptStackTrace) { Write-Log "STACK: $($_.ScriptStackTrace)" }
  Write-Log '--- run failed ---'
  exit 1
}
