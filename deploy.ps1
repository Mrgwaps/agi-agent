#Requires -Version 5.1
<#
.SYNOPSIS
    AGI Agent - Intelligent Deployment Orchestrator

.DESCRIPTION
    Professional deployment script for the AGI Agent platform.
    Supports full-stack Docker Compose deployment with intelligent
    pre-flight validation, environment configuration, health monitoring,
    and graceful rollback on failure.

.PARAMETER Action
    Deployment action: deploy | stop | restart | status | logs | update | clean | reset

.PARAMETER Environment
    Target environment: development | staging | production (default: development)

.PARAMETER Services
    Specific services to target (comma-separated). Default: all services.

.PARAMETER SkipPreflightCheck
    Skip pre-flight dependency validation (not recommended)

.PARAMETER ForceRecreate
    Force container recreation even if unchanged

.PARAMETER NoBuild
    Skip image builds (use existing images)

.PARAMETER Follow
    Follow log output (used with -Action logs)

.PARAMETER Tail
    Number of log lines to show (default: 100)

.EXAMPLE
    .\deploy.ps1 -Action deploy -Environment development
    .\deploy.ps1 -Action deploy -Environment production
    .\deploy.ps1 -Action status
    .\deploy.ps1 -Action logs -Services backend -Follow
    .\deploy.ps1 -Action stop
    .\deploy.ps1 -Action clean -Environment development

.NOTES
    Author:  AGI Agent Team
    Version: 1.0.0
    Requires: Docker Desktop, Docker Compose v2, PowerShell 5.1+
#>

[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Position = 0)]
    [ValidateSet("deploy", "stop", "restart", "status", "logs", "update", "clean", "reset", "setup", "health")]
    [string]$Action = "deploy",

    [ValidateSet("development", "staging", "production")]
    [string]$Environment = "development",

    [string]$Services = "",

    [switch]$SkipPreflightCheck,
    [switch]$ForceRecreate,
    [switch]$NoBuild,
    [switch]$Follow,
    [int]$Tail = 100,
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ============================================================
#  CONSTANTS & CONFIGURATION
# ============================================================
$Script:VERSION        = "1.0.0"
$Script:PROJECT_NAME   = "agi-agent"
$Script:COMPOSE_FILE   = "docker-compose.yml"
$Script:ENV_FILE       = ".env"
$Script:ENV_EXAMPLE    = ".env.example"
$Script:LOG_FILE       = "deploy.log"
$Script:HEALTH_TIMEOUT = 180  # seconds to wait for healthy state

$Script:REQUIRED_SERVICES = @("postgres", "redis", "chromadb", "backend", "frontend")
$Script:CORE_SERVICES     = @("postgres", "redis", "chromadb", "backend", "frontend", "nginx")

$Script:SERVICE_PORTS = @{
    "postgres"  = 5432
    "redis"     = 6379
    "chromadb"  = 8001
    "backend"   = 8000
    "frontend"  = 3000
    "nginx"     = 80
}

$Script:SERVICE_URLS = @{
    "backend"  = "http://localhost:8000/health"
    "frontend" = "http://localhost:3000"
    "nginx"    = "http://localhost/health"
}

# ============================================================
#  ANSI COLORS (Windows 10+ compatible)
# ============================================================
$Script:C = @{
    Reset   = "`e[0m"
    Bold    = "`e[1m"
    Dim     = "`e[2m"
    # Foreground
    Black   = "`e[30m"
    Red     = "`e[31m"
    Green   = "`e[32m"
    Yellow  = "`e[33m"
    Blue    = "`e[34m"
    Magenta = "`e[35m"
    Cyan    = "`e[36m"
    White   = "`e[37m"
    # Bright
    BrightRed     = "`e[91m"
    BrightGreen   = "`e[92m"
    BrightYellow  = "`e[93m"
    BrightBlue    = "`e[94m"
    BrightMagenta = "`e[95m"
    BrightCyan    = "`e[96m"
    BrightWhite   = "`e[97m"
    # Background
    BgBlue    = "`e[44m"
    BgGreen   = "`e[42m"
    BgRed     = "`e[41m"
    BgYellow  = "`e[43m"
    BgMagenta = "`e[45m"
}

# Detect if terminal supports color
$Script:ColorEnabled = $Host.UI.SupportsVirtualTerminal -or $env:TERM -eq "xterm-256color" -or $env:WT_SESSION

function c([string]$color, [string]$text) {
    if ($Script:ColorEnabled) { return "$($Script:C[$color])$text$($Script:C.Reset)" }
    return $text
}

