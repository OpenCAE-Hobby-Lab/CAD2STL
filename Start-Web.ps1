param([int]$Port = 8765, [string]$FreeCADPython = 'C:\Program Files\FreeCAD 1.0\bin\python.exe')
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $FreeCADPython -PathType Leaf)) {
    throw 'FreeCAD同梱Pythonのパスを -FreeCADPython で指定してください。'
}
& $FreeCADPython (Join-Path $PSScriptRoot 'experiments/freecad/web_app.py') --port $Port
exit $LASTEXITCODE
