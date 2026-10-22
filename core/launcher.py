from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from core.admin import enable_privilege, get_enabled_privileges
from core import args_transforms, list_health, preset_parse
from core.applog import log as _applog
from core.utils import short_path


# Маркеры ошибок winws2 на неверные параметры (exit code ненадёжен: даже на
# "unknown option" возвращает 0 - вывод приходится сканировать).
_DRY_RUN_ERROR_MARKERS = (
    "unknown option",
    "bad file",
    "cannot access file",
    "cannot create",
    "cannot open",
    "invalid autottl",
    "lua error",
    "error loading",
)


def _winws2_env() -> dict[str, str]:
    """env для winws2: Cygwin ждёт UTF-8-локаль (кривой LANG у юзера ломает пути)."""
    env = os.environ.copy()
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    return env


def _conf_quote_token(t: str) -> str:
    """Токен конфига: DQ при пробелах/бэкслэшах/glob-символах.

    Unquoted-токены Cygwin прогоняет через globify (`'`, `[`, `]`, `(`, `)`,
    `{`, `}`, `?`, `*`, `~`) - пути с такими символами калечатся (внешнее
    ревью 14.10: путь с `'`/`[]` терял бэкслэши: `C:Users...`). Пути с
    бэкслэшами квотим всегда - единообразно и дёшево."""
    if any(c in t for c in " \t\\'(){}[]?*~"):
        return f'"{t}"'
    return t


def _conf_text(tokens: list[str]) -> str:
    return "\n".join(_conf_quote_token(str(t)) for t in tokens) + "\n"


def _winws2_raw_cmdline(exe_path: Path, conf_path: Path, *pre: str) -> str:
    """Командная строка вида `"exe" [pre...] @"conf"`.

    Кавычки вокруг ПУТИ, @ снаружи: только так Cygwin раскрывает @file
    (`"@conf"` - кавычка перед @ - отключает раскрытие, см.
    AI_DOCS/ARG_FILE_RESEARCH_2026-10-14.md, dcrt0.cc sawquote).
    `pre` - флаги безопасности (--dry-run/--intercept=0) ДУБЛИРУЮТСЯ в argv:
    если раскрытие @file когда-нибудь сломается (обновление winws2), процесс
    всё равно не уйдёт в живой перехват (fail-closed, внешнее ревью 14.10).
    """
    pre_str = " ".join(pre)
    return f'"{exe_path}" {pre_str + " " if pre_str else ""}@"{conf_path}"'


def write_run_conf(root_dir: Path, args: list[str], name: str = "run.conf") -> Path:
    """Пишет аргументы winws2 в logs/<name> (токен на строку, LF, UTF-8).

    Атомарная запись (tmp + os.replace): winws2 читает конфиг только целиком.
    """
    logs = root_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    conf = logs / name
    tmp = conf.with_name(conf.name + ".tmp")
    tmp.write_text(_conf_text(args), encoding="utf-8")
    os.replace(tmp, conf)
    return conf


def _write_temp_conf(tokens: list[str]) -> Path:
    """Временный conf для dry-run/lua-проверок (в TEMP)."""
    fd, name = tempfile.mkstemp(prefix="zapret2_preflight_", suffix=".conf")
    os.close(fd)
    p = Path(name)
    p.write_text(_conf_text(tokens), encoding="utf-8")
    return p