# ============================================================
#  LOGGING
# ============================================================
function Write-Log {
    param([string]$Message, [string]$Level = "INFO", [string]$Color = "BrightWhite")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine   = "[$timestamp] [$Level] $Message"
    Add-Content -Path $Script:LOG_FILE -Value $logLine -Encoding UTF8
    if ($Level -ne "DEBUG" -or $Verbose) {
        Write-Host "$(c $Color $logLine)"
    }
}

function Write-Banner {
    $banner = @"

$(c 'BrightMagenta' '  ┌─────────────────────────────────────────────────────┐')
$(c 'BrightMagenta' '  │')$(c 'BrightCyan' '           ██████╗  ██████╗ ██╗          ')$(c 'BrightMagenta' '│')
$(c 'BrightMagenta' '  │')$(c 'BrightCyan' '          ██╔══██╗██╔════╝ ██║          ')$(c 'BrightMagenta' '│')
$(c 'BrightMagenta' '  │')$(c 'BrightCyan' '          ███████║██║  ███╗██║          ')$(c 'BrightMagenta' '│')
$(c 'BrightMagenta' '  │')$(c 'BrightCyan' '          ██╔══██║██║   ██║██║          ')$(c 'BrightMagenta' '│')
$(c 'BrightMagenta' '  │')$(c 'BrightCyan' '          ██║  ██║╚██████╔╝██║          ')$(c 'BrightMagenta' '│')
$(c 'BrightMagenta' '  │')$(c 'BrightCyan' '          ╚═╝  ╚═╝ ╚═════╝ ╚═╝          ')$(c 'BrightMagenta' '│')
$(c 'BrightMagenta' '  │')$(c 'BrightWhite' '         AGI Agent Neural Interface        ')$(c 'BrightMagenta' '│')
$(c 'BrightMagenta' '  │')$(c 'Dim' "         v$($Script:VERSION) · Deployment Orchestrator    ")$(c 'BrightMagenta' '│')
$(c 'BrightMagenta' '  └─────────────────────────────────────────────────────┘')

"@
    Write-Host $banner
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "$(c 'BrightBlue' "  ▸ $Title")"
    Write-Host "$(c 'Dim' "  $('─' * 52)")"
}

function Write-Success { param([string]$Msg) Write-Host "  $(c 'BrightGreen' '✔') $Msg" }
function Write-Failure { param([string]$Msg) Write-Host "  $(c 'BrightRed' '✖') $Msg" }
function Write-Info    { param([string]$Msg) Write-Host "  $(c 'BrightCyan' '›') $Msg" }
function Write-Warn    { param([string]$Msg) Write-Host "  $(c 'BrightYellow' '⚠') $Msg" }
function Write-Step    { param([string]$Msg) Write-Host "  $(c 'Dim' '·') $Msg" }

# ============================================================
#  PREFLIGHT CHECKS
# ============================================================
function Test-DockerAvailable {
    Write-Step "Checking Docker..."
    try {
        $version = docker version --format "{{.Server.Version}}" 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Docker daemon not running" }
        Write-Success "Docker $version is running"
        return $true
    } catch {
        Write-Failure "Docker is not available: $_"
        Write-Info "Install Docker Desktop from https://www.docker.com/products/docker-desktop"
        return $false
    }
}

function Test-DockerComposeAvailable {
    Write-Step "Checking Docker Compose..."
    try {
        $version = docker compose version --short 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Docker Compose v2 not found" }
        Write-Success "Docker Compose $version available"
        return $true
    } catch {
        Write-Failure "Docker Compose v2 not available: $_"
        Write-Info "Update Docker Desktop or install the Compose plugin"
        return $false
    }
}

function Test-DiskSpace {
    $minGB = 10
    Write-Step "Checking disk space (minimum ${minGB}GB)..."
    try {
        $drive = (Get-Location).Drive.Name + ":"
        $disk  = Get-PSDrive -Name $drive.TrimEnd(":")
        $freeGB = [math]::Round($disk.Free / 1GB, 1)
        if ($freeGB -lt $minGB) {
            Write-Warn "Low disk space: ${freeGB}GB free (${minGB}GB recommended)"
            return $false
        }
        Write-Success "${freeGB}GB free disk space"
        return $true
    } catch {
        Write-Warn "Could not check disk space"
        return $true
    }
}

