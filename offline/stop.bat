@echo off
rem Stop Peopleopslab. The data is kept; start.bat brings it back.
cd /d "%~dp0.."
docker compose -f docker/docker-compose.yml down
pause
