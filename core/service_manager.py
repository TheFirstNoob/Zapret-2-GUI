import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from core.utils import app_root, run_sc as _sc


SERVICE_NAME = "zapret2"

# Короткий TTL-кэш состояния службы: фронтенд поллит /api/service/status
# каждые ~9с, а sc query — подпроцесс. Сбрасывается на любой мутирующей
# операции (install/remove/start/stop/reconfigure).
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


def _taskkill_winws2():
    subprocess.run(
        ["taskkill", "/F", "/IM", "winws2.exe"],
        capture_output=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


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
        # Парсим ЗНАЧЕНИЕ из sc query: заголовок локализован («STATE» —
        # «СОСТОЯНИЕ» на русской Windows), но значение всегда английское
        # ("4  RUNNING") — ищем значение, не подпись.
        upper = out.upper()
        _status_cache_value = "running" if "RUNNING" in upper else "stopped"
    _status_cache_at = now
    return _status_cache_value


def _zapret1_service_exists() -> bool:
    code, _ = _sc(["query", "zapret"])
    return code == 0


def _service_cmdline(exe: Path, args: list[str]) -> str:
    """binPath в формате Zapret 1: \"exe\" \"arg\" ... — обратные слэш-кавычки
    обрабатываются парсером cmd.exe, ровно как в v1's service.bat. Обычные
    кавычки через argv заставляют sc ронять путь или хранить экранированный
    вид буквально."""
    parts = [f'\\"{exe}\\"']
    parts += [f'\\"{a}\\"' if " " in a else a for a in args]
    return " ".join(parts)


def _read_stored_binpath() -> str:
    """Сохранённый binPath службы (locale-independent через CIM)."""
    ps = ("(Get-CimInstance Win32_Service -Filter \"Name='%s'\").PathName"
          % SERVICE_NAME)
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True, text=True, encoding="oem", errors="replace", timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW)
    return (r.stdout or "").strip()


def _path_from_token(t: str) -> Optional[str]:
    """Путь к файлу из токена аргументов, если он там есть."""
    if "@" in t and "\\" in t:
        return t.split("@", 1)[1]
    if "=" in t and "\\" in t:
        return t.split("=", 1)[1]
    if "--blob" in t and not t.startswith("--blob"):
        return None
    return None


def _verify_binpath(exe: Path, args: list[str]) -> tuple[bool, str]:
    """Проверяет, что SCM сохранил всю командную строку: старый/кривой SCM
    Win10 мог молча исказить binPath (случай кривой установки 2026-09-12) —
    сверяем число аргументов и существование всех путей."""
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
    """sc через временный .bat — единственный способ честно передать
    v1-style binPath с backslash-кавычками (их понимает парсер cmd;
    argv и даже cmd /c <string> их искажают)."""
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
    """Причина, по которой Zapret 1 блокирует операцию, или None."""
    if _zapret1_service_exists():
        return "Обнаружена служба Zapret 1 (zapret). Удалите её через service.bat от Zapret 1."
    if _winws_running():
        return "Zapret 1 (winws.exe) запущен. Остановите его перед запуском Zapret 2."
    return None


def _taskkill_winws() -> bool:
    """Остановить winws.exe (Zapret 1). True, если процесс был снят."""
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/IM", "winws.exe"], capture_output=True,
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def zapret1_cleanup() -> tuple[bool, str]:
    """Остановить и удалить службу Zapret 1 (zapret) + winws.exe — как
    «Remove Services» в service.bat Flowseal-бандла. Вызывается только после
    ЯВНОГО подтверждения пользователя во фронтенде."""
    actions: list[str] = []
    code, _out = _sc(["query", "zapret"])
    if code == 0:
        _sc(["stop", "zapret"])
        code, out = _sc(["delete", "zapret"])
        if code != 0:
            if "1072" in out or "отмечен" in out.lower():
                return False, "Служба zapret помечена на удаление — нужна перезагрузка"
            return False, f"Не удалось удалить службу zapret: {out.strip()[:120]}"
        actions.append("служба zapret удалена")
    if _winws_running() and _taskkill_winws():
        actions.append("winws.exe остановлен")
    if not actions:
        return True, "Zapret 1 не обнаружен"
    return True, ", ".join(actions)


