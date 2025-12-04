@echo off
REM ==============================================
REM  Distributed Database System - Full Startup
REM  Windows Batch Script
REM ==============================================
echo.
echo ==============================================
echo  Distributed Database System - Full Startup
echo ==============================================
echo.

REM Ensure we are in the project root (where this BAT file lives)
cd /d "%~dp0"

REM ----------------------------------------------
REM 1. START BACKEND (Docker Compose)
REM ----------------------------------------------
echo [1/3] Starting backend services (10 containers)...
cd backend

docker-compose up -d
IF ERRORLEVEL 1 (
    echo.
    echo ❌ Failed to start backend containers. Check Docker Desktop and docker-compose.
    echo.
    pause
    exit /b 1
)

echo ✔ Backend started successfully.
echo.

REM ----------------------------------------------
REM 2. WAIT FOR SERVICES TO INITIALIZE
REM ----------------------------------------------
echo [2/3] Waiting for backend services to initialize (about 15 seconds)...
timeout /t 15 /nobreak >nul
echo ✔ Backend services should now be ready.
echo.

REM Go back to project root
cd ..

REM ----------------------------------------------
REM 3. START FRONTEND (npm / Vite)
REM ----------------------------------------------
echo [3/3] Starting frontend dashboard...
cd frontend

IF NOT EXIST node_modules (
    echo node_modules not found. Installing frontend dependencies...
    call npm install
    IF ERRORLEVEL 1 (
        echo.
        echo ❌ npm install failed. Make sure Node.js and npm are installed.
        echo.
        pause
        exit /b 1
    )
)

echo Launching Vite development server with "npm run dev"...
echo (This window will stay open and show logs. Press CTRL+C to stop the frontend.)
echo.

REM Use CALL so the batch file waits for npm to finish
call npm run dev

echo.
echo Frontend server stopped.
echo (Backend Docker containers are still running.)
echo To stop backend, run:
echo   cd backend
echo   docker-compose down
echo.
pause
