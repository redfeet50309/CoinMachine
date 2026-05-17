# Local daily-update runner for Windows Task Scheduler.
# TWSE / TPEx geo-block GitHub Actions runners (US IPs), so cron runs locally
# from a Taiwan IP. This script fetches data, then pushes the JSON to the repo.
#
# Setup:
#   1. Make sure 'git' and 'python' are on PATH
#   2. Make sure 'gh auth setup-git' has been run (so push works without prompt)
#   3. Register with Task Scheduler (see scripts/register_task.ps1)

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

Write-Log '--- run start ---'

try {
  Write-Log 'git pull --rebase'
  git pull --rebase 2>&1 | ForEach-Object { Write-Log $_ }

  Write-Log 'python build_dataset.py'
  $py = (Get-Command python).Source
  & $py scripts\build_dataset.py 2>&1 | ForEach-Object { Write-Log $_ }
  if ($LASTEXITCODE -ne 0) { throw "build_dataset.py exited with $LASTEXITCODE" }

  Write-Log 'git add data/'
  git add data/ 2>&1 | ForEach-Object { Write-Log $_ }

  $diff = git diff --cached --quiet
  if ($LASTEXITCODE -eq 0) {
    Write-Log 'no data changes; skipping push'
  } else {
    $date = (Get-Date).ToString('yyyy-MM-dd')
    Write-Log "git commit + push: $date"
    git commit -m "data: $date daily update" 2>&1 | ForEach-Object { Write-Log $_ }
    git push 2>&1 | ForEach-Object { Write-Log $_ }
  }

  Write-Log '--- run ok ---'
  exit 0
} catch {
  Write-Log "ERROR: $_"
  Write-Log '--- run failed ---'
  exit 1
}