def repair(root_dir: Optional[Path] = None) -> dict:
    """Починить службу драйвера WinDivert (repair ImagePath / включить
    disabled) и сообщить о конфликте с Zapret 1. Без удаления чужих служб."""
    actions: list[str] = []
    try:
        from core.utils import fix_stale_windivert_services
        actions += fix_stale_windivert_services(root_dir)
    except Exception as e:
        actions.append(f"ошибка починки драйвера: {e}")
    return {
        "actions": actions,
        "reboot_required": any("перезагруз" in a for a in actions),
        "zapret1": _zapret1_conflict(),
    }


def install(root_dir: Optional[Path] = None, args: Optional[list[str]] = None,
            cleanup_zapret1: bool = False) -> tuple[bool, str]:
    conflict = _zapret1_conflict()
    if conflict:
        if not cleanup_zapret1:
            return False, conflict
        ok_c, msg_c = zapret1_cleanup()
        if not ok_c:
            return False, msg_c
        conflict = _zapret1_conflict()
        if conflict:
            return False, conflict
    _invalidate_service_cache()
    remove()
    time.sleep(0.5)
    if root_dir is None:
        root_dir = app_root()
    # Драйвер лечим ПОСЛЕ остановки winws2 (кейс 2026-09-13): править или
    # удалять службу драйвера при живых хендлах нельзя — она получит
    # «marked for deletion» (1072) и починится только перезагрузкой.
    try:
        from core.utils import fix_stale_windivert_services
        fix_stale_windivert_services(root_dir)
    except Exception:
        pass
    exe = Path(root_dir) / "bin" / "winws2.exe"
    if not exe.exists():
        exe = Path(root_dir) / "winws2.exe"
    if not exe.exists():
        return False, "winws2.exe не найден"
    if not str(exe.resolve()).lower().startswith(str(app_root()).lower()):
        return False, f"winws2.exe вне каталога программы: {exe}"
    if args is None:
        args = []
    # winws2.exe — бинарник службы НАПРЯМУЮ (как service.bat у Zapret 1:
    # binPath = "winws.exe <args>", start= auto). cmd-обёртка — то, что
    # поведенческие детекты Defender помечают подозрительным.
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
    """Обновляет binPath службы текущими args (служба запускает exe напрямую,
    поэтому смена стратегии требует перезаписи командной строки)."""
    _invalidate_service_cache()
    root_dir = app_root()
    exe = root_dir / "bin" / "winws2.exe"
    if not exe.exists():
        exe = root_dir / "winws2.exe"
    if not str(exe.resolve()).lower().startswith(str(app_root()).lower()):
        return False, f"winws2.exe вне каталога программы: {exe}"
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
    # Драйвер мог сломаться между запусками (кейс 2026-09-13) — лечим до
    # sc start, иначе winws2 упадёт на WinDivertOpen.
    try:
        from core.utils import fix_stale_windivert_services
        fix_stale_windivert_services(app_root())
    except Exception:
        pass
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


# ── SCM-recovery: пауза/возобновление (2026-09-12) ─────────────────
# Тестер/сканы гасят winws2 на весь прогон. Если SCM-recovery активен, он
# через 60с ПЕРЕЗАПУСКАЕТ службовый winws2 посреди теста → конфликт
# WinDivert, обрыв прогона. На время управляемых остановок recovery
# выключается и включается обратно после восстановления.
_recovery_paused: bool = False
_recovery_was_on: bool = False
_recovery_lock = threading.Lock()


def pause_recovery() -> None:
    """Не бросает исключений: зависший sc.exe не должен ронять worker (L4)."""
    global _recovery_paused, _recovery_was_on
    with _recovery_lock:
        if _recovery_paused:
            return
        try:
            code, out = _sc(["qfailure", SERVICE_NAME])
            _recovery_was_on = code == 0 and (
                "restart" in (out or "").lower()
                or "перезапуск" in (out or "").lower())
            _sc(["failure", SERVICE_NAME, "reset=", "0", "actions=", ""])
            _recovery_paused = True
        except Exception:
            pass


def resume_recovery() -> None:
    global _recovery_paused
    with _recovery_lock:
        if not _recovery_paused:
            return
        try:
            if _recovery_was_on:
                _sc(["failure", SERVICE_NAME, "reset=", "86400",
                     "actions=", "restart/60000/restart/60000/restart/60000"])
        finally:
            _recovery_paused = False