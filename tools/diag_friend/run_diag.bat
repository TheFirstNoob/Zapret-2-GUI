@echo off
rem ZAPRET2 DIAG COLLECTION (run as Administrator)
rem Creates zapret2_diag_<date>.log next to this file.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diag.ps1"
echo.
pause
