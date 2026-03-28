#Requires -Version 5.1
<#
.SYNOPSIS
    AGI Agent - Local Development Launcher (no Docker required)

.DESCRIPTION
    Starts the AGI Agent backend and frontend locally without Docker.
    Uses SQLite for storage and in-memory fallback for Redis — zero
    external services required. Just Python 3.11+ and Node.js 18+.

.PARAMETER Action
    start  | stop | restart | status | logs-backend | logs-frontend | open

.PARAMETER SkipInstall
    Skip dependency installation (faster startup if already installed)

.PARAMETER BackendOnly
    Start only the FastAPI backend

.PARAMETER FrontendOnly
    Start only the Next.js frontend

.EXAMPLE
    .\run-local.ps1                        # First-time setup + start everything
    .\run-local.ps1 -Action start          # Start all services
    .\run-local.ps1 -Action stop           # Stop all services
    .\run-local.ps1 -Action status         # Check what's running
    .\run-local.ps1 -SkipInstall           # Start without reinstalling deps
    .\run-local.ps1 -BackendOnly           # API server only

.NOTES
    Ports: Backend=8000  Frontend=3000
#>

[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "restart", "status", "logs-backend", "logs-frontend", "open", "install")]
    [string]$Action = "start",
    [switch]$SkipInstall,
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Paths ─────────────────────────────────────────────────────────────────────
$Script:ROOT       = Split-Path -Parent $MyInvocation.PSCommandPath
$Script:BACKEND    = Join-Path $Script:ROOT "backend"
$Script:FRONTEND   = Join-Path $Script:ROOT "frontend"
$Script:VENV       = Join-Path $Script:BACKEND ".venv"
$Script:PID_FILE   = Join-Path $Script:ROOT ".local-pids"
$Script:LOG_DIR    = Join-Path $Script:ROOT ".local-logs"
$Script:BE_LOG     = Join-Path $Script:LOG_DIR "backend.log"
$Script:FE_LOG     = Join-Path $Script:LOG_DIR "frontend.log"

# ── Colors ────────────────────────────────────────────────────────────────────
$Script:ColorOK    = if ($Host.UI.SupportsVirtualTerminal) { "`e[92m" } else { "" }
$Script:ColorWarn  = if ($Host.UI.SupportsVirtualTerminal) { "`e[93m" } else { "" }
$Script:ColorErr   = if ($Host.UI.SupportsVirtualTerminal) { "`e[91m" } else { "" }
$Script:ColorInfo  = if ($Host.UI.SupportsVirtualTerminal) { "`e[96m" } else { "" }
$Script:ColorDim   = if ($Host.UI.SupportsVirtualTerminal) { "`e[2m"  } else { "" }
$Script:ColorBold  = if ($Host.UI.SupportsVirtualTerminal) { "`e[1m"  } else { "" }
$Script:ColorReset = if ($Host.UI.SupportsVirtualTerminal) { "`e[0m"  } else { "" }
$Script:ColorPurp  = if ($Host.UI.SupportsVirtualTerminal) { "`e[95m" } else { "" }

function ok   { param([string]$m) Write-Host "  $($Script:ColorOK)✔$($Script:ColorReset) $m" }
function warn { param([string]$m) Write-Host "  $($Script:ColorWarn)⚠$($Script:ColorReset) $m" }
function err  { param([string]$m) Write-Host "  $($Script:ColorErr)✖$($Script:ColorReset) $m" }
function info { param([string]$m) Write-Host "  $($Script:ColorInfo)›$($Script:ColorReset) $m" }
function dim  { param([string]$m) Write-Host "  $($Script:ColorDim)$m$($Script:ColorReset)" }
function section { param([string]$t) Write-Host ""; Write-Host "$($Script:ColorBold)$($Script:ColorPurp)  ▸ $t$($Script:ColorReset)"; Write-Host "$($Script:ColorDim)  $('─' * 50)$($Script:ColorReset)" }

function Write-Banner {
    Write-Host ""
    Write-Host "$($Script:ColorPurp)$($Script:ColorBold)  ╔════════════════════════════════════════════╗$($Script:ColorReset)"
    Write-Host "$($Script:ColorPurp)$($Script:ColorBold)  ║$($Script:ColorReset)$($Script:ColorBold)     AGI Agent · Local Dev Launcher         $($Script:ColorPurp)║$($Script:ColorReset)"
    Write-Host "$($Script:ColorPurp)$($Script:ColorBold)  ║$($Script:ColorReset)$($Script:ColorDim)     No Docker · SQLite · In-Memory Redis    $($Script:ColorPurp)$($Script:ColorBold)║$($Script:ColorReset)"
    Write-Host "$($Script:ColorPurp)$($Script:ColorBold)  ╚════════════════════════════════════════════╝$($Script:ColorReset)"
    Write-Host ""
}

