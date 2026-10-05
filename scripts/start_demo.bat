@echo off
REM One-click local run on Windows: API on :8000, UI on :3000. No API key needed.
REM Usage: double-click this file, or run  scripts\start_demo.bat  from the repo root.
setlocal
cd /d "%~dp0\.."
set "ROOT=%CD%"

where python >nul 2>nul || (echo [X] Python 3.10+ not found. Install it from python.org and tick "Add python.exe to PATH". & pause & exit /b 1)
where npm >nul 2>nul || (echo [X] Node.js not found. Install the LTS version from nodejs.org. & pause & exit /b 1)
if not exist .env copy .env.example .env >nul

if not exist backend\.venv\Scripts\python.exe (
  echo [1/2] Creating backend\.venv and installing Python deps - first run only, a few minutes...
  python -m venv backend\.venv || (pause & exit /b 1)
  backend\.venv\Scripts\python -m pip install --upgrade pip >nul
  backend\.venv\Scripts\python -m pip install -r backend\requirements.txt || (pause & exit /b 1)
)
if not exist frontend\node_modules (
  echo [2/2] Installing frontend deps - first run only...
  pushd frontend
  call npm install --no-audit --no-fund || (popd & pause & exit /b 1)
  popd
)

start "CENP API :8000" cmd /k "cd /d "%ROOT%\backend" && .venv\Scripts\python -m uvicorn app.main:app --port 8000"
start "CENP UI :3000"  cmd /k "cd /d "%ROOT%\frontend" && npm run dev"
echo Waiting for the servers to start...
timeout /t 15 /nobreak >nul
start "" http://localhost:3000
echo Opened http://localhost:3000  -  close the two server windows to stop.
endlocal
