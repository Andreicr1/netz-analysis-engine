#!/usr/bin/env pwsh
# ============================================================================
# Self-Hosted Runner Prerequisites Check — Legion
# Run: powershell -ExecutionPolicy Bypass -File infra\check-runner-prereqs.ps1
# ============================================================================

$ErrorActionPreference = "SilentlyContinue"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Self-Hosted Runner Prerequisites Check" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# ── OS ────────────────────────────────────────────────────────────────
Write-Host "[OS]" -ForegroundColor Yellow
Write-Host "  Hostname:    $env:COMPUTERNAME"
Write-Host "  OS:          $((Get-CimInstance Win32_OperatingSystem).Caption)"
Write-Host "  Version:     $((Get-CimInstance Win32_OperatingSystem).Version)"
Write-Host "  Arch:        $env:PROCESSOR_ARCHITECTURE"
Write-Host "  RAM:         $([math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)) GB"
Write-Host "  Disk Free:   $([math]::Round((Get-PSDrive C).Free / 1GB, 1)) GB on C:"

# ── GPU / CUDA ────────────────────────────────────────────────────────
Write-Host "`n[GPU / CUDA]" -ForegroundColor Yellow
$nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvsmi) {
    $smiOut = & nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits 2>&1
    Write-Host "  nvidia-smi:  OK" -ForegroundColor Green
    Write-Host "  GPU:         $smiOut"
    $cudaVer = & nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>&1
    Write-Host "  Driver:      $cudaVer"
} else {
    Write-Host "  nvidia-smi:  NOT FOUND" -ForegroundColor Red
}

$nvcc = Get-Command nvcc -ErrorAction SilentlyContinue
if ($nvcc) {
    $nvccVer = & nvcc --version 2>&1 | Select-String "release" | ForEach-Object { $_.ToString().Trim() }
    Write-Host "  nvcc:        $nvccVer" -ForegroundColor Green
} else {
    Write-Host "  nvcc:        NOT FOUND (CUDA Toolkit not in PATH)" -ForegroundColor DarkYellow
}

# ── Docker ────────────────────────────────────────────────────────────
Write-Host "`n[Docker]" -ForegroundColor Yellow
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    $dockerVer = & docker version --format "Client: {{.Client.Version}} / Server: {{.Server.Version}}" 2>&1
    Write-Host "  docker:      $dockerVer" -ForegroundColor Green

    # Check if Docker is actually running
    $dockerInfo = & docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  daemon:      RUNNING" -ForegroundColor Green
    } else {
        Write-Host "  daemon:      NOT RUNNING" -ForegroundColor Red
    }

    # Check compose
    $composeVer = & docker compose version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  compose:     $composeVer" -ForegroundColor Green
    } else {
        Write-Host "  compose:     NOT FOUND" -ForegroundColor Red
    }
} else {
    Write-Host "  docker:      NOT FOUND" -ForegroundColor Red
}

# ── WSL ───────────────────────────────────────────────────────────────
Write-Host "`n[WSL]" -ForegroundColor Yellow
$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($wsl) {
    $wslList = & wsl --list --verbose 2>&1
    Write-Host "  wsl:         AVAILABLE" -ForegroundColor Green
    $wslList | ForEach-Object { Write-Host "               $_" }
} else {
    Write-Host "  wsl:         NOT FOUND" -ForegroundColor DarkYellow
}

# ── Python ────────────────────────────────────────────────────────────
Write-Host "`n[Python]" -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pyVer = & python --version 2>&1
    Write-Host "  python:      $pyVer ($($python.Source))" -ForegroundColor Green
} else {
    Write-Host "  python:      NOT FOUND" -ForegroundColor Red
}

$pip = Get-Command pip -ErrorAction SilentlyContinue
if ($pip) {
    # Check if key packages are already installed
    $torch = & pip show torch 2>&1 | Select-String "Version"
    if ($torch) {
        Write-Host "  torch:       $($torch.ToString().Trim())" -ForegroundColor Green
    } else {
        Write-Host "  torch:       NOT INSTALLED" -ForegroundColor DarkYellow
    }
}

# ── Node / pnpm ──────────────────────────────────────────────────────
Write-Host "`n[Node.js / pnpm]" -ForegroundColor Yellow
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    Write-Host "  node:        $(& node --version)" -ForegroundColor Green
} else {
    Write-Host "  node:        NOT FOUND" -ForegroundColor Red
}

$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if ($pnpm) {
    Write-Host "  pnpm:        $(& pnpm --version)" -ForegroundColor Green
} else {
    Write-Host "  pnpm:        NOT FOUND" -ForegroundColor DarkYellow
}

# ── Git ───────────────────────────────────────────────────────────────
Write-Host "`n[Git]" -ForegroundColor Yellow
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    Write-Host "  git:         $(& git --version)" -ForegroundColor Green
} else {
    Write-Host "  git:         NOT FOUND" -ForegroundColor Red
}

# ── Ports ─────────────────────────────────────────────────────────────
Write-Host "`n[Ports]" -ForegroundColor Yellow
$port5432 = Get-NetTCPConnection -LocalPort 5432 -ErrorAction SilentlyContinue
$port6379 = Get-NetTCPConnection -LocalPort 6379 -ErrorAction SilentlyContinue
if ($port5432) {
    Write-Host "  5432 (PG):   IN USE (PID $($port5432[0].OwningProcess))" -ForegroundColor DarkYellow
} else {
    Write-Host "  5432 (PG):   FREE" -ForegroundColor Green
}
if ($port6379) {
    Write-Host "  6379 (Redis):IN USE (PID $($port6379[0].OwningProcess))" -ForegroundColor DarkYellow
} else {
    Write-Host "  6379 (Redis):FREE" -ForegroundColor Green
}

# ── Summary ───────────────────────────────────────────────────────────
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  VERDICT" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$blockers = @()
if (-not $docker) { $blockers += "Docker not installed" }
if (-not $python) { $blockers += "Python not found" }
if (-not $git) { $blockers += "Git not found" }
if (-not $nvsmi) { $blockers += "NVIDIA driver not found (nvidia-smi)" }

if ($blockers.Count -eq 0) {
    Write-Host "`n  READY — all prerequisites met" -ForegroundColor Green
    Write-Host "  Next: run the self-hosted runner setup script`n"
} else {
    Write-Host "`n  BLOCKERS:" -ForegroundColor Red
    $blockers | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    Write-Host ""
}