# ── Prerequisite checks ───────────────────────────────────────────────────────
function Test-Prerequisites {
    section "Checking Prerequisites"
    $ok = $true

    # Python
    try {
        $pyVer = python --version 2>&1
        if ($pyVer -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
                warn "Python $major.$minor found — 3.11+ recommended"
            } else {
                ok "Python $major.$minor"
            }
        }
    } catch {
        err "Python not found. Install from https://python.org (3.11+)"
        $ok = $false
    }

    # Node
    if (-not $BackendOnly) {
        try {
            $nodeVer = node --version 2>&1
            if ($nodeVer -match "v(\d+)") {
                $major = [int]$Matches[1]
                if ($major -lt 18) { warn "Node $nodeVer found — v18+ recommended" }
                else { ok "Node $nodeVer" }
            }
        } catch {
            err "Node.js not found. Install from https://nodejs.org (v18+)"
            $ok = $false
        }
    }

    return $ok
}

# ── Environment setup ─────────────────────────────────────────────────────────
function Initialize-Environment {
    section "Environment Setup"

    $envFile = Join-Path $Script:BACKEND ".env"
    $envExample = Join-Path $Script:ROOT ".env.local.example"

    if (-not (Test-Path $envFile)) {
        if (Test-Path $envExample) {
            Copy-Item $envExample $envFile
            ok "Created backend/.env from .env.local.example"
        } else {
            warn "No .env found — backend will use defaults"
            return
        }
    } else {
        ok "backend/.env already exists"
    }

    # Check for OpenRouter key
    $content = Get-Content $envFile -Raw
    if ($content -match "OPENROUTER_API_KEY=sk-or-v1-your-key-here" -or
        $content -notmatch "OPENROUTER_API_KEY=sk-or-") {
        Write-Host ""
        warn "OPENROUTER_API_KEY is not set in backend/.env"
        info "Get a free key at: $($Script:ColorInfo)https://openrouter.ai/keys$($Script:ColorReset)"
        info "Free models available — no payment needed to start!"
        Write-Host ""
        $edit = Read-Host "  Open backend/.env in editor now? [Y/n]"
        if ($edit -ne "n" -and $edit -ne "N") {
            if (Get-Command "code" -ErrorAction SilentlyContinue) { code $envFile }
            elseif (Get-Command "notepad" -ErrorAction SilentlyContinue) { Start-Process notepad $envFile -Wait }
        }
    }
}

# ── Python venv + dependencies ────────────────────────────────────────────────
function Install-BackendDeps {
    section "Backend Dependencies"

    # Create venv if missing
    if (-not (Test-Path $Script:VENV)) {
        info "Creating Python virtual environment..."
        python -m venv $Script:VENV
        ok "Virtual environment created at backend/.venv"
    } else {
        ok "Virtual environment exists"
    }

    $pip = Join-Path $Script:VENV "Scripts\pip.exe"
    if (-not (Test-Path $pip)) { $pip = Join-Path $Script:VENV "bin/pip" }

    info "Installing Python packages..."
    $req = Join-Path $Script:BACKEND "requirements.txt"
    & $pip install -r $req -q --disable-pip-version-check 2>&1 | Out-Null
    ok "Python packages installed"
}

# ── Node dependencies ─────────────────────────────────────────────────────────
function Install-FrontendDeps {
    section "Frontend Dependencies"

    $nm = Join-Path $Script:FRONTEND "node_modules"
    if (-not (Test-Path $nm)) {
        info "Installing npm packages (first run, may take a minute)..."
        Push-Location $Script:FRONTEND
        npm install --silent 2>&1 | Out-Null
        Pop-Location
        ok "npm packages installed"
    } else {
        ok "node_modules already present"
    }
}

# ── PID management ────────────────────────────────────────────────────────────
function Save-Pids {
    param([int]$BackendPid, [int]$FrontendPid)
    @{ backend = $BackendPid; frontend = $FrontendPid } | ConvertTo-Json | Set-Content $Script:PID_FILE
}

