# Startet die Browser-Oberfläche und öffnet sie im Standardbrowser.
# Benutzung:  .\web.ps1
$py = Join-Path $env:USERPROFILE "venvs\NotenErkennung\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Python-Umgebung fehlt. Siehe README.md, Abschnitt Setup."
    exit 1
}
Start-Process "http://localhost:8765"
Set-Location $PSScriptRoot
& $py -m uvicorn web.server:app --port 8765
