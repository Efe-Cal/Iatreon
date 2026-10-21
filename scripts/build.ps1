$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}
$null = Get-Command go, iscc -ErrorAction Stop

Push-Location $projectRoot
try {
    & $python -c 'import PyInstaller'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller is required in the build Python environment.' }

    $releasePath = [IO.Path]::GetFullPath((Join-Path $projectRoot 'release'))
    if ([IO.Path]::GetDirectoryName($releasePath) -ne $projectRoot) {
        throw 'Release output must be inside the project directory.'
    }
    if (Test-Path -LiteralPath $releasePath) {
        Remove-Item -LiteralPath $releasePath -Recurse -Force
    }
    New-Item -Path (Join-Path $releasePath 'python-worker') -ItemType Directory | Out-Null

    Write-Host 'Building iatreon.exe...'
    go build -C .\tui -trimpath -o ..\release\iatreon.exe .\cmd\app
    if ($LASTEXITCODE -ne 0) { throw 'TUI build failed.' }

    Write-Host 'Building python-worker.exe...'
    & $python -m PyInstaller python-worker.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw 'Python worker build failed.' }
    Copy-Item -Path 'dist\python-worker\*' -Destination (Join-Path $releasePath 'python-worker') -Recurse

    & $python scripts/smoke_worker.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaged worker smoke check failed.' }

    iscc installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
} finally {
    Pop-Location
}
