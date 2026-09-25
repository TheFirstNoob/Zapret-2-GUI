import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from core.utils import app_root, run_sc as _sc
from core.applog import log as _applog


SERVICE_NAME = "zapret2"

# Короткий TTL-кэш состояния службы: фронтенд поллит /api/service/status
# каждые ~9с, а sc query - подпроцесс. Сбрасывается на любой мутирующей
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


def _svc_log(msg: str) -> None:
    """Операционный лог службы (logs/zapret2.log) - разбор без GUI."""
    _applog("service", msg)


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
        # Парсим ЗНАЧЕНИЕ из sc query: заголовок локализован («STATE» -
        # «СОСТОЯНИЕ» на русской Windows), но значение всегда английское
        # ("4  RUNNING") - ищем значение, не подпись.
        upper = out.upper()
        _status_cache_value = "running" if "RUNNING" in upper else "stopped"
    _status_cache_at = now
    return _status_cache_value


def _zapret1_service_exists() -> bool:
    code, _ = _sc(["query", "zapret"])
    return code == 0


def _service_cmdline(exe: Path, args: list[str]) -> str:
    """binPath в формате Zapret 1: \"exe\" \"arg\" ... - обратные слэш-кавычки
    обрабатываются парсером cmd.exe, ровно как в v1's service.bat. Обычные
    кавычки через argv заставляют sc ронять путь или хранить экранированный
    вид буквально."""
    parts = [f'\\"{exe}\\"']
    parts += [f'\\"{a}\\"' if " " in a else a for a in args]
    return " ".join(parts)