function Test-RequiredFiles {
    Write-Step "Checking required files..."
    $required = @($Script:COMPOSE_FILE, "backend/Dockerfile", "frontend/Dockerfile")
    $missing = $required | Where-Object { -not (Test-Path $_) }
    if ($missing.Count -gt 0) {
        Write-Failure "Missing required files: $($missing -join ', ')"
        return $false
    }
    Write-Success "All required files present"
    return $true
}

function Invoke-PreflightCheck {
    Write-Section "Pre-flight Checks"
    $results = @(
        (Test-DockerAvailable),
        (Test-DockerComposeAvailable),
        (Test-DiskSpace),
        (Test-RequiredFiles)
    )
    $failed = ($results | Where-Object { $_ -eq $false }).Count
    if ($failed -gt 0) {
        Write-Failure "$failed pre-flight check(s) failed"
        return $false
    }
    Write-Success "All pre-flight checks passed"
    return $true
}

# ============================================================
#  ENVIRONMENT SETUP
# ============================================================
function Initialize-Environment {
    Write-Section "Environment Configuration"

    if (-not (Test-Path $Script:ENV_FILE)) {
        if (Test-Path $Script:ENV_EXAMPLE) {
            Write-Warn ".env file not found. Creating from .env.example..."
            Copy-Item $Script:ENV_EXAMPLE $Script:ENV_FILE
            Write-Success "Created .env from template"
            Write-Warn "IMPORTANT: Edit .env and set your API keys before deploying!"
            Write-Info "  Required keys:"
            Write-Info "    OPENROUTER_API_KEY   - Get from https://openrouter.ai/keys"
            Write-Info "    HYPERBROWSER_API_KEY - Get from https://app.hyperbrowser.ai (optional)"
            Write-Info ""
            $edit = Read-Host "  Open .env in editor now? [Y/n]"
            if ($edit -ne "n" -and $edit -ne "N") {
                if (Get-Command "code" -ErrorAction SilentlyContinue) {
                    code $Script:ENV_FILE
                } elseif (Get-Command "notepad" -ErrorAction SilentlyContinue) {
                    Start-Process notepad $Script:ENV_FILE -Wait
                }
            }
        } else {
            Write-Failure ".env.example not found. Cannot create .env."
            return $false
        }
    } else {
        Write-Success ".env file exists"
    }

    # Validate critical settings
    $envContent = Get-Content $Script:ENV_FILE -Raw
    $warnings = @()

    if ($envContent -match "OPENROUTER_API_KEY=sk-or-v1-your-key-here" -or
        $envContent -notmatch "OPENROUTER_API_KEY=sk-or-") {
        $warnings += "OPENROUTER_API_KEY appears to be unset or default"
    }
    if ($envContent -match "change-me-strong-password") {
        $warnings += "POSTGRES_PASSWORD is still the default (change for production)"
    }
    if ($envContent -match "change-me-in-production") {
        $warnings += "APP_SECRET_KEY is still the default (change for production)"
    }

    if ($warnings.Count -gt 0 -and $Environment -eq "production") {
        Write-Warn "Configuration warnings for PRODUCTION deployment:"
        $warnings | ForEach-Object { Write-Warn "  · $_" }
        $confirm = Read-Host "  Continue anyway? [y/N]"
        if ($confirm -ne "y" -and $confirm -ne "Y") {
            Write-Failure "Deployment cancelled. Please fix configuration."
            return $false
        }
    } elseif ($warnings.Count -gt 0) {
        $warnings | ForEach-Object { Write-Warn $_ }
    }

    # Set environment-specific overrides
    switch ($Environment) {
        "production" {
            $env:COMPOSE_PROJECT_NAME = "$($Script:PROJECT_NAME)-prod"
            Write-Info "Environment: PRODUCTION"
        }
        "staging" {
            $env:COMPOSE_PROJECT_NAME = "$($Script:PROJECT_NAME)-staging"
            Write-Info "Environment: STAGING"
        }
        default {
            $env:COMPOSE_PROJECT_NAME = $Script:PROJECT_NAME
            Write-Info "Environment: DEVELOPMENT"
        }
    }

    Write-Success "Environment configured"
    return $true
}

# ============================================================
#  DOCKER OPERATIONS
# ============================================================
function Invoke-DockerCompose {
    param(
        [string[]]$Arguments,
        [switch]$PassThru,
        [switch]$Silent
    )
    $cmd = @("compose", "--file", $Script:COMPOSE_FILE) + $Arguments
    if (-not $Silent) {
        Write-Log "docker $($cmd -join ' ')" "DEBUG" "Dim"
    }
    if ($PassThru) {
        return docker @cmd 2>&1
    }
    docker @cmd
    return $LASTEXITCODE
}

