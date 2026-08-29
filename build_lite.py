"""Generate the 'lite' distribution — a Defender-friendly .bat-based package
with NO Python runtime (mirrors the Zapret 1 layout).

The full GUI (PyInstaller onefile) triggers cloud-detection heuristics
(temp extraction + driver load + localhost server).  The lite package is
just winws2 + lua/blobs/lists + .bat files — the same binaries v1 ships.

Usage:  python build_lite.py   (run from the repo root)
Output: lite/  (start.bat, stop.bat, service-install.bat, service-remove.bat)
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import zipfile

from core.launcher import build_args_from_preset
from core.utils import short_path

ROOT = pathlib.Path(__file__).resolve().parent
LITE = ROOT / "lite"

COPY_DIRS = ("bin", "lua", "blobs", "lists", "presets", "windivert")

Z1_CHECK_BLOCK = (
    'tasklist /FI "IMAGENAME eq winws.exe" /NH 2>nul | findstr /I "winws.exe" >nul\r\n'
    'if not errorlevel 1 (\r\n'
    '    echo ERROR: Zapret 1 is running - stop winws.exe first.\r\n'
    '    pause\r\n'
    '    exit /b 1\r\n'
    ')\r\n'
)

STOP_BAT = (
    "@echo off\r\n"
    "taskkill /F /IM winws2.exe >nul 2>&1\r\n"
    "taskkill /F /IM winws.exe >nul 2>&1\r\n"
)


def _portable_args(args: list[str], root_abs: str, root_short: str) -> list[str]:
    """Rewrite absolute paths in args to %~dp0-relative (portable bat)."""
    out = []
    for a in args:
        for prefix in (root_abs, root_short):
            for marker in (f"@{prefix}\\", f"{prefix}\\"):
                if marker in a:
                    a = a.replace(marker, "@%~dp0" if marker[0] == "@" else "%~dp0")
                    break
            else:
                continue
            break
        out.append(a)
    return out


def _write_start_bat(name: str, args: list[str]) -> None:
    cmdline = " ".join(f'"{a}"' for a in args)
    (LITE / name).write_text(
        '@echo off\r\n'
        'cd /d "%~dp0"\r\n'
        + Z1_CHECK_BLOCK +
        f'start "zapret2" /min "%~dp0bin\\winws2.exe" {cmdline}\r\n',
        encoding="ascii",
    )


SERVICE_MENU_BAT = r"""@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
:menu
cls
echo ==========================================
echo   Zapret 2 lite - menu
echo ==========================================
echo   1. Select strategy and start
echo   2. Stop
echo   3. Install service (autostart, default preset)
echo   4. Remove service
echo   5. Exit
echo.
set /p c=Choose [1-5]:
if "%c%"=="1" goto pick
if "%c%"=="2" goto stop
if "%c%"=="3" call "%~dp0service-install.bat"
if "%c%"=="4" call "%~dp0service-remove.bat"
if "%c%"=="5" exit /b
goto menu
:pick
cls
echo Available strategies:
set n=0
for %%f in (start-*.bat) do (
    set /a n+=1
    set "nm=%%~nf"
    set "opt!n!=%%f"
    echo   !n!. !nm:start-=!
)
echo.
set /p sel=Number:
set "chosen=opt!sel!"
call set "filename=%%!chosen!%%"
if not defined filename goto pick
call "!filename!"
echo Started. Press any key...
pause >nul
goto menu
:stop
taskkill /F /IM winws2.exe >nul 2>&1
echo Stopped.
pause >nul
goto menu
"""


def _write_service_bat(exe_rel: str, args: list[str]) -> None:
    cmdline = " ".join(f'"{a}"' for a in args)
    (LITE / "_zapret_service.bat").write_text(
        '@echo off\r\n'
        'cd /d "%~dp0"\r\n'
        f'start /b /wait "" "{exe_rel}" {cmdline} > nul 2>&1\r\n',
        encoding="ascii",
    )


def _svc_install_bat(portable_args: list[str]) -> str:
    """Direct-exe service like Zapret 1 (binPath = winws2.exe + args,
    start= auto) — the cmd/bat wrapper is what Defender flags."""
    argstr = " ".join(f'\\"{a}\\"' for a in portable_args)
    return (
        '@echo off\r\n'
        'cd /d "%~dp0"\r\n'
        'sc query zapret >nul 2>&1 && (echo ERROR: Zapret 1 service found - remove it first. & pause & exit /b 1)\r\n'
        + Z1_CHECK_BLOCK +
        'sc stop zapret2 >nul 2>&1\r\n'
        'sc delete zapret2 >nul 2>&1\r\n'
        f'sc create zapret2 binPath= "\\"%~dp0bin\\winws2.exe\\" {argstr}" '
        'DisplayName= "Zapret 2 DPI Bypass" start= auto\r\n'
        'sc start zapret2\r\n'
        'echo.\r\n'
        'echo Service installed and started. To remove: service-remove.bat\r\n'
        'pause\r\n'
    )


SVC_INSTALL_BAT = (
    '@echo off\r\n'
    'cd /d "%~dp0"\r\n'
    'sc stop zapret2 >nul 2>&1\r\n'
    'sc delete zapret2 >nul 2>&1\r\n'
    'sc create zapret2 binPath= "\\"cmd.exe\\" /C \\"%~dp0_zapret_service.bat\\"" '
    'DisplayName= "Zapret 2 DPI Bypass" start= auto\r\n'
    'sc start zapret2\r\n'
    'echo.\r\n'
    'echo Service installed and started. To remove: service-remove.bat\r\n'
    'pause\r\n'
)

SVC_REMOVE_BAT = (
    '@echo off\r\n'
    'sc stop zapret2 >nul 2>&1\r\n'
    'sc delete zapret2 >nul 2>&1\r\n'
    'taskkill /F /IM winws2.exe >nul 2>&1\r\n'
    'echo Service removed.\r\n'
    'pause\r\n'
)

README_TXT = """Zapret 2 GUI — lite-версия (без Python, на .bat)

