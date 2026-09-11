@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PROC=%~1"
if "%PROC%"=="" set "PROC=WardogsClient"

:: UDP-захват (pktmon) требует прав администратора — перезапускаемся с UAC
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Запрос прав администратора...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%PROC%' -Verb RunAs"
  exit /b
)

echo.
echo === game_probe ===
echo Процесс: %PROC%  (другой: game_probe.bat имя_процесса)
echo Живой лог: %~dp0game_probe.log
echo.
echo Запускаю наблюдение за игрой. Лог обновляется сам, копировать ничего не надо.
echo Остановка: Ctrl+C (или просто выйдите из игры)
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0game_probe.ps1" -Process "%PROC%"

echo.
echo Лог: %~dp0game_probe.log
echo Отправьте этот файл для анализа.
pause
