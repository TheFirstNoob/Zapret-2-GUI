"""Сборка «lite»-дистрибутива: .bat-пакет без Python-рантайма (как в Zapret 1) —
те же бинарники winws2 + lua/blobs/lists, что и в v1.

PyInstaller-onefile полного GUI ловит облачные эвристики Defender (распаковка
во временную папку + загрузка драйвера + локальный сервер); lite-сборке
ловить нечего.

Запуск: python build_lite.py   (из корня репо)
Вывод:  lite/  (start.bat, stop.bat, service-install.bat, service-remove.bat)
"""
from __future__ import annotations

import pathlib
import re
import shutil
import sys
import zipfile

from core.launcher import build_args_from_preset, _conf_quote_token
from core.utils import short_path

ROOT = pathlib.Path(__file__).resolve().parent
LITE = ROOT / "lite"

COPY_DIRS = ("bin", "lua", "blobs", "lists", "presets", "windivert")

# Экспериментальные пресеты не попадают в дистрибутив (остаются в git).
RELEASE_PRESETS = lambda name: not name.startswith(("exp-", "cand-", "test-"))

Z1_CHECK_BLOCK = (
    'tasklist /FI "IMAGENAME eq winws.exe" /NH 2>nul | findstr /I "winws.exe" >nul\r\n'
    'if not errorlevel 1 (\r\n'
    '    echo ERROR: Zapret 1 is running - stop winws.exe first.\r\n'
    '    pause\r\n'
    '    exit /b 1\r\n'
    ')\r\n'
)

# Parity 18.10: два движка winws2 (lite + GUI/service) одновременно = конфликт
# фильтров и мусорные замеры - start-*.bat отказывается.
W2_CHECK_BLOCK = (
    'tasklist /FI "IMAGENAME eq winws2.exe" /NH 2>nul | findstr /I "winws2.exe" >nul\r\n'
    'if not errorlevel 1 (\r\n'
    '    echo ERROR: winws2 is already running ^(GUI/lite/service^). Run stop.bat first.\r\n'
    '    pause\r\n'
    '    exit /b 1\r\n'
    ')\r\n'
)

# Останавливаем ТОЛЬКО winws2 из этой папки (+служба zapret2 отдельно):
# name-wide taskkill убивал движок другой копии GUI/lite (parity 18.10).
OWN_WINWS2_STOP = (
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \""
    "$p='%~dp0'; Get-Process winws2 -ErrorAction SilentlyContinue | "
    "Where-Object { $_.Path -and $_.Path.StartsWith($p, "
    "[StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force\" "
    ">nul 2>&1\r\n"
)

STOP_BAT = (
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    "cd /d \"%~dp0\"\r\n"
    "sc stop zapret2 >nul 2>&1\r\n"
    + OWN_WINWS2_STOP +
    "taskkill /F /IM winws.exe >nul 2>&1\r\n"
)


def _portable_args(args: list[str], root_abs: str, root_short: str) -> list[str]:
    """Переписывает абсолютные пути в args на %~dp0-относительные (portable bat)."""
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


def _conf_portable_args(args: list[str], root_abs: str, root_short: str) -> list[str]:
    """Абсолютные пути -> ОТНОСИТЕЛЬНЫЕ (для conf-файла start-батов).

    Conf читает Cygwin, а не cmd: `%~dp0` в контенте не раскрывается, зато
    winws2 резолвит относительные пути от cwd, который bat ставит в %~dp0."""
    out = []
    for a in args:
        for prefix in (root_abs, root_short):
            for marker, repl in ((f"@{prefix}\\", "@"), (f"{prefix}\\", "")):
                if marker in a:
                    a = a.replace(marker, repl)
                    break
            else:
                continue
            break
        out.append(a)
    return out