def _read_stderr_sink(root_dir: Path, limit: int = 1500) -> str:
    """Перехваченный вывод winws2 (logs/winws2_last_stderr.log).

    Ранние ошибки (getopt/lua) печатаются в НАЧАЛЕ вывода, поэтому при
    длинном тексте возвращаем начало+конец, а не только хвост.
    """
    p = root_dir / "logs" / "winws2_last_stderr.log"
    try:
        data = p.read_bytes()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace").strip()
    if len(text) <= limit:
        return text
    head = text[: limit // 2].strip()
    tail = text[-limit // 2:].strip()
    return head + "\n...\n" + tail


def validate_args(exe_path: Path, args: list[str], cwd: Optional[Path] = None, timeout: float = 10.0) -> tuple[bool, str]:
    """Проверка аргументов winws2 через --dry-run перед реальным запуском.

    Гоняет настоящий бинарник в режиме проверки (~0.1-0.3с) и ищет в выводе
    известные маркеры ошибок.  Возвращает (True, "") при валидных аргументах
    или (False, первая проблемная строка вывода).  WinDivert не грузится -
    состояние драйвера не затрагивается.
    """
    conf = _write_temp_conf(list(args) + ["--dry-run"])
    try:
        r = subprocess.run(
            _winws2_raw_cmdline(exe_path, conf, "--dry-run"),
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=_winws2_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"winws2 --dry-run не выполнился: {e}"
    finally:
        conf.unlink(missing_ok=True)
    output = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
    for line in output.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in _DRY_RUN_ERROR_MARKERS):
            return False, f"winws2 отклонил параметры: {stripped}"
    return validate_lua(exe_path, args, cwd, timeout)


_LUA_ERROR_MARKERS = (
    "lua error",
    "not accessible",
    "unexpected symbol",
    "' expected",
    "attempt to",
    "stack traceback",
    "bad argument",
)


def validate_lua(exe_path: Path, args: list[str], cwd: Optional[Path] = None, timeout: float = 10.0) -> tuple[bool, str]:
    """Компиляционная проверка Lua-модулей из args через --intercept=0.

    --dry-run НЕ инициализирует Lua, поэтому опечатка в кастомном lua-файле
    (например, zapret-custom.lua) проходит её и валит winws2 при реальном
    запуске.  --intercept=0 загружает и компилирует lua-init-файлы и выходит
    без захвата.  Передаются только lua/blob-токены - без фильтров, поэтому
    хендл WinDivert не трогается даже при работающем другом экземпляре.
    """
    # Собираем полный набор lua/blob-токенов ВМЕСТЕ со значениями: значения
    # у --blob/--lua-init/--lua-gc идут отдельной строкой пресета, и раньше
    # проверка передавала только флаг - валидация blobs была fail-open
    # (ревью 18.10).
    lua_tokens: list[str] = []
    i = 0
    while i < len(args):
        t = args[i]
        if (t.startswith("--lua-init") or t.startswith("--blob")
                or t.startswith("--lua-gc")):
            lua_tokens.append(t)
            if ("=" not in t and i + 1 < len(args)
                    and not args[i + 1].startswith("--")):
                lua_tokens.append(args[i + 1])
                i += 1
        i += 1
    if not lua_tokens:
        return True, ""
    conf = _write_temp_conf(lua_tokens + ["--intercept=0"])
    try:
        r = subprocess.run(
            _winws2_raw_cmdline(exe_path, conf, "--intercept=0"),
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=_winws2_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"winws2 --intercept=0 не выполнился: {e}"
    finally:
        conf.unlink(missing_ok=True)
    output = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
    for line in output.splitlines():
        stripped = line.strip()
        if any(marker in stripped for marker in _LUA_ERROR_MARKERS):
            return False, f"winws2: ошибка Lua: {stripped}"
    return True, ""


def build_args_from_preset(
    root_dir: Path,
    lua_dir: Path,
    blobs_dir: Path,
    preset_path: Path,
    lists_dir: Optional[Path] = None,
    windivert_dir: Optional[Path] = None,
    debug: bool = False,
    game_filter_mode: str = "off",
    discord_voice: bool = False,
    discord_voice_mode: str = "",
    autohostlist: bool = False,
    ipset_catchall: bool = False,
    fake_blob: str = "",
    discord_alt: bool = False,
    ipset_include_file: Optional[Path] = None,
) -> list[str]:
    """Читает .txt пресет и возвращает токены командной строки.

    Тонкий оркестратор: core.preset_parse (чтение и подстановки пресета) +
    core.args_transforms.PIPELINE (постобработки; порядок критичен и
    зафиксирован списком). Раньше всё это была одна функция на 380 строк.

    Публичная сигнатура стабильна: её зовут build_lite/build_portable и
    server._prepare_service_args (аудит #4, инварианты §7).
    """
    if lists_dir is None:
        lists_dir = root_dir / "lists"
    if windivert_dir is None:
        windivert_dir = root_dir / "windivert"
    game_on = game_filter_mode != "off"
    # Discord Voice: legacy bool + новый селект. Неизвестное значение -> off.
    voice_mode = (discord_voice_mode or ("fake" if discord_voice else "off")).strip().lower()
    if voice_mode not in ("off", "fake", "udplen"):
        voice_mode = "off"

    auto_path = ""
    if autohostlist:
        auto_file = lists_dir / "zapret-auto.txt"
        if not auto_file.exists():
            auto_file.write_text("", encoding="utf-8")
        auto_path = str(auto_file)

    # User IP-include/exclude: только НЕПУСТОЙ файл меняет args - пустой не
    # должен трогать конфиг вообще (байт-в-байт прежний default). Exclude
    # всегда сильнее include (ipset.c проверяет ips_exclude первым) - без
    # этой связки редактор «IP-сети - исключения» писал в файл, который
    # winws2 никогда не получал.
    if ipset_include_file is None:
        ipset_inc_file = lists_dir / "ipset-include-user.txt"
    else:
        # Верификация ipset-кандидатов: пробные IP - во ВРЕМЕННОМ файле,
        # пользовательский ipset-include-user.txt не трогаем (ревью 18.10:
        # crash/гонка могли оставить пробные IP или затереть правку юзера).
        ipset_inc_file = Path(ipset_include_file)
    ipset_inc_path = str(ipset_inc_file) if list_health.read_entries(ipset_inc_file) else ""
    ipset_excl_file = lists_dir / "ipset-exclude-user.txt"
    ipset_excl_path = str(ipset_excl_file) if list_health.read_entries(ipset_excl_file) else ""

    tokens = preset_parse.parse_preset(
        preset_path, lists_base=str(lists_dir), lua_dir=lua_dir,
        blobs_dir=blobs_dir, windivert_dir=windivert_dir, game_on=game_on,
        ipset_catchall=ipset_catchall, autohostlist=autohostlist,
        auto_path=auto_path, ipset_inc_path=ipset_inc_path,
        ipset_excl_path=ipset_excl_path)
    ctx = args_transforms.ArgsCtx(
        root_dir=root_dir, lua_dir=lua_dir, blobs_dir=blobs_dir,
        lists_dir=lists_dir, windivert_dir=windivert_dir,
        game_filter_mode=game_filter_mode, voice_mode=voice_mode, debug=debug,
        fake_blob=fake_blob, autohostlist=autohostlist,
        ipset_catchall=ipset_catchall, discord_alt=discord_alt,
        auto_path=auto_path, ipset_inc_path=ipset_inc_path,
        ipset_excl_path=ipset_excl_path)
    for step in args_transforms.PIPELINE:
        tokens = step(tokens, ctx)
    return tokens


def write_run_bat(
    root_dir: Path,
    bat_path: Path,
    exe_path: Path,
    args: list[str],
) -> None:
    """Пишет .bat, запускающий winws2 через `start /min` (аргументы - из conf).

    Как и в прямом запуске, аргументы идут через logs/run.conf: bat не зависит
    от длины и кавычек аргументов. Короткие пути убирают не-ASCII из ASCII-bat.
    """
    conf = write_run_conf(root_dir, args)
    short_exe = short_path(exe_path)
    short_root = short_path(root_dir)
    short_conf = short_path(conf)
    body = (f'cd /d "{short_root}"\r\n'
            f'start "zapret2" /min "{short_exe}" @"{short_conf}"\r\n')
    # ASCII-bat: если 8.3-короткие пути получились не-ASCII (8.3 выключен +
    # кириллица в пути), ascii+replace раньше молча ломал путь. Фолбэк -
    # UTF-8 без BOM + chcp 65001 (правило .bat), иначе оставляем ASCII.
    if body.isascii():
        bat_path.write_text("@echo off\r\n" + body, encoding="ascii")
    else:
        bat_path.write_text("@echo off\r\nchcp 65001 >nul\r\n" + body,
                            encoding="utf-8")


def _arg_path_token(t: str) -> str:
    """Путь к файлу из токена аргументов (@-файлы, blobs, hostlist/ipset)."""
    if t.startswith("@") and "\\" in t:
        return t[1:]
    if ":@" in t:
        return t.split(":@", 1)[1]
    if "=@" in t:
        return t.split("=@", 1)[1]
    if t.startswith("--") and "=" in t and "\\" in t:
        return t.split("=", 1)[1]
    return ""


def _launch_preflight(root_dir: Path, exe_path: Path, args: list[str],
                      method: str) -> tuple[bool, str]:
    """Префлайт запуска + запись в операционный лог (logs/zapret2.log).

    Разбор «у кого-то запускается, у кого-то нет» без пользователя у экрана:
    фиксируем frozen-раскладку, наличие exe, число и суммарную длину
    аргументов, пустые аргументы, битые @-пути (lua/blob/hostlist/ipset).
    Фатально: нет exe или пустой аргумент (стратегия/тоггл сгенерил "").
    """
    import sys as _sys
    exe_ok = exe_path.is_file()
    empties = [i for i, a in enumerate(args) if not str(a)]
    cmdlen = sum(len(str(a)) + 1 for a in args) + len(str(exe_path)) + 1
    _applog("launch", f"preflight[{method}]: frozen={bool(getattr(_sys, 'frozen', False))} "
                      f"exe={exe_path} exists={exe_ok} cwd={root_dir} "
                      f"args={len(args)} cmdlen={cmdlen} empty={len(empties)}")
    checked = 0
    missing: list[str] = []
    for i, a in enumerate(args):
        p = _arg_path_token(str(a))
        if not p:
            continue
        checked += 1
        if not Path(p).exists():
            missing.append(f"#{i}={a}")
    if checked or missing:
        tail = f" -> {'; '.join(missing[:5])}" if missing else ""
        _applog("launch", f"preflight[{method}]: paths checked={checked} "
                          f"missing={len(missing)}{tail}")
    if not exe_ok:
        return False, f"winws2.exe не найден: {exe_path}"
    if empties:
        i = empties[0]
        ctx = [str(x) for x in args[max(0, i - 3):i + 2]]
        return False, (f"пустой аргумент #{i} (рядом: {ctx}) - стратегия или "
                       f"тоггл формирует пустую строку")
    return True, ""


def _prepare_winws2_launch(root_dir: Path) -> None:
    """Драйвер + SeLoadDriverPrivilege до запуска (общее для direct и bat).

    CreateProcess наследует ТЕКУЩИЙ токен: у UAC-elevated Python привилегия
    часто выключена, без неё WinDivert не грузится.
    """
    try:
        from core.utils import fix_stale_windivert_services
        fix_stale_windivert_services(root_dir)
    except Exception:
        pass
    if "SeLoadDriverPrivilege" not in get_enabled_privileges():
        enable_privilege("SeLoadDriverPrivilege")
        enable_privilege("SeDebugPrivilege")
    privs = get_enabled_privileges()
    if "SeLoadDriverPrivilege" not in privs:
        _applog("launch", f"WARN: SeLoadDriverPrivilege OFF (privs={privs})")
    else:
        _applog("launch", "SeLoadDriverPrivilege ON")
    # Пауза на случай перезапуска сразу после taskkill.
    time.sleep(0.5)


def _wait_winws2_alive(timeout: float,
                       proc: Optional[subprocess.Popen] = None) -> bool:
    """Ждёт появления winws2.exe в tasklist (только по имени образа)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False  # процесс уже упал - ждать нечего
        from core.proc import image_running
        if image_running("winws2.exe", timeout=3):
            return True
        time.sleep(0.2)
    return False


def launch_winws2_direct(root_dir: Path, exe_path: Path, args: list[str],
                         timeout: float = 5.0,
                         ) -> tuple[Optional[subprocess.Popen], str]:
    """Прямой запуск winws2.exe через @config_file. -> (proc | None, ошибка).

    Аргументы пишутся в logs/run.conf, командная строка - `"exe" @"conf"`:
    @file раскрывает Cygwin-рантайм ещё до main() (это снимает лимиты длины
    cmd 8191/CreateProcess), кавычки стоят ПОСЛЕ @ (см. _winws2_raw_cmdline).
    stdout/stderr winws2 пишутся в logs/winws2_last_stderr.log (PIPE без
    чтения использовать нельзя - deadlock на полном буфере).
    """
    ok, msg = _launch_preflight(root_dir, exe_path, args, "direct")
    if not ok:
        _applog("launch", f"preflight FAIL: {msg}")
        return None, msg
    try:
        conf = write_run_conf(root_dir, args)
    except OSError as e:
        _applog("launch", f"run.conf write FAIL: {e!r}")
        return None, f"run.conf: {e}"
    _prepare_winws2_launch(root_dir)
    sink = None
    try:
        sink = open(root_dir / "logs" / "winws2_last_stderr.log", "wb")
    except OSError:
        sink = None
    kw: dict = dict(cwd=str(root_dir),
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    close_fds=True, env=_winws2_env())
    if sink is not None:
        kw.update(stdout=sink, stderr=subprocess.STDOUT)
    try:
        proc = subprocess.Popen(
            _winws2_raw_cmdline(exe_path, conf),
            executable=str(exe_path),
            **kw,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _applog("launch", f"direct Popen FAIL: {e!r}")
        return None, f"Popen: {e}"
    finally:
        if sink is not None:
            sink.close()
    _applog("launch", f"direct Popen ok pid={proc.pid} conf=logs/{conf.name}")
    return proc, ""


def launch_winws2(root_dir: Path, exe_path: Path, args: list[str],
                  timeout: float = 5.0) -> tuple[bool, Optional[subprocess.Popen]]:
    """Умный запуск: прямой Popen (основной) -> bat (аварийный фолбэк).

    Возвращает (ok, proc): proc - УПРАВЛЯЕМЫЙ процесс прямого запуска (для
    PID-остановки и ожидания выхода, ревью-раунд 3/P1-1); bat-фолбэк даёт
    (ok, None) - запуск неуправляем (PID неизвестен, пишем в лог).
    """
    proc, err = launch_winws2_direct(root_dir, exe_path, args, timeout)
    if proc is not None and _wait_winws2_alive(timeout, proc):
        _applog("launch", "direct OK: winws2 жив")
        return True, proc
    if proc is not None and proc.poll() is None:
        # процесс жив, но tasklist его не увидел - не плодим дубль
        _applog("launch", "direct: процесс жив, tasklist без winws2 - успех")
        return True, proc
    if proc is not None:
        _applog("launch", f"direct FAIL: winws2 упал rc={proc.returncode}")
    elif err:
        _applog("launch", f"direct FAIL: {err}")
    tail = _read_stderr_sink(root_dir)
    if tail:
        _applog("launch", f"winws2 stderr: {tail}")
    bat = root_dir / "_zapret_run.bat"
    write_run_bat(root_dir, bat, exe_path, args)
    ok = launch_winws2_bat(bat, root_dir, timeout=timeout)
    _applog("launch", f"bat fallback: {'OK' if ok else 'FAIL'} (unmanaged: PID неизвестен)")
    return ok, None


def launch_winws2_bat(
    bat_path: Path,
    root_dir: Path,
    timeout: float = 5.0,
) -> bool:
    """Запускает .bat с winws2, включив SeLoadDriverPrivilege (аварийный путь)."""
    _prepare_winws2_launch(root_dir)
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            cwd=str(root_dir),
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    except (OSError, subprocess.SubprocessError) as e:
        _applog("launch-bat", f"Popen cmd FAIL: {e!r}")
        return False
    ok = _wait_winws2_alive(timeout)
    _applog("launch-bat", f"winws2 {'жив' if ok else 'НЕ появился'} ({timeout}s)")
    return ok