@echo off
chcp 65001 >nul
setlocal
title Discord / Cloudflare temporary fix
set "DIR=%~dp0"
set "STATE=%DIR%"
if "%STATE:~-1%"=="\" set "STATE=%STATE:~0,-1%"

rem --- admin check; relaunch whole console as admin ---
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Для установки/удаления нужны права администратора.
  echo  Сейчас откроется запрос UAC - нажмите "Да".
  echo.
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs"
  exit /b
)

if /I "%~1"=="install"   set "ACTION=Install"
if /I "%~1"=="uninstall" set "ACTION=Uninstall"
if /I "%~1"=="status"    set "ACTION=Status"
if defined ACTION goto run

:menu
cls
echo ============================================================
echo   Discord / Cloudflare - временный фикс
echo ============================================================
echo.
echo   Что делает:
echo   ставит фоновую задачу Windows, локальный DNS и hosts,
echo   чтобы Discord, Cloudflare-капча и авторизация работали
echo   без открытого Zapret GUI и без VPN.
echo.
echo   ВАЖНО: это временный обход, не VPN. Стримы могут флапать.
echo   Если у вас включен фикс внутри Zapret 2 - сначала отключите его,
echo   иначе конфликт порта 53.
echo.
echo   1. Установить фикс  (рекомендуется)
echo   2. Проверить состояние
echo   3. Удалить фикс
echo   0. Выход
echo.
set /p choice=Выберите пункт [0-3]: 
if "%choice%"=="1" set "ACTION=Install"
if "%choice%"=="2" set "ACTION=Status"
if "%choice%"=="3" set "ACTION=Uninstall"
if "%choice%"=="0" exit /b 0
if not defined ACTION goto menu
goto run

:run
echo.
echo Запускаю: %ACTION% ...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%DIR%DiscordCloudflareFix.ps1" -Action %ACTION% -StateDir "%STATE%"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo Команда завершилась с кодом %RC%.
echo Нажмите любую клавишу, чтобы закрыть окно...
pause >nul
exit /b %RC%
