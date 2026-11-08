param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$portable = Join-Path $PSScriptRoot 'dist/CAD2STL/CAD2STL.exe'
if (Test-Path -LiteralPath $portable) {
    & $portable serve --port $Port
} else {
    $python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Build CAD2STL.exe or create .venv and install requirements.txt. See README.md.'
    }
    & $python (Join-Path $PSScriptRoot 'cad2stl.py') serve --port $Port
}
exit $LASTEXITCODE
