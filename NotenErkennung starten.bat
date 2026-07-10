@echo off
title NotenErkennung
cd /d "%~dp0"

set "PY=%USERPROFILE%\venvs\NotenErkennung\Scripts\python.exe"
if not exist "%PY%" (
    echo Python-Umgebung nicht gefunden unter:
    echo   %PY%
    echo Bitte README.md, Abschnitt "Setup" lesen.
    pause
    exit /b 1
)

echo.
echo  NotenErkennung startet ...
echo  Der Browser oeffnet sich gleich unter http://localhost:8765
echo.
echo  WICHTIG: Dieses schwarze Fenster offen lassen, solange du das
echo  Tool benutzt. Zum Beenden einfach dieses Fenster schliessen.
echo.

start "" "http://localhost:8765"
"%PY%" -m uvicorn web.server:app --port 8765

echo.
echo Der Server wurde beendet (oder konnte nicht starten, siehe Meldung oben).
echo Haeufigste Ursache: Das Tool laeuft bereits in einem anderen Fenster.
pause
