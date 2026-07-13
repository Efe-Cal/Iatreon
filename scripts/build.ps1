$count = (pip freeze | Measure-Object -Line).Lines

if ($count -gt 80) {
    Write-Host "Warning: venv is too large: $count packages. This may result in a large executable size."
}

Remove-Item release -Recurse -Force -ErrorAction Ignore

New-Item release -ItemType Directory | Out-Null
New-Item release\python-worker -ItemType Directory | Out-Null

echo "Building iatreon.exe..."

go build -C .\tui -o ..\release\iatreon.exe .\cmd\app

echo "Building python-worker.exe..."

pyinstaller python-worker.spec --noconfirm --clean

Copy-Item dist\python-worker\* release\python-worker -Recurse

iscc installer.iss