function Get-SavedPids {
    if (Test-Path $Script:PID_FILE) {
        return Get-Content $Script:PID_FILE | ConvertFrom-Json
    }
    return $null
}

function Stop-Process-Safe {
    param([int]$Pid)
    try {
        $p = Get-Process -Id $Pid -ErrorAction SilentlyContinue
        if ($p) { $p.Kill(); $p.WaitForExit(3000) }
    } catch {}
}

# ── Start services ────────────────────────────────────────────────────────────
function Start-Backend {
    $null = New-Item -ItemType Directory -Path $Script:LOG_DIR -Force

    $python  = Join-Path $Script:VENV "Scripts\python.exe"
    if (-not (Test-Path $python)) { $python = Join-Path $Script:VENV "bin/python" }

    info "Starting FastAPI backend on http://localhost:8000 ..."
    $proc = Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload" `
        -WorkingDirectory $Script:BACKEND `
        -RedirectStandardOutput $Script:BE_LOG `
        -RedirectStandardError  $Script:BE_LOG `
        -PassThru `
        -WindowStyle Hidden
    return $proc.Id
}

function Start-Frontend {
    $null = New-Item -ItemType Directory -Path $Script:LOG_DIR -Force

    info "Starting Next.js frontend on http://localhost:3000 ..."
    $proc = Start-Process -FilePath "npm" `
        -ArgumentList "run", "dev" `
        -WorkingDirectory $Script:FRONTEND `
        -RedirectStandardOutput $Script:FE_LOG `
        -RedirectStandardError  $Script:FE_LOG `
        -PassThru `
        -WindowStyle Hidden
    return $proc.Id
}

function Wait-ForPort {
    param([int]$Port, [string]$Name, [int]$TimeoutSec = 60)
    $spinner = @('⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏')
    $elapsed = 0; $i = 0
    while ($elapsed -lt $TimeoutSec) {
        $conn = Test-NetConnection -ComputerName localhost -Port $Port `
            -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null
        if ($conn) {
            Write-Host "`r  $($Script:ColorOK)✔$($Script:ColorReset) $Name is ready on :$Port               "
            return $true
        }
        $spin = $spinner[$i % $spinner.Length]
        Write-Host "`r  $($Script:ColorWarn)$spin$($Script:ColorReset) Waiting for $Name... ($elapsed/$TimeoutSec s)" -NoNewline
        Start-Sleep -Seconds 2; $elapsed += 2; $i++
    }
    Write-Host "`r  $($Script:ColorErr)✖$($Script:ColorReset) $Name did not start within ${TimeoutSec}s         "
    return $false
}

# ── Actions ───────────────────────────────────────────────────────────────────
function Invoke-Start {
    $bePid = 0; $fePid = 0

    if (-not $FrontendOnly) {
        $bePid = Start-Backend
        $beReady = Wait-ForPort -Port 8000 -Name "Backend API" -TimeoutSec 45
        if (-not $beReady) {
            warn "Backend slow to start — check .local-logs/backend.log"
        }
    }

    if (-not $BackendOnly) {
        $fePid = Start-Frontend
        $feReady = Wait-ForPort -Port 3000 -Name "Frontend UI" -TimeoutSec 90
        if (-not $feReady) {
            warn "Frontend slow to start — check .local-logs/frontend.log"
        }
    }

    Save-Pids -BackendPid $bePid -FrontendPid $fePid
}

function Invoke-Stop {
    section "Stopping Services"
    $pids = Get-SavedPids
    if ($null -eq $pids) { warn "No running services found (.local-pids missing)"; return }

    if ($pids.backend -gt 0) {
        Stop-Process-Safe -Pid $pids.backend
        ok "Backend stopped (PID $($pids.backend))"
    }
    if ($pids.frontend -gt 0) {
        Stop-Process-Safe -Pid $pids.frontend
        ok "Frontend stopped (PID $($pids.frontend))"
    }

    # Also kill any orphaned uvicorn / next processes
    Get-Process -Name "python","node" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "uvicorn|next" } |
        ForEach-Object { $_.Kill() }

    if (Test-Path $Script:PID_FILE) { Remove-Item $Script:PID_FILE -Force }
    ok "All services stopped"
}

