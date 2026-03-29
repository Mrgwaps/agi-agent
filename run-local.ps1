#Requires -Version 5.1
<#
.SYNOPSIS
    AGI Agent - Local Development Launcher (no Docker required)

.DESCRIPTION
    Starts the AGI Agent backend and frontend locally without Docker.
    Uses SQLite + in-memory fallback - zero external services needed.
    Requires Python 3.11+ and Node 18+ to be in PATH (can live on any drive).
    All data files (venv, SQLite, logs, workspace) are stored on the drive
    where this script lives, keeping your system drive free.

.PARAMETER Action
    start | stop | restart | status | logs-backend | logs-frontend | open | install

.PARAMETER SkipInstall
    Skip dependency installation (faster restart if deps already installed)

.PARAMETER BackendOnly
    Start only the FastAPI backend (port 8000)

.PARAMETER FrontendOnly
    Start only the Next.js frontend (port 3000)

.EXAMPLE
    .\run-local.ps1                         # First-time setup + start everything
    .\run-local.ps1 -Action stop            # Stop all services
    .\run-local.ps1 -Action status          # Check running ports
    .\run-local.ps1 -SkipInstall            # Fast restart (deps already installed)
    .\run-local.ps1 -BackendOnly            # API only, no UI
    .\run-local.ps1 -Action logs-backend    # Tail backend log

.NOTES
    Ports  : Backend=8000  Frontend=3000
    Data   : Stored next to this script (SQLite, venv, logs)
    Python : Looked up via PATH - install location does not matter
#>

[CmdletBinding()]
param(
    [ValidateSet("start","stop","restart","status","logs-backend","logs-frontend","open","install")]
    [string]$Action = "start",
    [switch]$SkipInstall,
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Paths  (all data goes to the drive where this script lives)
# $PSScriptRoot is always the directory containing the .ps1 file, regardless
# of where the caller's working directory is or how the path was specified.
# ---------------------------------------------------------------------------
$Script:ROOT      = $PSScriptRoot
$Script:BACKEND   = Join-Path $Script:ROOT "backend"
$Script:FRONTEND  = Join-Path $Script:ROOT "frontend"
$Script:VENV      = Join-Path $Script:BACKEND ".venv"
$Script:LOG_DIR   = Join-Path $Script:ROOT ".local-logs"
# Start-Process requires stdout and stderr to be DIFFERENT files on Windows
$Script:BE_OUT    = Join-Path $Script:LOG_DIR "backend-out.log"
$Script:BE_ERR    = Join-Path $Script:LOG_DIR "backend-err.log"
$Script:FE_OUT    = Join-Path $Script:LOG_DIR "frontend-out.log"
$Script:FE_ERR    = Join-Path $Script:LOG_DIR "frontend-err.log"
$Script:BE_PID    = Join-Path $Script:ROOT ".be.pid"
$Script:FE_PID    = Join-Path $Script:ROOT ".fe.pid"

# ---------------------------------------------------------------------------
# Colors  (use [char]27 for ESC - works on PowerShell 5.1 and 7+)
# ---------------------------------------------------------------------------
$ESC = [char]27
if ($Host.UI.SupportsVirtualTerminal) {
    $CG = "$ESC[92m"   # green
    $CY = "$ESC[93m"   # yellow
    $CR = "$ESC[91m"   # red
    $CC = "$ESC[96m"   # cyan
    $CM = "$ESC[95m"   # magenta
    $CD = "$ESC[2m"    # dim
    $CB = "$ESC[1m"    # bold
    $CX = "$ESC[0m"    # reset
} else {
    $CG = ""; $CY = ""; $CR = ""; $CC = ""; $CM = ""; $CD = ""; $CB = ""; $CX = ""
}

function ok      { param([string]$m) Write-Host "  $($CG)OK$($CX)  $m" }
function warn    { param([string]$m) Write-Host "  $($CY)>>$($CX)  $m" }
function err     { param([string]$m) Write-Host "  $($CR)!!$($CX)  $m" }
function info    { param([string]$m) Write-Host "  $($CC)->$($CX)  $m" }
function dim     { param([string]$m) Write-Host "  $($CD)$m$($CX)" }
function section {
    param([string]$t)
    Write-Host ""
    Write-Host "$($CB)$($CM)  >> $t$($CX)"
    Write-Host "$($CD)  $('-' * 52)$($CX)"
}

function Write-Banner {
    Write-Host ""
    Write-Host "$($CM)$($CB)  +------------------------------------------+$($CX)"
    Write-Host "$($CM)$($CB)  |$($CX)$($CB)   AGI Agent  -  Local Dev Launcher      $($CM)|$($CX)"
    Write-Host "$($CM)$($CB)  |$($CX)$($CD)   No Docker | SQLite | In-Memory Redis  $($CM)$($CB)|$($CX)"
    Write-Host "$($CM)$($CB)  +------------------------------------------+$($CX)"
    Write-Host ""
    dim "  Script root : $($Script:ROOT)"
    dim "  Backend     : $($Script:BACKEND)"
    dim "  Frontend    : $($Script:FRONTEND)"
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Find Python / Node on PATH (works regardless of install drive)
# ---------------------------------------------------------------------------
function Get-PythonExe {
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $out = & $cmd --version 2>&1
            if ($out -match "Python \d") { return $cmd }
        } catch {}
    }
    return $null
}