Отличается от полной версии только способом запуска: здесь нет GUI и
сборщика — только winws2, списки и батники (как в Zapret 1). Защитник
Windows к этой версии относится заметно спокойнее.

Использование (от имени администратора):
  start.bat                — запустить обход (пресет default.txt)
  stop.bat                 — остановить обход
  service-install.bat      — установить и запустить службу (автозапуск)
  service-remove.bat       — удалить службу

Настройка стратегии: редактируйте presets\\default.txt (как в полной версии)
или другие .txt в presets\\ — затем замените имя пресета в start.bat
(строка --запуск по умолчанию использует default).

Пресет по умолчанию: default.txt (универсальная стратегия).
"""


def main() -> None:
    if LITE.exists():
        shutil.rmtree(LITE)
    LITE.mkdir()

    for d in COPY_DIRS:
        src = ROOT / d
        if src.is_dir():
            shutil.copytree(src, LITE / d)

    exe = LITE / "bin" / "winws2.exe"

    # one start-<preset>.bat per strategy (portable %~dp0 paths)
    for pf in sorted((LITE / "presets").glob("*.txt")):
        args = build_args_from_preset(LITE, LITE / "lua", LITE / "blobs", pf)
        portable = _portable_args(args, str(LITE), short_path(LITE))
        _write_start_bat(f"start-{pf.stem}.bat", portable)

    # default preset for the service
    args = build_args_from_preset(LITE, LITE / "lua", LITE / "blobs",
                                  LITE / "presets" / "default.txt")
    portable = _portable_args(args, str(LITE), short_path(LITE))

    (LITE / "stop.bat").write_text(STOP_BAT, encoding="ascii")
    (LITE / "service.bat").write_text(SERVICE_MENU_BAT, encoding="ascii")
    (LITE / "service-install.bat").write_text(_svc_install_bat(portable), encoding="ascii")
    (LITE / "service-remove.bat").write_text(SVC_REMOVE_BAT, encoding="ascii")

    # tester: test.bat launcher (double-click safe) + test.ps1 (PS 5.1)
    (LITE / "test.bat").write_text(
        '@echo off\r\n'
        'chcp 65001 >nul\r\n'
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test.ps1"\r\n',
        encoding="ascii")
    ps1 = (ROOT / "test_lite.ps1").read_text(encoding="utf-8")
    (LITE / "test.ps1").write_text(ps1, encoding="utf-8-sig")  # BOM: PS5.1 reads Cyrillic correctly

    (LITE / "README.txt").write_text(README_TXT, encoding="utf-8")

    zip_name = ROOT / "Windows build" / "Zapret2GUI-lite.zip"
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(LITE.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(LITE))
    print(f"OK: {LITE}  + {zip_name}  ({zip_name.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()