def _write_start_bat(name: str, args_rel: list[str]) -> None:
    """start-<name>.bat + conf-<name>.conf: bat запускает winws2 @"conf".

    Аргументы не зависят от длины и кавычек cmd; относительные пути - от cwd
    (bat делает `cd /d %~dp0`)."""
    stem = name[:-4] if name.endswith(".bat") else name
    conf_name = f"conf-{stem}.conf"
    conf = LITE / conf_name
    conf.write_text("\n".join(_conf_quote_token(t) for t in args_rel) + "\n",
                    encoding="utf-8")
    (LITE / name).write_text(
        '@echo off\r\n'
        'cd /d "%~dp0"\r\n'
        + Z1_CHECK_BLOCK + W2_CHECK_BLOCK +
        f'start "zapret2" /min "%~dp0bin\\winws2.exe" @"%~dp0{conf_name}"\r\n',
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
echo   5. Fix WinDivert driver (if bypass fails to start)
echo   6. Check for updates
echo   7. Exit
echo.
set /p c=Choose [1-7]:
if "%c%"=="1" goto pick
if "%c%"=="2" goto stop
if "%c%"=="3" call "%~dp0service-install.bat"
if "%c%"=="4" call "%~dp0service-remove.bat"
if "%c%"=="5" call "%~dp0fix-driver.bat"
if "%c%"=="6" call "%~dp0update.bat"
if "%c%"=="7" exit /b
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
call "%~dp0stop.bat"
echo Stopped.
pause >nul
goto menu
"""


def _svc_install_bat(portable_args: list[str]) -> str:
    """service-install.bat: на месте генерит service_run.conf (echo-блок,
    %~dp0 раскрывается cmd) и ставит короткий binPath = exe + @"conf"."""
    # build-time инвариант: токены уходят в `echo "..."` - внутри кавычек
    # cmd опасны только `"` и `%` (вне `%~dp0`); ломаем сборку громко, если
    # пресет изменился и занёс такие символы.
    bad = [a for a in portable_args
           if '"' in a or "%" in a.replace("%~dp0", "")]
    if bad:
        raise SystemExit(f"service-install: небезопасные для cmd токены: {bad[:3]}")
    body = "".join(f'    echo "{a}"\r\n' for a in portable_args)
    return (
        '@echo off\r\n'
        'cd /d "%~dp0"\r\n'
        'sc query zapret >nul 2>&1 && (echo ERROR: Zapret 1 service found - remove it first. & pause & exit /b 1)\r\n'
        + Z1_CHECK_BLOCK +
        # Служба zapret2 ОБЩАЯ с GUI: чужую (из другой папки) не трогаем -
        # иначе lite молча перезапишет/удалит установку GUI (parity 18.10).
        'sc query zapret2 >nul 2>&1 && (\r\n'
        '    sc qc zapret2 | findstr /I /C:"%~dp0" >nul\r\n'
        '    if errorlevel 1 (\r\n'
        '        echo ERROR: service zapret2 is installed from ANOTHER folder ^(GUI/lite^).\r\n'
        '        echo Remove it from that copy first. Nothing changed.\r\n'
        '        pause\r\n'
        '        exit /b 1\r\n'
        '    )\r\n'
        ')\r\n'
        'sc stop zapret2 >nul 2>&1\r\n'
        'sc delete zapret2 >nul 2>&1\r\n'
        '> "%~dp0service_run.conf" (\r\n'
        + body +
        ')\r\n'
        'sc create zapret2 binPath= "\\"%~dp0bin\\winws2.exe\\" @\\"%~dp0service_run.conf\\"" '
        'DisplayName= "Zapret 2 DPI Bypass" start= auto\r\n'
        'sc description zapret2 "zapret DPI bypass (Zapret 2 lite)" >nul\r\n'
        # Паритет с GUI: автоперезапуск при падении движка (SCM recovery).
        'sc failure zapret2 reset= 86400 actions= restart/60000/restart/60000/restart/60000 >nul\r\n'
        'sc start zapret2\r\n'
        'echo.\r\n'
        'echo Service installed and started. To remove: service-remove.bat\r\n'
        'pause\r\n'
    )


SVC_REMOVE_BAT = (
    '@echo off\r\n'
    'chcp 65001 >nul\r\n'
    'cd /d "%~dp0"\r\n'
    # Удаляем только СВОЮ службу: чужую (GUI/lite из другой папки) не трогаем.
    'sc query zapret2 >nul 2>&1 && (\r\n'
    '    sc qc zapret2 | findstr /I /C:"%~dp0" >nul\r\n'
    '    if errorlevel 1 (\r\n'
    '        echo ERROR: service zapret2 belongs to ANOTHER folder - not removed.\r\n'
    '        pause\r\n'
    '        exit /b 1\r\n'
    '    )\r\n'
    ')\r\n'
    'sc stop zapret2 >nul 2>&1\r\n'
    'sc delete zapret2 >nul 2>&1\r\n'
    + OWN_WINWS2_STOP +
    'echo Service removed.\r\n'
    'pause\r\n'
)

# Аналог GUI «Выгрузить драйвер»/repair: битый ImagePath чиним на НАШ
# WinDivert64.sys, застрявший драйвер выгружаем (parity lite↔GUI, 18.10).
FIX_DRIVER_BAT = (
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    "cd /d \"%~dp0\"\r\n"
    "echo [1/3] Stopping Zapret 2 (service + this copy)...\r\n"
    "sc stop zapret2 >nul 2>&1\r\n"
    + OWN_WINWS2_STOP +
    "echo [2/3] Checking WinDivert driver service...\r\n"
    "sc query WinDivert >nul 2>&1\r\n"
    "if errorlevel 1 (\r\n"
    "    echo   WinDivert service not found - it will be created automatically on next start.\r\n"
    "    goto done\r\n"
    ")\r\n"
    "sc qc WinDivert | findstr /I /C:\"%~dp0bin\\WinDivert64.sys\" >nul\r\n"
    "if errorlevel 1 (\r\n"
    "    echo   ImagePath is broken or points to another folder - repairing...\r\n"
    "    sc config WinDivert binPath= \"\\??\\%~dp0bin\\WinDivert64.sys\" start= demand\r\n"
    ") else (\r\n"
    "    echo   ImagePath OK.\r\n"
    ")\r\n"
    "sc query WinDivert | findstr /I \"RUNNING\" >nul\r\n"
    "if not errorlevel 1 (\r\n"
    "    sc stop WinDivert >nul 2>&1\r\n"
    "    if errorlevel 1 (\r\n"
    "        echo   Driver is busy - it will unload after handles close or reboot.\r\n"
    "    ) else (\r\n"
    "        echo   Driver unloaded.\r\n"
    "    )\r\n"
    ")\r\n"
    ":done\r\n"
    "echo [3/3] Done. Start protection again: start-default.bat or service.bat (item 3).\r\n"
    "pause\r\n"
)

README_TXT = """Zapret 2 lite - обход блокировок без GUI (Windows)

Это простая версия Zapret 2: без установки Python и без графического окна.
Всё делается через .bat-файлы. Запускать от имени администратора.

Честно о программе (коротко):
  - Это оболочка над движком winws2 (Zapret 2): фильтрует сетевые пакеты
    на вашем ПК, чтобы обходить DPI-блокировки.
  - Права администратора нужны, чтобы загрузить драйвер WinDivert
    (bin\\WinDivert64.sys) - без него обход не работает.
  - Автозапуск появляется ТОЛЬКО если сами установите службу
    (service.bat -> пункт 3). Удалить - пункт 4.
  - Телеметрии нет. Логи движка пишутся в эту же папку и никуда не уходят.
  - Сами .bat-файлы ничего никуда не отправляют.

Как пользоваться:

  Шаг 1. Просто включить обход:
         двойной клик по start-default.bat
         (чтобы остановить - stop.bat)

  Шаг 2. Если что-то не открывается - запусти test.bat.
         Он сам проверит связь, найдёт проблемные сайты и спросит:
         "Применить фикс? Y/N" - ответьте Y, и он сам всё поправит.
         После этого обход перезапустится с улучшенными списками.

  Шаг 3. Автозапуск после перезагрузки (по желанию):
         service.bat -> пункт 3 (установить службу).
         Удаление службы - service.bat -> пункт 4.

Что за файлы:
  start-default.bat   обычный обход (все списки)
  start-ipset.bat     обход для всех сайтов сразу (если списки не помогли)
  start-имя.bat       запуск с конкретной стратегией (по одной на стратегию)
  test.bat            проверка связи и автофикс списков
  stop.bat            остановить обход
  service.bat         меню службы (автозапуск)
  fix-driver.bat      починить драйвер WinDivert (обход не запускается/выбивает)
  update.bat          проверить обновления (только уведомление)

Если обход не запускается вообще:
  запустите fix-driver.bat: он останавливает обход, починит путь службы
  WinDivert на файл из этой папки и выгрузит застрявший драйвер. Если он
  напишет, что драйвер занят - перезагрузите ПК и запустите обход заново.

Проверка обновлений: update.bat (сравнивает VERSION с GitHub, даёт ссылку).
Автообновления в lite нет - обновляйтесь вручную, сохраняя свои списки.

Настройка под себя: списки лежат в папке lists\\ (list-general.txt -
что обходить, list-exclude.txt - что не трогать). Файлы можно
редактировать обычным блокнотом, по одной записи на строку.

Ограничения lite (важно):
  - lite не повторяет GUI-тогглы: GameFilter, голос Discord, автохостлист и
    выбор блоба в lite не настраиваются - пресет запускается с настройками
    по умолчанию. start-ipset.bat = default с «Общим IP-обходом».
  - Не запускайте lite одновременно с GUI/службой: если winws2 уже запущен,
    start-*.bat откажется. stop.bat останавливает службу zapret2 и движки
    ТОЛЬКО из этой папки.
  - Служба zapret2 общая для GUI и lite: установка/удаление из папки, которая
    её не ставила, откажется (защита от взаимного затирания).
  - test.bat - упрощённая проверка связи + автофикс списков (без QUIC/H3,
    DoH-проверки и сравнения всех пресетов; полный тестер - в GUI).
  - Обновление lite - вручную: скачайте новый архив и распакуйте поверх,
    сохранив свои lists\\*user*.txt и правки.
"""


def main() -> None:
    if LITE.exists():
        shutil.rmtree(LITE)
    LITE.mkdir()

    for d in COPY_DIRS:
        src = ROOT / d
        if src.is_dir():
            shutil.copytree(src, LITE / d)
    # экспериментальные пресеты и генерируемый custom не попадают в дистрибутив
    for p in list((LITE / "presets").glob("*.txt")):
        if not RELEASE_PRESETS(p.stem) or p.stem == "custom":
            p.unlink()
    # юзер-файлы: в дистрибутив — пустые шаблоны (реальные не утекают)
    for name in ("list-include-user", "list-exclude-user",
                 "ipset-include-user", "ipset-exclude-user",
                 "list-games", "list-include-all"):
        (LITE / "lists" / f"{name}.txt").write_text("", encoding="utf-8")
    # пул-файлы игр (lists/games/*) — рантайм конкретной машины
    shutil.rmtree(LITE / "lists" / "games", ignore_errors=True)

    # манифест обновления пишется НИЖЕ, после генерации всех файлов
    # (bat/тестер/VERSION/README): иначе манифест не совпадал с содержимым
    # архива (аудит 2026-10)
    sys.path.insert(0, str(ROOT))
    from core.config import VERSION
    from core.updater import write_manifest

    # по одному start-<preset>.bat на стратегию (conf-файлы с относительными
    # путями; bat дописывает cwd=%~dp0)
    for pf in sorted((LITE / "presets").glob("*.txt")):
        if not RELEASE_PRESETS(pf.stem):
            continue
        args = build_args_from_preset(LITE, LITE / "lua", LITE / "blobs", pf)
        conf_args = _conf_portable_args(args, str(LITE), short_path(LITE))
        _write_start_bat(f"start-{pf.stem}.bat", conf_args)

    # ipset-вариант default (catch-all) — им пользуется стабилизатор test.ps1 в A/B
    ipset_args = build_args_from_preset(LITE, LITE / "lua", LITE / "blobs",
                                        LITE / "presets" / "default.txt",
                                        ipset_catchall=True)
    ipset_conf = _conf_portable_args(ipset_args, str(LITE), short_path(LITE))
    _write_start_bat("start-ipset.bat", ipset_conf)

    # default-пресет для службы (%~dp0-токены: echo-блок раскроет их в момент
    # установки службы, conf получит абсолютные пути)
    args = build_args_from_preset(LITE, LITE / "lua", LITE / "blobs",
                                  LITE / "presets" / "default.txt")
    portable = _portable_args(args, str(LITE), short_path(LITE))

    (LITE / "stop.bat").write_text(STOP_BAT, encoding="ascii")
    (LITE / "service.bat").write_text(SERVICE_MENU_BAT, encoding="ascii")
    (LITE / "service-install.bat").write_text(_svc_install_bat(portable), encoding="ascii")
    (LITE / "service-remove.bat").write_text(SVC_REMOVE_BAT, encoding="ascii")
    (LITE / "fix-driver.bat").write_text(FIX_DRIVER_BAT, encoding="ascii")
    # Проверка обновлений: только уведомление (автообновления в lite нет).
    (LITE / "update.bat").write_text(
        '@echo off\r\n'
        'chcp 65001 >nul\r\n'
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"\r\n',
        encoding="ascii")
    (LITE / "update.ps1").write_text(
        (ROOT / "update_lite.ps1").read_text(encoding="utf-8"),
        encoding="utf-8-sig")  # BOM: PS 5.1 читает кириллицу только так

    # тестер: test.bat (безопасен при двойном клике) + test.ps1 (PS 5.1)
    (LITE / "test.bat").write_text(
        '@echo off\r\n'
        'chcp 65001 >nul\r\n'
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test.ps1"\r\n',
        encoding="ascii")
    ps1 = (ROOT / "test_lite.ps1").read_text(encoding="utf-8")
    # Анти-дрейф (parity 18.10): наборы хостов в test.ps1 генерируются из
    # core/tester_defs.py - lite-тестер не отстаёт от GUI при правках списков.
    from core.tester_defs import CDN_HOSTS, CONTROL_HOSTS, RATED_HOSTS

    def _ps_array(name: str, items: list[str]) -> str:
        body = ",\r\n".join(f'    "{h}"' for h in items)
        return f"${name} = @(\r\n{body}\r\n)"

    hosts_block = (
        "# >>> HOSTS-AUTOGEN (build_lite.py: из core/tester_defs.py)\r\n"
        + _ps_array("RATED", RATED_HOSTS) + "\r\n"
        + _ps_array("CONTROL", CONTROL_HOSTS) + "\r\n"
        + "# CDN candidates for the hostlist-vs-ipset A/B (GUI CDN_HOSTS)\r\n"
        + _ps_array("CDN", CDN_HOSTS) + "\r\n"
        + "# <<< HOSTS-AUTOGEN")
    ps1, _n = re.subn(r"# >>> HOSTS-AUTOGEN.*?# <<< HOSTS-AUTOGEN",
                      lambda _m: hosts_block, ps1, count=1, flags=re.S)
    if _n != 1:
        raise SystemExit("test_lite.ps1: нет маркеров HOSTS-AUTOGEN")
    (LITE / "test.ps1").write_text(ps1, encoding="utf-8-sig")  # BOM: иначе PS 5.1 ломает кириллицу

    from datetime import date
    (LITE / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    lite_readme = (f"Версия: {VERSION} · сборка {date.today().isoformat()}\n"
                   + "=" * 50 + "\n\n" + README_TXT)
    (LITE / "README.txt").write_text(lite_readme, encoding="utf-8")
    # лицензии: собственный код (MIT) + уведомления о сторонних компонентах
    shutil.copy2(ROOT / "LICENSE", LITE / "LICENSE.txt")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", LITE / "THIRD_PARTY_NOTICES.txt")
    # готовый hosts (пины GitHub/AI/Discord и т.п.) - применяется вручную
    shutil.copy2(ROOT / "hosts.txt", LITE / "hosts.txt")

    # Смоук-тест прямо в сборке: движок из архива должен принимать каждый
    # release-пресет (dry-run, драйвер не грузится). Лучше упасть на сборке,
    # чем отдать пользователю архив с нерабочим пресетом.
    from core.launcher import validate_args
    lite_exe = LITE / "bin" / "winws2.exe"
    checked = 0
    failed = []
    for pf in sorted((LITE / "presets").glob("*.txt")):
        if not RELEASE_PRESETS(pf.stem) or pf.stem == "custom":
            continue
        args = build_args_from_preset(LITE, LITE / "lua", LITE / "blobs", pf)
        ok, err = validate_args(lite_exe, args, cwd=LITE)
        checked += 1
        if not ok:
            failed.append(f"{pf.stem}: {err}")
    if failed:
        print("ОШИБКА: lite-пресеты не проходят dry-run:")
        for f in failed:
            print("  -", f)
        sys.exit(1)
    print(f"OK: dry-run {checked} пресетов")

    write_manifest(LITE, VERSION)
    zip_name = ROOT / "Windows build" / "Zapret2GUI-lite.zip"
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(LITE.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(LITE))
    import hashlib
    sha = hashlib.sha256(zip_name.read_bytes()).hexdigest()
    (ROOT / "Windows build" / "Zapret2GUI-lite.zip.sha256").write_text(sha + "\n", encoding="ascii")
    print(f"OK: {LITE}  + {zip_name}  ({zip_name.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"SHA256: {sha}")


if __name__ == "__main__":
    main()