function Get-ServiceStatus {
    param([string]$ServiceName = "")
    $args = @("ps", "--format", "json")
    if ($ServiceName) { $args += $ServiceName }
    $output = Invoke-DockerCompose -Arguments $args -PassThru -Silent
    return $output
}

function Wait-ForHealthy {
    param([string]$ServiceName, [int]$TimeoutSeconds = $Script:HEALTH_TIMEOUT)

    $spinner = @('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
    $elapsed = 0
    $i = 0

    while ($elapsed -lt $TimeoutSeconds) {
        $status = Invoke-DockerCompose -Arguments @("ps", "--format", "{{.Status}}", $ServiceName) -PassThru -Silent
        $statusStr = ($status | Out-String).Trim()

        if ($statusStr -match "healthy") {
            Write-Host "`r  $(c 'BrightGreen' '✔') $ServiceName is healthy                      "
            return $true
        } elseif ($statusStr -match "Exit|unhealthy|error") {
            Write-Host "`r  $(c 'BrightRed' '✖') $ServiceName failed to start                  "
            return $false
        }

        $spin = $spinner[$i % $spinner.Length]
        Write-Host "`r  $(c 'BrightYellow' $spin) Waiting for $ServiceName... ($elapsed/$TimeoutSeconds s)" -NoNewline
        Start-Sleep -Seconds 2
        $elapsed += 2
        $i++
    }

    Write-Host "`r  $(c 'BrightRed' '✖') $ServiceName health check timed out               "
    return $false
}

function Test-ServiceHTTP {
    param([string]$ServiceName, [string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -lt 400) {
            Write-Success "$ServiceName HTTP endpoint responding ($Url)"
            return $true
        }
    } catch {
        Write-Warn "$ServiceName HTTP not yet reachable: $Url"
        return $false
    }
    return $false
}

# ============================================================
#  ACTIONS
# ============================================================

function Invoke-Setup {
    Write-Section "One-Time Setup"
    Write-Info "Pulling base images for faster builds..."
    Invoke-DockerCompose -Arguments @("pull", "--ignore-pull-failures")
    Write-Success "Setup complete. Run: .\deploy.ps1 -Action deploy"
}

function Invoke-Deploy {
    Write-Section "Building Images"

    $buildArgs = @("build", "--parallel")
    if ($ForceRecreate) { $buildArgs += "--no-cache" }

    if (-not $NoBuild) {
        Write-Info "Building Docker images (this may take a few minutes on first run)..."
        $exitCode = Invoke-DockerCompose -Arguments $buildArgs
        if ($exitCode -ne 0) {
            Write-Failure "Image build failed"
            return $false
        }
        Write-Success "Images built successfully"
    }

    Write-Section "Starting Services"

    # Start infrastructure first
    Write-Info "Starting infrastructure services (postgres, redis, chromadb)..."
    $infraArgs = @("up", "-d", "--remove-orphans", "postgres", "redis", "chromadb")
    Invoke-DockerCompose -Arguments $infraArgs | Out-Null

    # Wait for infrastructure
    foreach ($svc in @("postgres", "redis", "chromadb")) {
        $healthy = Wait-ForHealthy -ServiceName $svc -TimeoutSeconds 120
        if (-not $healthy) {
            Write-Failure "Infrastructure service '$svc' failed to become healthy"
            Write-Info "Check logs: .\deploy.ps1 -Action logs -Services $svc"
            return $false
        }
    }

    # Start application services
    Write-Info "Starting application services (backend, frontend, nginx)..."
    $appArgs = @("up", "-d", "--remove-orphans")
    if ($ForceRecreate) { $appArgs += "--force-recreate" }
    Invoke-DockerCompose -Arguments $appArgs | Out-Null

    # Wait for app services
    foreach ($svc in @("backend", "frontend")) {
        $healthy = Wait-ForHealthy -ServiceName $svc -TimeoutSeconds 180
        if (-not $healthy) {
            Write-Failure "Application service '$svc' failed to start"
            Write-Info "Check logs: .\deploy.ps1 -Action logs -Services $svc"
            return $false
        }
    }

    Start-Sleep -Seconds 3

    Write-Section "HTTP Health Checks"
    foreach ($svc in $Script:SERVICE_URLS.Keys) {
        Test-ServiceHTTP -ServiceName $svc -Url $Script:SERVICE_URLS[$svc] | Out-Null
    }

    return $true
}

function Invoke-Stop {
    Write-Section "Stopping Services"
    $svcList = if ($Services) { $Services.Split(",").Trim() } else { @() }
    $args = @("down")
    if ($svcList.Count -gt 0) {
        $args = @("stop") + $svcList
    }
    Invoke-DockerCompose -Arguments $args
    Write-Success "Services stopped"
}

function Invoke-Restart {
    Write-Section "Restarting Services"
    $svcList = if ($Services) { $Services.Split(",").Trim() } else { $Script:CORE_SERVICES }
    foreach ($svc in $svcList) {
        Write-Step "Restarting $svc..."
        Invoke-DockerCompose -Arguments @("restart", $svc) | Out-Null
    }
    Write-Success "Services restarted"
}

function Invoke-Status {
    Write-Section "Service Status"

    $statusOutput = Invoke-DockerCompose -Arguments @("ps", "--format", "table") -PassThru
    Write-Host ($statusOutput | Out-String)

    Write-Section "Port Bindings"
    foreach ($svc in $Script:SERVICE_PORTS.Keys) {
        $port = $Script:SERVICE_PORTS[$svc]
        $tcpConn = Test-NetConnection -ComputerName localhost -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null
        $status = if ($tcpConn) { c 'BrightGreen' "OPEN" } else { c 'Dim' "CLOSED" }
        Write-Host "  $($svc.PadRight(12)) :$port  $status"
    }

    Write-Section "Resource Usage"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" 2>$null
}

function Invoke-ShowLogs {
    $svcList = if ($Services) { $Services.Split(",").Trim() } else { @() }
    $args = @("logs", "--tail=$Tail")
    if ($Follow) { $args += "-f" }
    if ($svcList.Count -gt 0) { $args += $svcList }
    Invoke-DockerCompose -Arguments $args
}

function Invoke-Update {
    Write-Section "Pulling Latest Images"
    Invoke-DockerCompose -Arguments @("pull")
    Write-Success "Images updated. Run: .\deploy.ps1 -Action deploy -ForceRecreate"
}

function Invoke-Clean {
    Write-Section "Cleaning Environment"
    $confirm = Read-Host "  Remove all containers and volumes for $Environment? [y/N]"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Info "Cancelled"
        return
    }
    Invoke-DockerCompose -Arguments @("down", "-v", "--remove-orphans")
    Write-Success "Environment cleaned"
}

