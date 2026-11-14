@echo off
rem Start Peopleopslab on this computer. Nothing leaves the machine.
rem The first run downloads the base images and builds; later runs need no internet.
cd /d "%~dp0.."
docker compose -f docker/docker-compose.yml up -d --build
if errorlevel 1 (
  echo.
  echo Could not start. Is Docker Desktop running?
  pause
  exit /b 1
)
echo.
echo Peopleopslab is starting. Open http://localhost:3000 in a minute.
echo Stop it with offline\stop.bat. Your data stays on this computer.
pause
