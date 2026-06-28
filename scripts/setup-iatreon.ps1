#TODO: Update hostname
param(
    [string]$KeyPath = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$HostName = "127.0.0.1",
    [switch]$NoConnect
)
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message"
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. Install OpenSSH Client for Windows and try again."
    }
}

Require-Command ssh
Require-Command ssh-add
Require-Command ssh-keygen

$sshDir = Split-Path -Parent $KeyPath
if (-not (Test-Path $sshDir)) {
    Write-Step "Creating $sshDir"
    New-Item -ItemType Directory -Path $sshDir | Out-Null
}

$agent = Get-Service ssh-agent -ErrorAction SilentlyContinue
if ($null -eq $agent) {
    throw "The Windows OpenSSH Authentication Agent service is missing. Install OpenSSH Client and try again."
}

try {
    if ($agent.StartType -ne "Automatic") {
        Write-Step "Enabling ssh-agent service"
        Set-Service ssh-agent -StartupType Automatic
    }

    if ($agent.Status -ne "Running") {
        Write-Step "Starting ssh-agent service"
        Start-Service ssh-agent
    }
} catch {
    throw "Could not enable/start ssh-agent. Re-run this command in PowerShell as Administrator, then run it again normally if needed. Details: $($_.Exception.Message)"
}

if (-not (Test-Path $KeyPath)) {
    Write-Step "Creating Ed25519 SSH key at $KeyPath"
    & ssh-keygen -t ed25519 -f $KeyPath -N "" -C "iatreon@$env:COMPUTERNAME"
    if ($LASTEXITCODE -ne 0) {
        throw "ssh-keygen failed with exit code $LASTEXITCODE."
    }
}

Write-Step "Adding key to ssh-agent"
& ssh-add $KeyPath
if ($LASTEXITCODE -ne 0) {
    throw "ssh-add failed with exit code $LASTEXITCODE."
}

$keys = & ssh-add -L 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($keys -join "`n"))) {
    throw "ssh-agent is running, but no keys are loaded."
}

Write-Step "ssh-agent is ready"
Write-Host ""
Write-Host "Loaded public key:"
Write-Host $keys
Write-Host ""

if ($NoConnect) {
    Write-Host "Connect with:"
    Write-Host "ssh -A $HostName"
} else {
    $answer = Read-Host "Run ssh -A $HostName now? [y/N]"
    if ($answer -match '(?i)^y(es)?$') {
        Write-Step "Connecting to Iatreon SSH server"
        & ssh -A $HostName
    }
}
