@echo off
rem Write the whole database to a dated file in offline\backups. Run it while the app is up.
cd /d "%~dp0.."
if not exist offline\backups mkdir offline\backups
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set STAMP=%%i
docker compose -f docker/docker-compose.yml exec -T db sh -c "pg_dump -U $POSTGRES_USER $POSTGRES_DB" > "offline\backups\peopleopslab-%STAMP%.sql"
if errorlevel 1 (
  echo Backup failed. Is the app running?
) else (
  echo Saved offline\backups\peopleopslab-%STAMP%.sql
)
pause
