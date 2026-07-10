# Startet die Transkription mit der richtigen Python-Umgebung.
# Benutzung:  .\noten.ps1 "C:\Pfad\zum\song.mp3" [weitere Optionen]
$py = Join-Path $env:USERPROFILE "venvs\NotenErkennung\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Python-Umgebung fehlt. Siehe README.md, Abschnitt Setup."
    exit 1
}
& $py (Join-Path $PSScriptRoot "transcribe.py") @args
