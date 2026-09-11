@echo off
setlocal
cd /d "%~dp0"

set "PROC=%~1"
if "%PROC%"=="" set "PROC=WardogsClient"

rem UDP capture (pktmon) requires administrator rights - self-elevate via UAC
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%PROC%' -Verb RunAs"
  exit /b
)

echo.
echo === game_probe ===
echo Process: %PROC%   (other process: game_probe.bat process_name)
echo Live log: %~dp0game_probe.log
echo.
echo Watching the game network. The log updates itself - nothing to copy.
echo Start the game, reproduce the problem, then press Ctrl+C (or exit the game).
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0game_probe.ps1" -Process "%PROC%"

echo.
echo Log: %~dp0game_probe.log
echo Send this file for analysis.
pause