function Invoke-Status {
    section "Service Status"
    $ports = @{ "Backend API" = 8000; "Frontend UI" = 3000 }
    foreach ($svc in $ports.Keys) {
        $port = $ports[$svc]
        $conn = Test-NetConnection -ComputerName localhost -Port $port `
            -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null
        $label = if ($conn) { "$($Script:ColorOK)● RUNNING$($Script:ColorReset)" } else { "$($Script:ColorDim)○ stopped$($Script:ColorReset)" }
        $url   = if ($conn) { "$($Script:ColorInfo)http://localhost:$port$($Script:ColorReset)" } else { "http://localhost:$port" }
        Write-Host "  $label  $($svc.PadRight(14)) $url"
    }
}

function Invoke-OpenBrowser {
    Start-Process "http://localhost:3000"
}

function Show-Completion {
    Write-Host ""
    Write-Host "$($Script:ColorOK)$($Script:ColorBold)  ╔══════════════════════════════════════════════╗$($Script:ColorReset)"
    Write-Host "$($Script:ColorOK)$($Script:ColorBold)  ║$($Script:ColorReset)$($Script:ColorBold)    ✨  AGI Agent Running Locally           $($Script:ColorOK)║$($Script:ColorReset)"
    Write-Host "$($Script:ColorOK)$($Script:ColorBold)  ╠══════════════════════════════════════════════╣$($Script:ColorReset)"
    Write-Host "$($Script:ColorOK)$($Script:ColorBold)  ║$($Script:ColorReset)  $($Script:ColorDim)Frontend:$($Script:ColorReset)  $($Script:ColorInfo)http://localhost:3000$($Script:ColorReset)            $($Script:ColorOK)$($Script:ColorBold)║$($Script:ColorReset)"
    Write-Host "$($Script:ColorOK)$($Script:ColorBold)  ║$($Script:ColorReset)  $($Script:ColorDim)Backend: $($Script:ColorReset)  $($Script:ColorInfo)http://localhost:8000$($Script:ColorReset)            $($Script:ColorOK)$($Script:ColorBold)║$($Script:ColorReset)"
    Write-Host "$($Script:ColorOK)$($Script:ColorBold)  ║$($Script:ColorReset)  $($Script:ColorDim)API Docs:$($Script:ColorReset)  $($Script:ColorInfo)http://localhost:8000/docs$($Script:ColorReset)       $($Script:ColorOK)$($Script:ColorBold)║$($Script:ColorReset)"
    Write-Host "$($Script:ColorOK)$($Script:ColorBold)  ║$($Script:ColorReset)  $($Script:ColorDim)Storage: $($Script:ColorReset)  SQLite + in-memory (no Docker!)         $($Script:ColorOK)$($Script:ColorBold)║$($Script:ColorReset)"
    Write-Host "$($Script:ColorOK)$($Script:ColorBold)  ╚══════════════════════════════════════════════╝$($Script:ColorReset)"
    Write-Host ""
    Write-Host "  $($Script:ColorDim)Logs:$($Script:ColorReset)  .local-logs\backend.log   .local-logs\frontend.log"
    Write-Host "  $($Script:ColorDim)Stop:$($Script:ColorReset)  $($Script:ColorWarn).\run-local.ps1 -Action stop$($Script:ColorReset)"
    Write-Host ""

    $open = Read-Host "  Open browser now? [Y/n]"
    if ($open -ne "n" -and $open -ne "N") { Invoke-OpenBrowser }
}

# ── Main ──────────────────────────────────────────────────────────────────────
function Main {
    Write-Banner

    switch ($Action) {
        "stop"           { Invoke-Stop; return }
        "status"         { Invoke-Status; return }
        "open"           { Invoke-OpenBrowser; return }
        "logs-backend"   { if (Test-Path $Script:BE_LOG) { Get-Content $Script:BE_LOG -Tail 50 -Wait } else { warn "No backend log yet" }; return }
        "logs-frontend"  { if (Test-Path $Script:FE_LOG) { Get-Content $Script:FE_LOG -Tail 50 -Wait } else { warn "No frontend log yet" }; return }
        "restart"        { Invoke-Stop; Start-Sleep 2 }
    }

    if (-not (Test-Prerequisites)) { exit 1 }

    Initialize-Environment

    if (-not $SkipInstall) {
        if (-not $FrontendOnly) { Install-BackendDeps }
        if (-not $BackendOnly)  { Install-FrontendDeps }
    }

    section "Starting Services"
    Invoke-Start
    Show-Completion
}

Main