function Invoke-Reset {
    Write-Section "Full Reset (DESTRUCTIVE)"
    Write-Warn "This will DELETE ALL data including the database!"
    $confirm = Read-Host "  Type 'RESET' to confirm"
    if ($confirm -ne "RESET") {
        Write-Info "Cancelled"
        return
    }
    Invoke-DockerCompose -Arguments @("down", "-v", "--remove-orphans", "--rmi", "local")
    if (Test-Path $Script:ENV_FILE) {
        Remove-Item $Script:ENV_FILE -Confirm:$false
    }
    Write-Success "Full reset complete"
}

function Invoke-HealthCheck {
    Write-Section "Health Check Report"

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss UTC"
    Write-Info "Report generated: $timestamp"

    foreach ($svc in $Script:SERVICE_URLS.Keys) {
        $url = $Script:SERVICE_URLS[$svc]
        try {
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $response = Invoke-WebRequest -Uri $url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            $sw.Stop()
            $latency = $sw.ElapsedMilliseconds
            Write-Host "  $(c 'BrightGreen' '●') $($svc.PadRight(12)) $(c 'BrightGreen' "HTTP $($response.StatusCode)") $(c 'Dim' "${latency}ms") $url"
        } catch {
            Write-Host "  $(c 'BrightRed' '●') $($svc.PadRight(12)) $(c 'BrightRed' 'UNREACHABLE') $url"
        }
    }
}

