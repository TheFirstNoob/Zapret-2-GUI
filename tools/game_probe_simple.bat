@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PROC=%~1"
if "%PROC%"=="" set "PROC=WardogsClient"
set "LOG=%~dp0game_probe_simple.log"

echo === game_probe_simple ===
echo Process: %PROC%.exe
echo Log file: %LOG%
echo.
echo Watching the game network (no admin rights needed).
echo Start the game, reproduce the problem, then press Ctrl+C.
echo.

echo === game_probe_simple: %PROC%.exe === > "%LOG%"
echo Started: %DATE% %TIME% >> "%LOG%"
echo. >> "%LOG%"

:loop
set "PAT="
for /f "skip=1 tokens=2 delims=," %%p in ('tasklist /FI "IMAGENAME eq %PROC%.exe" /FO CSV /NH 2^>nul') do (
    set "P=%%~p"
    if not "!P!"=="" set "PAT=!PAT! !P!$"
)

if defined PAT (
    echo [%DATE% %TIME%] PIDs:!PAT! >> "%LOG%"
    netstat -ano | findstr /R "!PAT!" >> "%LOG%"
    echo. >> "%LOG%"
) else (
    echo [%DATE% %TIME%] process %PROC%.exe not running >> "%LOG%"
    echo. >> "%LOG%"
)

timeout /t 3 /nobreak >nul
goto loop
