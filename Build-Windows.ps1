param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        & $Python -3.12 -m venv .venv
        if ($LASTEXITCODE) { throw 'Python 3.12 environment creation failed' }
    }
    & .venv/Scripts/python.exe -m pip install -r requirements-build.txt
    if ($LASTEXITCODE) { throw 'Dependency installation failed' }
    & .venv/Scripts/python.exe -m PyInstaller --noconfirm CAD2STL.spec
    if ($LASTEXITCODE) { throw 'Build failed' }
    Copy-Item -LiteralPath 'README.md','THIRD_PARTY_NOTICES.md' -Destination 'dist/CAD2STL'
    Copy-Item -LiteralPath 'licenses' -Destination 'dist/CAD2STL' -Recurse -Force
    Write-Host 'Built dist/CAD2STL/CAD2STL.exe. Copy the entire CAD2STL folder.'
} finally { Pop-Location }