function Show-CompletionSummary {
    param([bool]$Success, [TimeSpan]$Duration)

    Write-Host ""
    if ($Success) {
        Write-Host "$(c 'BrightGreen' "  ╔══════════════════════════════════════════════════╗")"
        Write-Host "$(c 'BrightGreen' "  ║")$(c 'BrightWhite' "         ✨  AGI Agent Successfully Deployed        ")$(c 'BrightGreen' "║")"
        Write-Host "$(c 'BrightGreen' "  ╠══════════════════════════════════════════════════╣")"
        Write-Host "$(c 'BrightGreen' "  ║")  $(c 'Dim' "Frontend UI:  ")$(c 'BrightCyan' "http://localhost:3000           ")$(c 'BrightGreen' "║")"
        Write-Host "$(c 'BrightGreen' "  ║")  $(c 'Dim' "Backend API:  ")$(c 'BrightCyan' "http://localhost:8000           ")$(c 'BrightGreen' "║")"
        Write-Host "$(c 'BrightGreen' "  ║")  $(c 'Dim' "API Docs:     ")$(c 'BrightCyan' "http://localhost:8000/docs      ")$(c 'BrightGreen' "║")"
        Write-Host "$(c 'BrightGreen' "  ║")  $(c 'Dim' "Nginx Proxy:  ")$(c 'BrightCyan' "http://localhost                ")$(c 'BrightGreen' "║")"
        Write-Host "$(c 'BrightGreen' "  ║")  $(c 'Dim' "Duration:     ")$(c 'BrightWhite' "$([math]::Round($Duration.TotalSeconds, 1))s                          ")$(c 'BrightGreen' "║")"
        Write-Host "$(c 'BrightGreen' "  ╚══════════════════════════════════════════════════╝")"
        Write-Host ""
        Write-Host "  $(c 'Dim' "Next steps:")"
        Write-Host "  $(c 'BrightCyan' "·") View logs:   $(c 'Yellow' ".\deploy.ps1 -Action logs -Follow")"
        Write-Host "  $(c 'BrightCyan' "·") Check status: $(c 'Yellow' ".\deploy.ps1 -Action status")"
        Write-Host "  $(c 'BrightCyan' "·") Stop:        $(c 'Yellow' ".\deploy.ps1 -Action stop")"
    } else {
        Write-Host "$(c 'BrightRed' "  ╔══════════════════════════════════════════════════╗")"
        Write-Host "$(c 'BrightRed' "  ║")$(c 'BrightWhite' "         ✖  Deployment Failed                       ")$(c 'BrightRed' "║")"
        Write-Host "$(c 'BrightRed' "  ╚══════════════════════════════════════════════════╝")"
        Write-Host ""
        Write-Host "  $(c 'Dim' "Troubleshooting:")"
        Write-Host "  $(c 'BrightCyan' "·") View logs:  $(c 'Yellow' ".\deploy.ps1 -Action logs -Services backend")"
        Write-Host "  $(c 'BrightCyan' "·") Check .env: $(c 'Yellow' "notepad .env")"
        Write-Host "  $(c 'BrightCyan' "·") Clean up:   $(c 'Yellow' ".\deploy.ps1 -Action clean")"
    }
    Write-Host ""
}

# ============================================================
#  MAIN ENTRY POINT
# ============================================================
function Main {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    # Ensure we're in the right directory
    $scriptDir = Split-Path -Parent $MyInvocation.PSCommandPath
    Set-Location $scriptDir

    # Initialize log
    $null = New-Item -ItemType File -Path $Script:LOG_FILE -Force
    Write-Log "=== AGI Agent Deployment === Action=$Action Environment=$Environment" "INFO" "Dim"

    Write-Banner

    Write-Host "  $(c 'Dim' "Action:") $(c 'BrightWhite' $Action)  $(c 'Dim' "Environment:") $(c 'BrightWhite' $Environment)"
    Write-Host ""

    $success = $true

    switch ($Action) {
        "setup" {
            if (-not $SkipPreflightCheck) {
                if (-not (Invoke-PreflightCheck)) { exit 1 }
            }
            if (-not (Initialize-Environment)) { exit 1 }
            Invoke-Setup
        }
        "deploy" {
            if (-not $SkipPreflightCheck) {
                if (-not (Invoke-PreflightCheck)) { $success = $false; break }
            }
            if (-not (Initialize-Environment)) { $success = $false; break }
            $success = Invoke-Deploy
        }
        "stop"    { Invoke-Stop }
        "restart" { Invoke-Restart }
        "status"  { Invoke-Status }
        "logs"    { Invoke-ShowLogs }
        "update"  { Invoke-Update }
        "clean"   { Invoke-Clean }
        "reset"   { Invoke-Reset }
        "health"  { Invoke-HealthCheck }
    }

    $sw.Stop()

    if ($Action -in @("deploy")) {
        Show-CompletionSummary -Success $success -Duration $sw.Elapsed
    }

    Write-Log "Completed in $([math]::Round($sw.Elapsed.TotalSeconds, 1))s with success=$success" "INFO" "Dim"

    if (-not $success) { exit 1 }
}

Main