function Get-NodeExe {
    try {
        $out = node --version 2>&1
        if ($out -match "v\d") { return "node" }
    } catch {}
    return $null
}

function Get-VenvPython {
    $candidates = @(
        (Join-Path $Script:VENV "Scripts\python.exe"),
        (Join-Path $Script:VENV "Scripts\python"),
        (Join-Path $Script:VENV "bin\python")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Get-VenvPip {
    $candidates = @(
        (Join-Path $Script:VENV "Scripts\pip.exe"),
        (Join-Path $Script:VENV "Scripts\pip"),
        (Join-Path $Script:VENV "bin\pip")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Get-VenvUvicorn {
    $candidates = @(
        (Join-Path $Script:VENV "Scripts\uvicorn.exe"),
        (Join-Path $Script:VENV "Scripts\uvicorn"),
        (Join-Path $Script:VENV "bin\uvicorn")
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    # Fallback: run via python -m uvicorn
    return $null
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
function Test-Prerequisites {
    section "Checking Prerequisites"
    $allOk = $true

    # Python
    $pyCmd = Get-PythonExe
    if ($null -eq $pyCmd) {
        err "Python not found in PATH."
        info "Install Python 3.11+ from https://www.python.org/downloads/"
        info "Make sure to check 'Add Python to PATH' during install."
        $allOk = $false
    } else {
        try {
            $pyVerRaw = & $pyCmd --version 2>&1
            if ($pyVerRaw -match "Python (\d+)\.(\d+)") {
                $pyMaj = [int]$Matches[1]
                $pyMin = [int]$Matches[2]
                $pyStr = "$($pyMaj).$($pyMin)"
                if ($pyMaj -lt 3 -or ($pyMaj -eq 3 -and $pyMin -lt 11)) {
                    warn "Python $pyStr found - version 3.11 or higher is recommended"
                } else {
                    ok "Python $pyStr  ($pyCmd)"
                }
            }
        } catch {
            warn "Could not read Python version: $_"
        }
    }

    # Node (only needed if not BackendOnly)
    if (-not $BackendOnly) {
        $nodeCmd = Get-NodeExe
        if ($null -eq $nodeCmd) {
            err "Node.js not found in PATH."
            info "Install Node.js 18+ from https://nodejs.org/"
            info "The installer adds Node to PATH automatically."
            $allOk = $false
        } else {
            try {
                $nodeVer = node --version 2>&1
                if ($nodeVer -match "v(\d+)") {
                    $nodeMaj = [int]$Matches[1]
                    if ($nodeMaj -lt 18) {
                        warn "Node $nodeVer found - v18 or higher is recommended"
                    } else {
                        ok "Node $nodeVer"
                    }
                }
            } catch {
                warn "Could not read Node version: $_"
            }
        }
    }

    # Show where data will live
    Write-Host ""
    info "All data will be stored on: $($Script:ROOT)"
    dim "  Virtual env  -> $($Script:VENV)"
    dim "  SQLite DB    -> $($Script:BACKEND)\agi_memory.db"
    dim "  Logs         -> $($Script:LOG_DIR)"
    dim "  Workspace    -> $($Script:BACKEND)\agi_workspace"

    return $allOk
}

# ---------------------------------------------------------------------------
# Environment / .env setup
# ---------------------------------------------------------------------------
function Initialize-Environment {
    section "Environment Setup"

    $envFile    = Join-Path $Script:BACKEND ".env"
    $envExample = Join-Path $Script:ROOT ".env.local.example"

    if (-not (Test-Path $envFile)) {
        if (Test-Path $envExample) {
            Copy-Item $envExample $envFile
            ok "Created backend\.env from .env.local.example"
        } else {
            warn "No .env file found - backend will use built-in defaults"
            return
        }
    } else {
        ok "backend\.env already exists"
    }

    # Warn if OpenRouter key is still the placeholder
    $content = Get-Content $envFile -Raw
    $hasRealKey = $content -match "OPENROUTER_API_KEY=sk-or-v1-[A-Za-z0-9]"
    $hasPlaceholder = $content -match "OPENROUTER_API_KEY=sk-or-v1-your-key-here"

    if (-not $hasRealKey -or $hasPlaceholder) {
        Write-Host ""
        warn "OPENROUTER_API_KEY is not set in backend\.env"
        info "Get a free key at: https://openrouter.ai/keys"
        info "Free models are used by default - no payment required to start."
        Write-Host ""
        $edit = Read-Host "  Open backend\.env in Notepad now? [Y/n]"
        if ($edit -ne "n" -and $edit -ne "N") {
            Start-Process notepad (Join-Path $Script:BACKEND ".env") -Wait
        }
    }
}

# ---------------------------------------------------------------------------
# Install dependencies
# ---------------------------------------------------------------------------
function Install-BackendDeps {
    section "Backend Python Dependencies"

    $pyCmd = Get-PythonExe
    if ($null -eq $pyCmd) { err "Python not in PATH - cannot install."; return }

    # Create venv if missing
    if (-not (Test-Path $Script:VENV)) {
        info "Creating virtual environment at: $($Script:VENV)"

        # Point Python's temp dir to H: so venv creation doesn't touch C:
        $prevTemp = $env:TEMP; $prevTmp = $env:TMP
        $hTemp = Join-Path $Script:ROOT ".tmp"
        $null = New-Item -ItemType Directory -Path $hTemp -Force
        $env:TEMP = $hTemp; $env:TMP = $hTemp

        & $pyCmd -m venv $Script:VENV
        $exitCode = $LASTEXITCODE

        $env:TEMP = $prevTemp; $env:TMP = $prevTmp   # restore

        if ($exitCode -ne 0) { err "Failed to create virtual environment."; return }
        ok "Virtual environment created"
    } else {
        ok "Virtual environment already exists"
    }

    $pip = Get-VenvPip
    if ($null -eq $pip) { err "pip not found in venv."; return }

    # ---------------------------------------------------------------------------
    # Redirect ALL pip temp/cache dirs to H: so a full C: drive never blocks us.
    #   PIP_CACHE_DIR  - where pip caches downloaded wheels
    #   TEMP / TMP     - where pip & build tools unpack packages during install
    # ---------------------------------------------------------------------------
    $pipCache = Join-Path $Script:ROOT ".pip-cache"
    $pipTemp  = Join-Path $Script:ROOT ".tmp"
    $null = New-Item -ItemType Directory -Path $pipCache -Force
    $null = New-Item -ItemType Directory -Path $pipTemp  -Force

    $prevTemp       = $env:TEMP
    $prevTmp        = $env:TMP
    $prevPipCache   = $env:PIP_CACHE_DIR
    $prevPipTmpDir  = $env:PIP_TMPDIR

    $env:TEMP         = $pipTemp
    $env:TMP          = $pipTemp
    $env:PIP_CACHE_DIR = $pipCache
    $env:PIP_TMPDIR    = $pipTemp

    info "Pip cache  : $pipCache"
    info "Pip temp   : $pipTemp"
    info "Installing packages from requirements.txt  (may take a few minutes)..."

    $reqFile = Join-Path $Script:BACKEND "requirements.txt"
    & $pip install -r $reqFile --disable-pip-version-check `
        --cache-dir $pipCache `
        --no-build-isolation

    $exitCode = $LASTEXITCODE

    # Restore original env vars
    $env:TEMP         = $prevTemp
    $env:TMP          = $prevTmp
    if ($null -eq $prevPipCache)  { Remove-Item Env:\PIP_CACHE_DIR  -ErrorAction SilentlyContinue }
    else                          { $env:PIP_CACHE_DIR  = $prevPipCache }
    if ($null -eq $prevPipTmpDir) { Remove-Item Env:\PIP_TMPDIR     -ErrorAction SilentlyContinue }
    else                          { $env:PIP_TMPDIR     = $prevPipTmpDir }

    if ($exitCode -eq 0) {
        ok "Python packages installed"
    } else {
        warn "Some packages may have failed - check output above"
    }
}

function Install-FrontendDeps {
    section "Frontend Node Dependencies"

    # Redirect npm cache to H: so a full C: drive doesn't block the install.
    # npm stores its cache in %APPDATA%\npm-cache by default (C: drive).
    $npmCache = Join-Path $Script:ROOT ".npm-cache"
    $null = New-Item -ItemType Directory -Path $npmCache -Force

    $prevNpmCache = npm config get cache 2>$null
    npm config set cache $npmCache --global 2>$null
    info "npm cache  : $npmCache"

    $nm = Join-Path $Script:FRONTEND "node_modules"
    if (-not (Test-Path $nm)) {
        info "Installing npm packages (first run takes a minute)..."
        Push-Location $Script:FRONTEND

        # npm writes deprecation warnings to stderr; with $ErrorActionPreference="Stop"
        # PowerShell treats any stderr output from native commands as a fatal error.
        # Temporarily relax it so warnings are printed but don't abort the script.
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        npm install 2>&1 | ForEach-Object {
            # Show warn/error lines in yellow, info in dim, everything else normal
            if ($_ -match "^npm (warn|error)") { Write-Host "  $($CY)$_$($CX)" }
            else                               { Write-Host "  $($CD)$_$($CX)" }
        }
        $npmExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEAP

        Pop-Location

        if ($npmExit -eq 0) {
            ok "npm packages installed"
        } else {
            warn "npm install finished with exit code $npmExit - check output above"
        }
    } else {
        ok "node_modules already present"
    }

    # Restore previous npm cache location
    if ($prevNpmCache -and $prevNpmCache -ne "") {
        npm config set cache $prevNpmCache --global 2>$null
    }
}

# ---------------------------------------------------------------------------
# Wait for a TCP port to open
# ---------------------------------------------------------------------------
function Wait-ForPort {
    param(
        [int]$Port,
        [string]$Name,
        [int]$TimeoutSec = 60
    )
    $elapsed = 0
    $chars = @('|','/','-','\')
    $i = 0
    while ($elapsed -lt $TimeoutSec) {
        $conn = Test-NetConnection -ComputerName localhost -Port $Port `
            -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null
        if ($conn) {
            Write-Host "`r  $($CG)OK$($CX)  $Name is ready on port $Port              "
            return $true
        }
        $spin = $chars[$i % $chars.Length]
        $pct  = "$($elapsed)/$($TimeoutSec)s"
        Write-Host "`r  $($CY)$spin$($CX)   Waiting for $Name ... ($pct)" -NoNewline
        Start-Sleep -Seconds 2
        $elapsed += 2
        $i++
    }
    Write-Host "`r  $($CR)!!$($CX)  $Name did not start within $($TimeoutSec)s             "
    return $false
}

# ---------------------------------------------------------------------------
# Start / Stop services
# ---------------------------------------------------------------------------
function Start-Backend {
    $null = New-Item -ItemType Directory -Path $Script:LOG_DIR -Force

    $uvicorn = Get-VenvUvicorn
    $pyExe   = Get-VenvPython

    if ($null -ne $uvicorn) {
        $exe  = $uvicorn
        $args = @("app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload")
    } elseif ($null -ne $pyExe) {
        $exe  = $pyExe
        $args = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload")
    } else {
        err "Cannot find uvicorn or python in virtual environment."
        return $false
    }

    info "Starting FastAPI backend  ->  http://localhost:8000"

    $proc = Start-Process `
        -FilePath         $exe `
        -ArgumentList     $args `
        -WorkingDirectory $Script:BACKEND `
        -RedirectStandardOutput $Script:BE_OUT `
        -RedirectStandardError  $Script:BE_ERR `
        -PassThru `
        -WindowStyle Hidden

    $proc.Id | Set-Content $Script:BE_PID
    return $true
}

function Start-Frontend {
    $null = New-Item -ItemType Directory -Path $Script:LOG_DIR -Force

    info "Starting Next.js frontend  ->  http://localhost:3000"

    $proc = Start-Process `
        -FilePath         "npm" `
        -ArgumentList     @("run", "dev") `
        -WorkingDirectory $Script:FRONTEND `
        -RedirectStandardOutput $Script:FE_OUT `
        -RedirectStandardError  $Script:FE_ERR `
        -PassThru `
        -WindowStyle Hidden

    $proc.Id | Set-Content $Script:FE_PID
    return $true
}

function Stop-ServiceByPid {
    param([string]$PidFile, [string]$Name)
    if (Test-Path $PidFile) {
        $savedPid = [int](Get-Content $PidFile -Raw).Trim()
        try {
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                $proc.Kill()
                $proc.WaitForExit(5000) | Out-Null
                ok "$Name stopped (PID $savedPid)"
            } else {
                dim "$Name process (PID $savedPid) was already gone"
            }
        } catch {
            warn "Could not stop $Name PID $savedPid : $_"
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    } else {
        dim "No saved PID for $Name"
    }
}

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
function Invoke-Start {
    section "Starting Services"
    $beOk = $true
    $feOk = $true

    if (-not $FrontendOnly) {
        $beOk = Start-Backend
        if ($beOk) {
            $beReady = Wait-ForPort -Port 8000 -Name "Backend" -TimeoutSec 50
            if (-not $beReady) {
                warn "Backend is slow to start. Check: .local-logs\backend.log"
            }
        }
    }

    if (-not $BackendOnly) {
        $feOk = Start-Frontend
        if ($feOk) {
            $feReady = Wait-ForPort -Port 3000 -Name "Frontend" -TimeoutSec 90
            if (-not $feReady) {
                warn "Frontend is slow to start. Check: .local-logs\frontend.log"
            }
        }
    }
}

function Invoke-Stop {
    section "Stopping Services"
    Stop-ServiceByPid -PidFile $Script:BE_PID -Name "Backend"
    Stop-ServiceByPid -PidFile $Script:FE_PID -Name "Frontend"

    # Kill any orphaned processes as a safety net
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("python","python3","node") } |
        Where-Object {
            try { $_.MainModule.FileName -match "agi.agent|AGI.agent" } catch { $false }
        } |
        ForEach-Object { $_.Kill() }

    ok "Done"
}

function Invoke-Status {
    section "Service Status"

    $services = @(
        @{ Name = "Backend API";  Port = 8000; Url = "http://localhost:8000/health" },
        @{ Name = "Frontend UI";  Port = 3000; Url = "http://localhost:3000" }
    )

    foreach ($svc in $services) {
        $conn = Test-NetConnection -ComputerName localhost -Port $svc.Port `
            -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null
        $namePad = $svc.Name.PadRight(14)
        if ($conn) {
            Write-Host "  $($CG)RUNNING$($CX)  $namePad  $($CC)$($svc.Url)$($CX)"
        } else {
            Write-Host "  $($CD)stopped$($CX)  $namePad  $($CD)$($svc.Url)$($CX)"
        }
    }

    Write-Host ""
    dim "Logs : $($Script:LOG_DIR)"
    dim "venv : $($Script:VENV)"
}

function Show-Logs {
    param([string]$Which = "both")
    # stdout and stderr land in separate files on Windows; show both
    $files = switch ($Which) {
        "backend"  { @($Script:BE_OUT, $Script:BE_ERR) }
        "frontend" { @($Script:FE_OUT, $Script:FE_ERR) }
        default    { @($Script:BE_OUT, $Script:BE_ERR, $Script:FE_OUT, $Script:FE_ERR) }
    }
    $existing = $files | Where-Object { Test-Path $_ }
    if ($existing.Count -eq 0) {
        warn "No log files yet. Start the services first."
        dim "  Expected: $($Script:LOG_DIR)"
    } else {
        dim "  Watching: $($existing -join ', ')"
        Get-Content $existing -Tail 40 -Wait
    }
}

function Invoke-OpenBrowser {
    Start-Process "http://localhost:3000"
}

function Show-Completion {
    Write-Host ""
    Write-Host "$($CG)$($CB)  +------------------------------------------------+$($CX)"
    Write-Host "$($CG)$($CB)  |$($CX)$($CB)   AGI Agent is running locally               $($CG)|$($CX)"
    Write-Host "$($CG)$($CB)  +------------------------------------------------+$($CX)"
    Write-Host "$($CG)$($CB)  |$($CX)  $($CD)Frontend :$($CX)  $($CC)http://localhost:3000$($CX)            $($CG)$($CB)|$($CX)"
    Write-Host "$($CG)$($CB)  |$($CX)  $($CD)Backend  :$($CX)  $($CC)http://localhost:8000$($CX)            $($CG)$($CB)|$($CX)"
    Write-Host "$($CG)$($CB)  |$($CX)  $($CD)API Docs :$($CX)  $($CC)http://localhost:8000/docs$($CX)       $($CG)$($CB)|$($CX)"
    Write-Host "$($CG)$($CB)  |$($CX)  $($CD)Storage  :$($CX)  SQLite  (no Docker needed)         $($CG)$($CB)|$($CX)"
    Write-Host "$($CG)$($CB)  |$($CX)  $($CD)Data dir :$($CX)  $($Script:ROOT)  $($CG)$($CB)|$($CX)"
    Write-Host "$($CG)$($CB)  +------------------------------------------------+$($CX)"
    Write-Host ""
    Write-Host "  $($CD)View logs :$($CX)  $($CY).\run-local.ps1 -Action logs-backend$($CX)"
    Write-Host "  $($CD)Raw logs  :$($CX)  $($CD)$($Script:LOG_DIR)$($CX)"
    Write-Host "  $($CD)Stop      :$($CX)  $($CY).\run-local.ps1 -Action stop$($CX)"
    Write-Host ""

    $open = Read-Host "  Open browser now? [Y/n]"
    if ($open -ne "n" -and $open -ne "N") { Invoke-OpenBrowser }
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
function Main {
    # Must run from script directory so relative paths work correctly
    Set-Location $Script:ROOT

    Write-Banner

    switch ($Action) {
        "stop"          { Invoke-Stop; return }
        "status"        { Invoke-Status; return }
        "open"          { Invoke-OpenBrowser; return }
        "logs-backend"  { Show-Logs "backend"; return }
        "logs-frontend" { Show-Logs "frontend"; return }
        "restart"       { Invoke-Stop; Start-Sleep -Seconds 2 }
        "install" {
            if (-not (Test-Prerequisites)) { exit 1 }
            Initialize-Environment
            if (-not $FrontendOnly) { Install-BackendDeps }
            if (-not $BackendOnly)  { Install-FrontendDeps }
            ok "All dependencies installed. Run: .\run-local.ps1"
            return
        }
    }

    if (-not (Test-Prerequisites)) { exit 1 }
    Initialize-Environment

    if (-not $SkipInstall) {
        if (-not $FrontendOnly) { Install-BackendDeps }
        if (-not $BackendOnly)  { Install-FrontendDeps }
    }

    Invoke-Start
    Show-Completion
}

Main
