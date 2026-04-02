@echo off
REM ── SE ContentEdge Tools: Start both backend and frontend ──
echo.
echo  ╔══════════════════════════════════════╗
echo  ║   SE ContentEdge Tools - Starting    ║
echo  ╚══════════════════════════════════════╝
echo.

REM Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found in PATH
    exit /b 1
)

REM Check Node.js
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found in PATH
    exit /b 1
)

cd /d %~dp0

REM Install Python dependencies
echo [1/4] Installing Python dependencies...
pip install -q -r backend\requirements.txt

REM Install Node dependencies
echo [2/4] Installing Node.js dependencies...
cd frontend
call npm install --silent 2>nul
cd ..

REM Start Python backend
echo [3/4] Starting Python backend (port 8500)...
start "CE-Tools Backend" cmd /c "cd backend && python server.py"

REM Wait for backend
timeout /t 2 /nobreak >nul

REM Start Node frontend
echo [4/4] Starting Node.js frontend (port 3000)...
start "CE-Tools Frontend" cmd /c "cd frontend && node server.js"

echo.
echo  ✓ Backend running at http://localhost:8500
echo  ✓ Frontend running at http://localhost:3000
echo.
echo  Open http://localhost:3000 in your browser.
echo.
