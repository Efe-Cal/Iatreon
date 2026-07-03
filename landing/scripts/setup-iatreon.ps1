# Hostname/port are resolved at runtime from $Origin/host.txt (or fallback 127.0.0.1:2222).
param(
    [string]$KeyPath = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$HostName,
    [int]$Port,
    [string]$Origin = "https://iatreon.efecal.hackclub.app/",
    [string]$HostAlias = "iatreon",
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

function Get-IatreonHostInfo {
    param(
        [string]$OriginUrl
    )

    $base = $OriginUrl.TrimEnd('/')
    $url = "$base/host.txt"
    Write-Step "Fetching host info from $url"

    $body = $null
    try {
        $ProgressPreference = 'SilentlyContinue'
        $response = Invoke-WebRequest -Uri $url -Method Get -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        $body = $response.Content
    } catch {
        $body = $null
    } finally {
        $ProgressPreference = 'Continue'
    }

    $fallbackHost = "127.0.0.1"
    $fallbackPort = 2222

    if ([string]::IsNullOrWhiteSpace($body)) {
        Write-Step "Could not fetch host.txt; falling back to ${fallbackHost}:${fallbackPort}"
        return @{ HostName = $fallbackHost; Port = $fallbackPort }
    }

    $firstLine = ($body -split "`r?`n", 2)[0]
    $tokens = $firstLine -split ':', 3
    if ($tokens.Count -lt 2 -or [string]::IsNullOrWhiteSpace($tokens[0]) -or [string]::IsNullOrWhiteSpace($tokens[1])) {
        Write-Step "host.txt was empty or malformed; falling back to ${fallbackHost}:${fallbackPort}"
        return @{ HostName = $fallbackHost; Port = $fallbackPort }
    }

    $parsedHost = $tokens[0].Trim()
    $parsedPort = 0
    if (-not [int]::TryParse($tokens[1].Trim(), [ref]$parsedPort)) {
        Write-Step "host.txt port was not numeric; falling back to ${fallbackHost}:${fallbackPort}"
        return @{ HostName = $fallbackHost; Port = $fallbackPort }
    }

    Write-Step "Using ${parsedHost}:${parsedPort} from host.txt"
    return @{ HostName = $parsedHost; Port = $parsedPort }
}

function Write-SshConfig {
    param(
        [string]$ConfigPath,
        [string]$HostAlias,
        [string]$HostName,
        [int]$Port
    )

    $startMarker = "# >>> iatreon"
    $endMarker = "# <<< iatreon"
    $existing = ""
    if (Test-Path $ConfigPath) {
        $existing = Get-Content -Raw $ConfigPath
    }

    $pattern = "(?ms)^$([regex]::Escape($startMarker))\r?\n.*?^$([regex]::Escape($endMarker))\r?\n?"
    $filtered = ([regex]::Replace($existing, $pattern, "")).TrimEnd()
    $block = @"
$startMarker
Host $HostAlias
    HostName $HostName
    Port $Port
    ForwardAgent yes
$endMarker
"@

    if ([string]::IsNullOrWhiteSpace($filtered)) {
        $content = $block
    } else {
        $content = "$filtered`r`n`r`n$block"
    }
    Set-Content -Path $ConfigPath -Value $content -NoNewline -Encoding ascii
}

Require-Command ssh
Require-Command ssh-add
Require-Command ssh-keygen

if ([string]::IsNullOrWhiteSpace($HostName) -or $PSBoundParameters.ContainsKey('Port') -eq $false -or $Port -eq 0) {
    $info = Get-IatreonHostInfo -OriginUrl $Origin
    if ([string]::IsNullOrWhiteSpace($HostName)) { $HostName = $info.HostName }
    if (-not $PSBoundParameters.ContainsKey('Port') -or $Port -eq 0) { $Port = $info.Port }
} else {
    Write-Step "Using ${HostName}:${Port} from command line"
}

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

Write-Step "Writing SSH config for $HostAlias"
Write-SshConfig -ConfigPath (Join-Path $sshDir "config") -HostAlias $HostAlias -HostName $HostName -Port $Port

if ($NoConnect) {
    Write-Host "Connect with:"
    Write-Host "ssh $HostAlias"
} else {
    $answer = Read-Host "Run ssh $HostAlias now? [y/N]"
    if ($answer -match '(?i)^y(es)?$') {
        Write-Step "Connecting to Iatreon SSH server"
        & ssh $HostAlias
    }
}
