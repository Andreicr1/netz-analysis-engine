#!/usr/bin/env pwsh
# ============================================================================
# GitHub Actions Self-Hosted Runner Setup — Legion
# Run: powershell -ExecutionPolicy Bypass -File infra\setup-runner.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

$RUNNER_DIR = "D:\actions-runner"
$REPO_URL = "https://github.com/Andreicr1/netz-analysis-engine"
$TOKEN = "BSBWDSY2KVEI6KSMGUGJ2Q3JYCHTA"
$LABELS = "self-hosted,windows,x64,gpu"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  GitHub Actions Runner Setup" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# ── Step 1: Create runner directory ───────────────────────────────────
if (Test-Path $RUNNER_DIR) {
    Write-Host "[1/5] Runner directory exists at $RUNNER_DIR" -ForegroundColor Yellow
} else {
    Write-Host "[1/5] Creating $RUNNER_DIR..." -ForegroundColor Green
    New-Item -ItemType Directory -Path $RUNNER_DIR -Force | Out-Null
}

# ── Step 2: Download runner ──────────────────────────────────────────
$runnerZip = "$RUNNER_DIR\actions-runner-win-x64.zip"
$runnerExe = "$RUNNER_DIR\config.cmd"

if (Test-Path $runnerExe) {
    Write-Host "[2/5] Runner already downloaded" -ForegroundColor Yellow
} else {
    Write-Host "[2/5] Downloading runner v2.332.0..." -ForegroundColor Green
    $runnerVersion = "2.332.0"
    $downloadUrl = "https://github.com/actions/runner/releases/download/v${runnerVersion}/actions-runner-win-x64-${runnerVersion}.zip"
    Write-Host "  URL: $downloadUrl"

    Invoke-WebRequest -Uri $downloadUrl -OutFile $runnerZip -UseBasicParsing
    Write-Host "  Extracting..." -ForegroundColor Green
    Expand-Archive -Path $runnerZip -DestinationPath $RUNNER_DIR -Force
    Remove-Item $runnerZip -Force
}

# ── Step 3: Configure runner ─────────────────────────────────────────
Write-Host "[3/5] Configuring runner..." -ForegroundColor Green
Write-Host "  Repo:   $REPO_URL"
Write-Host "  Labels: $LABELS"

Push-Location $RUNNER_DIR
& .\config.cmd --url $REPO_URL --token $TOKEN --name "legion-gpu" --labels $LABELS --work "_work" --replace --unattended
Pop-Location

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n  ERROR: Runner configuration failed!" -ForegroundColor Red
    Write-Host "  Token may have expired (valid 1 hour). Re-run:" -ForegroundColor Red
    Write-Host "    gh api -X POST repos/Andreicr1/netz-analysis-engine/actions/runners/registration-token --jq '.token'" -ForegroundColor Yellow
    exit 1
}

# ── Step 4: Install as Windows Service ───────────────────────────────
Write-Host "[4/5] Installing as Windows service..." -ForegroundColor Green
& "$RUNNER_DIR\svc.cmd" install
& "$RUNNER_DIR\svc.cmd" start

# ── Step 5: Verify ───────────────────────────────────────────────────
Write-Host "[5/5] Verifying..." -ForegroundColor Green
Start-Sleep -Seconds 3
$status = & "$RUNNER_DIR\svc.cmd" status 2>&1
Write-Host "  Service status: $status"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  DONE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "`n  Runner 'legion-gpu' registered with labels: $LABELS"
Write-Host "  Running as Windows service (auto-start on boot)"
Write-Host "  Verify at: $REPO_URL/settings/actions/runners`n"
