import re
import subprocess
import time
from pathlib import Path
from typing import Optional


SERVICE_NAME = "zapret2"

# Короткий TTL-кэш состояния службы: фронтенд поллит /api/service/status каждые
# ~9с, а sc query — это подпроцесс. Сбрасывается на любой мутирующей операции
# (install/remove/start/stop/reconfigure) — как PID-кэш в контроллере (§28).
_STATUS_TTL = 10.0
_status_cache_at = 0.0
_status_cache_value: Optional[str] = None
_installed_cache_at = 0.0
_installed_cache_value: Optional[bool] = None


def _invalidate_service_cache() -> None:
    global _status_cache_at, _status_cache_value, _installed_cache_at, _installed_cache_value
    _status_cache_at = 0.0
    _status_cache_value = None
    _installed_cache_at = 0.0
    _installed_cache_value = None


def _sc(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["sc"] + args,
            capture_output=True, text=True, encoding="oem", errors="replace", timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return -1, "sc not found"


def _taskkill_winws2():
    subprocess.run(
        ["taskkill", "/F", "/IM", "winws2.exe"],
        capture_output=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _winws2_running() -> bool:
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq winws2.exe"],
        capture_output=True, text=True, encoding="oem", errors="replace", timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    # if winws2.exe appears in output (not just the header), it's running
    return "winws2.exe" in r.stdout and "No tasks" not in r.stdout


def is_installed() -> bool:
    global _installed_cache_at, _installed_cache_value
    now = time.time()
    if _installed_cache_value is not None and now - _installed_cache_at < _STATUS_TTL:
        return _installed_cache_value
    # Один sc query обслуживает оба кэша: status() сам ходит в SCM.
    _installed_cache_value = status() != "not_installed"
    _installed_cache_at = now
    return _installed_cache_value


def status() -> str:
    global _status_cache_at, _status_cache_value
    now = time.time()
    if _status_cache_value is not None and now - _status_cache_at < _STATUS_TTL:
        return _status_cache_value
    code, out = _sc(["query", SERVICE_NAME])
    if code != 0:
        _status_cache_value = "not_installed"
    else:
        # Parse SCM state from sc query output.  The header is localized
        # ("STATE" is "СОСТОЯНИЕ" on Russian Windows), but the VALUE is always
        # English ("4  RUNNING") — search the value, not the label.
        upper = out.upper()
        _status_cache_value = "running" if "RUNNING" in upper else "stopped"
    _status_cache_at = now
    return _status_cache_value


def _zapret1_service_exists() -> bool:
    code, _ = _sc(["query", "zapret"])
    return code == 0


def _service_cmdline(exe: Path, args: list[str]) -> str:
    """binPath value in the Zapret 1 format: \"exe\" \"arg\" ... — the
    backslash-quotes are processed by cmd.exe's line parser, exactly like
    v1's service.bat.  Passing plain quotes via argv makes sc drop the
    image path or store the escaped form literally."""
    parts = [f'\\"{exe}\\"']
    parts += [f'\\"{a}\\"' if " " in a else a for a in args]
    return " ".join(parts)


def _read_stored_binpath() -> str:
    """Stored binPath of the service (locale-independent via CIM)."""
    ps = ("(Get-CimInstance Win32_Service -Filter \"Name='%s'\").PathName"
          % SERVICE_NAME)
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True, text=True, encoding="oem", errors="replace", timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW)
    return (r.stdout or "").strip()


def _path_from_token(t: str) -> Optional[str]:
    """Extract a filesystem path from an args token, if it carries one."""
    if "@" in t and "\\" in t:
        return t.split("@", 1)[1]
    if "=" in t and "\\" in t:
        return t.split("=", 1)[1]
    if "--blob" in t and not t.startswith("--blob"):
        return None
    return None


def _verify_binpath(exe: Path, args: list[str]) -> tuple[bool, str]:
    """Confirm SCM stored the full command line.  Old/broken Win10 SCM could
    mangle binPath silently (случай кривой установки 2026-09-12) — validate
    counts and that every path token still points at an existing file."""
    stored = _read_stored_binpath()
    if not stored:
        return False, "binPath пуст — SCM не сохранил командную строку"
    s = stored.replace('\\"', '"')
    tokens = [m.group(1) if m.group(1) is not None else m.group(2)
              for m in re.finditer(r'"([^"]*)"|(\S+)', s)]
    if len(tokens) != 1 + len(args):
        return False, (f"binPath содержит {len(tokens)} аргументов вместо "
                       f"{1 + len(args)} — часть командной строки потеряна "
                       f"(нестандартный путь установки?)")
    for t in tokens[1:]:
        p = _path_from_token(t)
        if p and not Path(p).exists():
            return False, f"путь из binPath не существует: {p} — установка кривая"
    return True, ""


def _sc_run_bat(lines: list[str]) -> tuple[int, str]:
    """Run sc via a temporary .bat — the only faithful way to pass the
    v1-style binPath with backslash-quotes (cmd's line parser handles
    them; argv and even cmd /c <string> mangle them)."""
    import tempfile
    bat = Path(tempfile.gettempdir()) / "zapret2_svc.bat"
    # OEM (cp866 на русской Windows) — cmd читает bat в кодовой странице
    # консоли; ascii ронял установку у пользователей с кириллицей в пути
    # (UnicodeEncodeError — случай 2026-09-12).
    try:
        bat.write_text("\r\n".join(["@echo off"] + lines) + "\r\n", encoding="oem")
    except UnicodeEncodeError:
        bat.write_text("\r\n".join(["@echo off"] + lines) + "\r\n", encoding="utf-8")
    try:
        r = subprocess.run(
            ["cmd.exe", "/c", str(bat)],
            capture_output=True, text=True, encoding="oem", errors="replace", timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, "cmd failed"
    finally:
        try:
            bat.unlink()
        except OSError:
            pass


def _winws_running() -> bool:
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq winws.exe"],
        capture_output=True, text=True, encoding="oem", errors="replace", timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "winws.exe" in r.stdout and "No tasks" not in r.stdout


def _zapret1_conflict() -> Optional[str]:
    """Reason why Zapret 1 blocks the operation, or None when it's free."""
    if _zapret1_service_exists():
        return "Обнаружена служба Zapret 1 (zapret). Удалите её через service.bat от Zapret 1."
    if _winws_running():
        return "Zapret 1 (winws.exe) запущен. Остановите его перед запуском Zapret 2."
    return None


def install(root_dir: Optional[Path] = None, args: Optional[list[str]] = None) -> tuple[bool, str]:
    conflict = _zapret1_conflict()
    if conflict:
        return False, conflict
    _invalidate_service_cache()
    remove()
    time.sleep(0.5)
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent
    exe = Path(root_dir) / "bin" / "winws2.exe"
    if not exe.exists():
        exe = Path(root_dir) / "winws2.exe"
    if not exe.exists():
        return False, "winws2.exe не найден"
    if args is None:
        args = []
    # winws2.exe is the service binary DIRECTLY (like Zapret 1's service.bat:
    # binPath = "winws.exe <args>", start= auto).  A cmd.exe /C bat wrapper
    # is what Defender's behavior analytics flags as suspicious — the direct
    # binary matches the reputable zapret ecosystem and does not trigger.
    cmdline = _service_cmdline(exe, args)
    code, out = _sc_run_bat([
        f'sc create {SERVICE_NAME} binPath= "{cmdline}" '
        f'DisplayName= "Zapret 2 DPI Bypass" start= auto',
    ])
    if code != 0:
        return False, f"sc create failed: {out.strip()}"
    _sc(["description", SERVICE_NAME, "zapret DPI bypass (Zapret 2)"])
    # Verify BEFORE start: old/broken SCM может молча исказить binPath
    # (аргументы по пробелам рвутся, кириллические пути не читаются) —
    # тогда служба «стоит», но обхода нет и автозапуск валится.
    okv, msgv = _verify_binpath(exe, args)
    if not okv:
        remove()
        return False, f"Установка отменена (кривой binPath): {msgv}"
    # SCM recovery: если winws2 умрёт (случай 2026-09-12: три падения за утро,
    # обход пропадал до ручного перезапуска) — перезапустить службу через 60 с.
    _sc(["failure", SERVICE_NAME,
         "reset=", "86400",
         "actions=", "restart/60000/restart/60000/restart/60000"])
    start(args)
    return True, "Служба zapret2 установлена"


def reconfigure(args: list[str]) -> tuple[bool, str]:
    """Refresh the service's binPath with the current args (strategy changes
    require re-applying the command line — direct-exe services bake it in)."""
    _invalidate_service_cache()
    root_dir = Path(__file__).resolve().parent.parent
    exe = root_dir / "bin" / "winws2.exe"
    if not exe.exists():
        exe = root_dir / "winws2.exe"
    cmdline = _service_cmdline(exe, args)
    code, out = _sc_run_bat([f'sc config {SERVICE_NAME} binPath= "{cmdline}"'])
    if code != 0:
        return False, f"sc config failed: {out.strip()}"
    return True, "Параметры службы обновлены"


def remove():
    _invalidate_service_cache()
    _sc(["stop", SERVICE_NAME])
    _taskkill_winws2()
    time.sleep(0.5)
    _sc(["delete", SERVICE_NAME])
    return True, "Служба zapret2 удалена"


def start(args: Optional[list[str]] = None):
    conflict = _zapret1_conflict()
    if conflict:
        return False, conflict
    _invalidate_service_cache()
    from core.tcp_timestamps import enable_for_engine
    enable_for_engine()
    stop()
    # Даём SCM время закрыть состояние (иначе первый sc start может дать 1053).
    time.sleep(0.5)
    if args:
        reconfigure(args)
    code, out = _sc(["start", SERVICE_NAME])
    if code != 0:
        return False, f"sc start failed: {out.strip()}"
    return True, "winws2 запущен"


def stop():
    # Сначала — корректный sc stop (SCM состояние), taskkill как страховка
    # для вручную запущенного winws2.
    _invalidate_service_cache()
    _sc(["stop", SERVICE_NAME])
    _taskkill_winws2()
    return True, "winws2 остановлен"
