@echo off
REM ── SE ContentEdge Tools: Stop both services ──
echo Stopping SE ContentEdge Tools...
taskkill /FI "WINDOWTITLE eq CE-Tools Backend*" /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq CE-Tools Frontend*" /F >nul 2>nul
echo Done.