def _read_stored_binpath() -> str:
    """Сохранённый binPath: читаем ImagePath НАПРЯМУЮ из реестра.

    sc qc / CIM (QueryServiceConfig) ломается на длинных ImagePath: SCM
    хранит путь целиком, но штатное чтение падает (1734 «array bounds
    invalid» у sc, пустой PathName у CIM) начиная с ~4 КБ. Случай
    2026-09-25: игровые правила удлинили binPath до ~4.1 КБ - установка
    объявляла «binPath пуст - SCM не сохранил» и удаляла РАБОЧУЮ службу.
    Реестр возвращает значение любой длины и не зависит от локали.
    """
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}") as key:
            value, _type = winreg.QueryValueEx(key, "ImagePath")
            return str(value).strip()
    except OSError as e:
        _svc_log(f"registry ImagePath read failed: {e}")
        return ""


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
    Win10 мог молча исказить binPath (случай кривой установки 2026-09-12) -
    сверяем число аргументов и существование всех путей."""
    stored = _read_stored_binpath()
    if not stored:
        return False, "binPath пуст - SCM не сохранил командную строку"
    s = stored.replace('\\"', '"')
    tokens = [m.group(1) if m.group(1) is not None else m.group(2)
              for m in re.finditer(r'"([^"]*)"|(\S+)', s)]
    if len(tokens) != 1 + len(args):
        return False, (f"binPath содержит {len(tokens)} аргументов вместо "
                       f"{1 + len(args)} - часть командной строки потеряна "
                       f"(нестандартный путь установки?)")
    for t in tokens[1:]:
        p = _path_from_token(t)
        if p and not Path(p).exists():
            return False, f"путь из binPath не существует: {p} - установка кривая"
    return True, ""


def _sc_run_bat(lines: list[str]) -> tuple[int, str]:
    """sc через временный .bat - единственный способ честно передать
    v1-style binPath с backslash-кавычками (их понимает парсер cmd;
    argv и даже cmd /c <string> их искажают)."""
    import tempfile
    bat = Path(tempfile.gettempdir()) / "zapret2_svc.bat"
    # OEM (cp866 на русской Windows) - cmd читает bat в кодовой странице
    # консоли; ascii ронял установку у пользователей с кириллицей в пути
    # (UnicodeEncodeError - случай 2026-09-12).
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
        out = (r.stdout or "") + (r.stderr or "")
        _svc_log(f"sc-bat rc={r.returncode}: {' | '.join(lines)} "
                 f"out={out.strip()[:400]!r}")
        return r.returncode, out
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, "cmd failed"
    finally:
        try:
            bat.unlink()
        except OSError:
            pass


def _service_binpath(exe: Path, args: list[str]) -> str:
    """binPath с ОБЫЧНЫМИ кавычками (для Win32 API): \"exe\" \"arg\" arg.

    API/SCM хранят строку дословно - v1-стиль с backslash-кавычками нужен
    только транспорту через cmd/bat (sc create), см. _service_cmdline.
    """
    parts = [f'"{exe}"']
    parts += [f'"{a}"' if " " in a else a for a in args]
    return " ".join(parts)


def _win32_advapi():
    """ctypes-обвязка advapi32 (SCM) - API вместо sc.exe/cmd для службы."""
    import ctypes
    import ctypes.wintypes as wt
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    adv.OpenSCManagerW.restype = wt.HANDLE
    adv.OpenSCManagerW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, wt.DWORD]
    adv.OpenServiceW.restype = wt.HANDLE
    adv.OpenServiceW.argtypes = [wt.HANDLE, wt.LPCWSTR, wt.DWORD]
    adv.CloseServiceHandle.argtypes = [wt.HANDLE]
    return ctypes, wt, adv


def _win32_create_service(binpath: str) -> tuple[bool, str]:
    """Создать службу напрямую через CreateServiceW (без cmd/bat/кавычек).

    sc+bat - источник «у кого-то ставится, у кого-то нет» (парсер cmd,
    кодировка, кавычки, temp-файл). API принимает строку как есть.
    """
    try:
        ctypes, wt, adv = _win32_advapi()
    except Exception as e:  # noqa: BLE001
        return False, f"ctypes init: {e}"
    SC_MANAGER_CREATE_SERVICE = 0x0002
    SERVICE_ALL_ACCESS = 0xF01FF
    SERVICE_WIN32_OWN_PROCESS = 0x10
    SERVICE_AUTO_START = 0x2
    SERVICE_ERROR_NORMAL = 0x1
    adv.CreateServiceW.restype = wt.HANDLE
    adv.CreateServiceW.argtypes = [
        wt.HANDLE, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.DWORD,
        wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, ctypes.POINTER(wt.DWORD),
        wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR]
    scm = adv.OpenSCManagerW(None, None, SC_MANAGER_CREATE_SERVICE)
    if not scm:
        err = ctypes.get_last_error()
        return False, f"OpenSCManager: {err} {ctypes.FormatError(err)}"
    try:
        h = adv.CreateServiceW(
            scm, SERVICE_NAME, "Zapret 2 DPI Bypass", SERVICE_ALL_ACCESS,
            SERVICE_WIN32_OWN_PROCESS, SERVICE_AUTO_START,
            SERVICE_ERROR_NORMAL, binpath, None, None, None, None, None)
        if not h:
            err = ctypes.get_last_error()
            return False, f"CreateService: {err} {ctypes.FormatError(err)}"
        adv.CloseServiceHandle(h)
        return True, ""
    finally:
        adv.CloseServiceHandle(scm)


def _win32_change_service(binpath: str) -> tuple[bool, str]:
    """Перезаписать binPath через ChangeServiceConfigW (аналог sc config)."""
    try:
        ctypes, wt, adv = _win32_advapi()
    except Exception as e:  # noqa: BLE001
        return False, f"ctypes init: {e}"
    SC_MANAGER_CONNECT = 0x0001
    SERVICE_CHANGE_CONFIG = 0x0002
    SERVICE_NO_CHANGE = 0xFFFFFFFF
    adv.ChangeServiceConfigW.restype = wt.BOOL
    adv.ChangeServiceConfigW.argtypes = [
        wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR,
        ctypes.POINTER(wt.DWORD), wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR,
        wt.LPCWSTR]
    scm = adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not scm:
        err = ctypes.get_last_error()
        return False, f"OpenSCManager: {err} {ctypes.FormatError(err)}"
    try:
        h = adv.OpenServiceW(scm, SERVICE_NAME, SERVICE_CHANGE_CONFIG)
        if not h:
            err = ctypes.get_last_error()
            return False, f"OpenService: {err} {ctypes.FormatError(err)}"
        try:
            ok = adv.ChangeServiceConfigW(
                h, SERVICE_NO_CHANGE, SERVICE_NO_CHANGE, SERVICE_NO_CHANGE,
                binpath, None, None, None, None, None, None)
            if not ok:
                err = ctypes.get_last_error()
                return False, (f"ChangeServiceConfig: {err} "
                               f"{ctypes.FormatError(err)}")
            return True, ""
        finally:
            adv.CloseServiceHandle(h)
    finally:
        adv.CloseServiceHandle(scm)


def _win32_delete_service() -> tuple[bool, str]:
    """Удалить службу через DeleteService (аналог sc delete)."""
    try:
        ctypes, _wt, adv = _win32_advapi()
    except Exception as e:  # noqa: BLE001
        return False, f"ctypes init: {e}"
    SC_MANAGER_CONNECT = 0x0001
    DELETE = 0x10000
    adv.DeleteService.restype = bool
    adv.DeleteService.argtypes = [_wt.HANDLE]
    scm = adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not scm:
        err = ctypes.get_last_error()
        return False, f"OpenSCManager: {err} {ctypes.FormatError(err)}"
    try:
        h = adv.OpenServiceW(scm, SERVICE_NAME, DELETE)
        if not h:
            err = ctypes.get_last_error()
            return False, f"OpenService: {err} {ctypes.FormatError(err)}"
        try:
            if not adv.DeleteService(h):
                err = ctypes.get_last_error()
                return False, f"DeleteService: {err} {ctypes.FormatError(err)}"
            return True, ""
        finally:
            adv.CloseServiceHandle(h)
    finally:
        adv.CloseServiceHandle(scm)


def _winws_running() -> bool:
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq winws.exe"],
        capture_output=True, text=True, encoding="oem", errors="replace", timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "winws.exe" in r.stdout and "No tasks" not in r.stdout


def _winws2_running() -> bool:
    """winws2.exe ещё жив? (tasklist без локале-зависимых строк: ищем имя)."""
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq winws2.exe"],
        capture_output=True, text=True, encoding="oem", errors="replace", timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "winws2.exe" in r.stdout


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
    """Остановить и удалить службу Zapret 1 (zapret) + winws.exe - как
    «Remove Services» в service.bat Flowseal-бандла. Вызывается только после
    ЯВНОГО подтверждения пользователя во фронтенде."""
    actions: list[str] = []
    code, _out = _sc(["query", "zapret"])
    if code == 0:
        _sc(["stop", "zapret"])
        code, out = _sc(["delete", "zapret"])
        if code != 0:
            if "1072" in out or "отмечен" in out.lower():
                return False, "Служба zapret помечена на удаление - нужна перезагрузка"
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
    _svc_log(f"install: args={len(args or [])} cleanup_zapret1={cleanup_zapret1} "
             f"root={root_dir}")
    remove()
    time.sleep(0.5)
    if root_dir is None:
        root_dir = app_root()
    # Драйвер лечим ПОСЛЕ остановки winws2 (кейс 2026-09-13): править или
    # удалять службу драйвера при живых хендлах нельзя - она получит
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
    # winws2.exe - бинарник службы НАПРЯМУЮ (как service.bat у Zapret 1:
    # binPath = "winws.exe <args>", start= auto). cmd-обёртка - то, что
    # поведенческие детекты Defender помечают подозрительным.
    cmdline = _service_cmdline(exe, args)
    native = _service_binpath(exe, args)
    _svc_log(f"install: exe={exe} args={len(args)} cmdline={len(cmdline)}")
    ok_a, det_a = _win32_create_service(native)
    if ok_a:
        _svc_log(f"install: Win32 API create ok (binPath={len(native)})")
    else:
        _svc_log(f"install: Win32 API create failed: {det_a} - fallback sc-bat")
        code, out = _sc_run_bat([
            f'sc create {SERVICE_NAME} binPath= "{cmdline}" '
            f'DisplayName= "Zapret 2 DPI Bypass" start= auto',
        ])
        if code != 0:
            _svc_log(f"install FAIL: sc create rc={code} "
                     f"out={out.strip()[:200]!r}")
            return False, f"sc create failed: {out.strip()}"
    _sc(["description", SERVICE_NAME, "zapret DPI bypass (Zapret 2)"])
    # Verify BEFORE start: old/broken SCM может молча исказить binPath
    # (аргументы по пробелам рвутся, кириллические пути не читаются) -
    # тогда служба «стоит», но обхода нет и автозапуск валится.
    okv, msgv = _verify_binpath(exe, args)
    if not okv:
        _svc_log(f"install FAIL: verify binPath: {msgv}")
        remove()
        return False, f"Установка отменена (кривой binPath): {msgv}"
    # SCM recovery: если winws2 умрёт (случай 2026-09-12: три падения за утро,
    # обход пропадал до ручного перезапуска) - перезапустить службу через 60 с.
    _sc(["failure", SERVICE_NAME,
         "reset=", "86400",
         "actions=", "restart/60000/restart/60000/restart/60000"])
    start(args)
    _svc_log("install OK")
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
    native = _service_binpath(exe, args)
    _svc_log(f"reconfigure: args={len(args)} cmdline={len(cmdline)}")
    ok_a, det_a = _win32_change_service(native)
    if ok_a:
        _svc_log(f"reconfigure: Win32 API change ok (binPath={len(native)})")
    else:
        _svc_log(f"reconfigure: Win32 API change failed: {det_a} - fallback sc-bat")
        code, out = _sc_run_bat([f'sc config {SERVICE_NAME} binPath= "{cmdline}"'])
        if code != 0:
            _svc_log(f"reconfigure FAIL: sc config rc={code} "
                     f"out={out.strip()[:200]!r}")
            return False, f"sc config failed: {out.strip()}"
    # API/sc config могли отрапортовать успех, ничего не записав: сверяем
    # реестр (sc qc/CIM на длинных путях врёт - см. _read_stored_binpath).
    stored = _read_stored_binpath()
    if stored.replace('\\"', '"') != native:
        _svc_log(f"reconfigure FAIL: stored={len(stored)} != native={len(native)}")
        return False, ("sc config не сохранил аргументы дословно - служба "
                       "осталась на старых (запустите переустановку службы)")
    _svc_log("reconfigure OK")
    return True, "Параметры службы обновлены"


def remove():
    _invalidate_service_cache()
    _svc_log("remove: stop+taskkill")
    _sc(["stop", SERVICE_NAME])
    _taskkill_winws2()
    # Живой winws2 держит хендл: sc delete сразу после taskkill оставляет
    # службу «отмеченной для удаления» (1072) - отсюда «удаляется со второго
    # раза». Ждём фактического выхода процесса, затем удаляем с повторами.
    for _ in range(20):
        if not _winws2_running():
            break
        time.sleep(0.25)
    else:
        _svc_log("remove: winws2 ещё жив после 5с ожидания")
    ok_d, det_d = _win32_delete_service()
    if ok_d:
        _svc_log("remove: Win32 API delete ok")
    else:
        _svc_log(f"remove: Win32 API delete failed: {det_d} - fallback sc delete")
    for _ in range(10):
        code, out = _sc(["delete", SERVICE_NAME])
        if code == 0 or "1060" in out:
            _svc_log(f"remove OK (sc delete rc={code})")
            return True, "Служба zapret2 удалена"
        _svc_log(f"remove: sc delete rc={code} out={out.strip()[:160]!r} - повтор")
        time.sleep(0.5)
    code, out = _sc(["query", SERVICE_NAME])
    if code != 0 or "1060" in out:
        _svc_log("remove OK (службы нет)")
        return True, "Служба zapret2 удалена"
    _svc_log(f"remove FAIL: служба осталась (query rc={code})")
    return False, ("Служба zapret2 не удалилась: отмечена для удаления "
                   "(winws2 не отпустил хендл) - повторите удаление или "
                   "перезагрузите ПК")


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
    # Драйвер мог сломаться между запусками (кейс 2026-09-13) - лечим до
    # sc start, иначе winws2 упадёт на WinDivertOpen.
    try:
        from core.utils import fix_stale_windivert_services
        fix_stale_windivert_services(app_root())
    except Exception:
        pass
    if args:
        ok_r, msg_r = reconfigure(args)
        if not ok_r:
            return False, msg_r
    code, out = _sc(["start", SERVICE_NAME])
    _svc_log(f"start: sc start rc={code} out={out.strip()[:200]!r}")
    if code != 0:
        return False, f"sc start failed: {out.strip()}"
    return True, "winws2 запущен"


def stop():
    # Сначала - корректный sc stop (SCM состояние), taskkill как страховка
    # для вручную запущенного winws2.
    _invalidate_service_cache()
    _svc_log("stop")
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