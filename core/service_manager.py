from __future__ import annotations

import functools
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from core.utils import app_root, run_sc as _sc
from core.applog import log as _applog


SERVICE_NAME = "zapret2"

# HTTP-сервер многопоточный, а операции со службой меняют одно и то же
# состояние SCM и перезапускают один и тот же winws2. Две одновременные
# заявки (например «удалить службу» из подвала и «установить» из блока
# обхода, либо окно тестера плюс фоновая починка) накладывались:
# install вызывает remove и start, remove ждёт выхода winws2 до 5 с, и
# второй поток успевал за это время пересоздать службу - итог «служба
# удалена, а потом снова установлена» с непредсказуемыми аргументами.
# RLock, а не Lock: install/start/reconfigure внутри сами вызывают
# stop/remove/reconfigure, и обычный лок тут встал бы насмерть.
_op_lock = threading.RLock()


def _serialized(fn):
    """Проводит мутирующую операцию со службой под _op_lock."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _op_lock:
            return fn(*args, **kwargs)
    return wrapper

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
    """Аудит #7: единый kill_image (раньше таймаут taskkill не обрабатывался)."""
    from core.proc import kill_image
    kill_image("winws2.exe", timeout=10)


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


def path_status() -> tuple[str, str]:
    """Сверка exe из binPath службы с текущим каталогом программы.

    Возвращает ("ok"|"mismatch"|"none"|"unknown", описание). Ловит переезд
    папки и запуск GUI из другой копии: служба молча продолжает работать со
    старым exe, а текущая копия об этом не знает."""
    if not is_installed():
        return "none", ""
    stored = _read_stored_binpath()
    if not stored:
        return "unknown", "binPath не прочитан"
    from core.utils import split_windows_cmdline
    tokens = split_windows_cmdline(stored.replace('\\"', '"'))
    if not tokens:
        return "unknown", "binPath пуст"
    cur = app_root() / "bin" / "winws2.exe"
    if not cur.exists():
        cur = app_root() / "winws2.exe"
    if str(tokens[0]).strip('"').lower() != str(cur).lower():
        return "mismatch", (f"служба запускает {tokens[0]}, "
                            f"текущая копия программы: {cur}")
    return "ok", ""


def _zapret1_service_exists() -> bool:
    code, _ = _sc(["query", "zapret"])
    return code == 0


def _service_cmdline(exe: Path, conf: Path) -> str:
    """Транспорт binPath для sc-bat (v1-стиль, backslash-кавычки в cmd).

    Итог в SCM: \"exe\" @\"conf\" - кавычки вокруг ПУТИ, @ снаружи (только так
    Cygwin раскрывает @file, см. AI_DOCS/ARG_FILE_RESEARCH_2026-10-14.md)."""
    return f'\\"{exe}\\" @\\"{conf}\\"'


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


def _verify_binpath(exe: Path, conf: Path) -> tuple[bool, str]:
    """Проверяет сохранённый binPath нового формата: [exe, @conf].

    Кривой SCM Win10 исторически молча искажал длинные binPath (случай
    2026-09-12) - теперь binPath короткий, сверяем: число токенов, наличие
    @conf-токена и существование conf-файла (его путь SCM мог исказить)."""
    stored = _read_stored_binpath()
    if not stored:
        return False, "binPath пуст - SCM не сохранил командную строку"
    from core.utils import split_windows_cmdline
    tokens = split_windows_cmdline(stored.replace('\\"', '"'))
    if len(tokens) != 2 or not tokens[1].startswith("@"):
        return False, (f"binPath не в формате @conf (токенов: {len(tokens)}) - "
                       f"командная строка потеряна (нестандартный SCM?)")
    conf_path = Path(tokens[1][1:])
    if not conf_path.exists():
        return False, f"conf-файл из binPath не существует: {conf_path}"
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


def _service_binpath(exe: Path, conf: Path) -> str:
    """binPath с ОБЫЧНЫМИ кавычками (для Win32 API): \"exe\" @\"conf\".

    Аргументы в binPath больше не хранятся (лимит SCM ~4К и искажения Win10
    не применимы): движок читает их из conf-файла - Cygwin раскрывает @file
    до main. Транспорт через cmd/bat - см. _service_cmdline.
    """
    return f'"{exe}" @"{conf}"'


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


def _query_service_state() -> Optional[int]:
    """Состояние службы через QueryServiceStatusEx: 1=STOPPED, 2=START_PENDING,
    3=STOP_PENDING, 4=RUNNING; None - службы нет или не прочиталось
    (ревью старшей модели, P1-2: подтверждённое состояние вместо sleep)."""
    try:
        ctypes, wt, adv = _win32_advapi()

        class SERVICE_STATUS_PROCESS(ctypes.Structure):
            _fields_ = [("dwServiceType", wt.DWORD),
                        ("dwCurrentState", wt.DWORD),
                        ("dwControlsAccepted", wt.DWORD),
                        ("dwWin32ExitCode", wt.DWORD),
                        ("dwServiceSpecificExitCode", wt.DWORD),
                        ("dwCheckPoint", wt.DWORD),
                        ("dwWaitHint", wt.DWORD),
                        ("dwProcessId", wt.DWORD),
                        ("dwServiceFlags", wt.DWORD)]

        adv.QueryServiceStatusEx.restype = wt.BOOL
        adv.QueryServiceStatusEx.argtypes = [
            wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
            ctypes.POINTER(wt.DWORD)]
        SC_MANAGER_CONNECT = 0x0001
        SERVICE_QUERY_STATUS = 0x0004
        scm = adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
        if not scm:
            return None
        try:
            h = adv.OpenServiceW(scm, SERVICE_NAME, SERVICE_QUERY_STATUS)
            if not h:
                return None
            try:
                buf = SERVICE_STATUS_PROCESS()
                need = wt.DWORD()
                ok = adv.QueryServiceStatusEx(h, 0, ctypes.byref(buf),
                                              ctypes.sizeof(buf),
                                              ctypes.byref(need))
                return int(buf.dwCurrentState) if ok else None
            finally:
                adv.CloseServiceHandle(h)
        finally:
            adv.CloseServiceHandle(scm)
    except Exception:  # noqa: BLE001
        return None


def _wait_service_stopped(timeout: float = 5.0) -> bool:
    """Поллинг SCM до SERVICE_STOPPED (1) или «службы нет».

    Подтверждённое состояние вместо голого sleep: первый sc start сразу
    после stop исторически давал 1053 (ревью старшей модели, P1-2)."""
    deadline = time.time() + timeout
    while True:
        st = _query_service_state()
        if st is None or st == 1:
            return True
        if time.time() >= deadline:
            _svc_log(f"stop-wait: служба не дошла до STOPPED за {timeout:.1f}s "
                     f"(state={st})")
            return False
        time.sleep(0.15)


def _winws_running() -> bool:
    """Zapret 1 (winws.exe) запущен? Единый core.proc (аудит #7, хвост:
    конвертация при верификации - census §3.7 эту обёртку пропустил).
    core.proc не бросает и парсит CSV локале-независимо."""
    from core.proc import image_running
    return image_running("winws.exe", timeout=10)


def _winws2_running() -> bool:
    """winws2.exe ещё жив? (единый core.proc; ждём смерти после kill)."""
    from core.proc import image_running
    return image_running("winws2.exe", timeout=10)


def _zapret1_conflict() -> Optional[str]:
    """Причина, по которой Zapret 1 блокирует операцию, или None."""
    if _zapret1_service_exists():
        return "Обнаружена служба Zapret 1 (zapret). Удалите её через service.bat от Zapret 1."
    if _winws_running():
        return "Zapret 1 (winws.exe) запущен. Остановите его перед запуском Zapret 2."
    return None


def _taskkill_winws() -> bool:
    """Остановить winws.exe (Zapret 1). True - команда выполнена
    (не гарантия смерти; core.proc.kill_image, таймаут внутри)."""
    from core.proc import kill_image
    return kill_image("winws.exe", timeout=10)


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


@_serialized
def repair(root_dir: Optional[Path] = None) -> dict:
    """Выгрузка драйвера WinDivert (кнопка «Выгрузить драйвер») + heal
    битых записей службы и сообщение о конфликте с Zapret 1.

    Немедленный путь (кейс автора): служба zapret2 и winws2 держат драйвер -
    останавливаем их, затем sc stop WinDivert выгружает драйвер, и отложенное
    удаление/занятые файлы bin/ освобождаются БЕЗ перезагрузки. Служба, если
    была запущена, поднимается обратно. В ответе - перепроверка (resolved)."""
    from core.utils import (fix_stale_windivert_services,
                            windivert_emergency_unload, windivert_delete_flag,
                            windivert_service_state)
    actions: list[str] = []
    was_installed = is_installed()
    was_running = False
    if was_installed:
        try:
            was_running = status() == "running"
        except Exception:  # noqa: BLE001
            was_running = False
    pause_recovery()  # не даём SCM поднять winws2 посреди починки
    try:
        if was_running:
            _sc(["stop", SERVICE_NAME])
            actions.append("служба zapret2 остановлена")
        if _winws2_running() and _taskkill_winws2():
            actions.append("winws2.exe остановлен (драйвер освобождён)")
        actions += fix_stale_windivert_services(root_dir)
        if _winws_running():
            actions.append("Zapret 1 (winws.exe) запущен - драйвер не трогаю")
        else:
            actions += windivert_emergency_unload()
    except Exception as e:  # noqa: BLE001
        actions.append(f"ошибка починки драйвера: {e}")
    finally:
        resume_recovery()
    if was_installed and was_running:
        ok_s, msg_s = start(None)
        actions.append("служба zapret2 запущена заново" if ok_s
                       else f"служба zapret2 не запустилась: {msg_s}")
    state = windivert_service_state()
    stuck = windivert_delete_flag("WinDivert") == 1 or (
        state is not None and state[1] == 4)
    return {
        "actions": actions,
        "reboot_required": stuck,
        "resolved": not stuck,
        "zapret1": _zapret1_conflict(),
    }


@_serialized
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
    # winws2.exe - бинарник службы НАПРЯМУЮ, аргументы - в logs/service_run.conf
    # (binPath короткий: "exe" @"conf"; cmd-обёртку ловит Defender, а длинные
    # binPath исторически искажались SCM Win10).
    from core.launcher import write_run_conf
    try:
        conf = write_run_conf(root_dir, args, name="service_run.conf")
    except OSError as e:
        return False, f"не записался service_run.conf: {e}"
    cmdline = _service_cmdline(exe, conf)
    native = _service_binpath(exe, conf)
    _svc_log(f"install: exe={exe} args={len(args)} conf={conf}")
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
    okv, msgv = _verify_binpath(exe, conf)
    if not okv:
        _svc_log(f"install FAIL: verify binPath: {msgv}")
        remove()
        return False, f"Установка отменена (кривой binPath): {msgv}"
    # SCM recovery: если winws2 умрёт (случай 2026-09-12: три падения за утро,
    # обход пропадал до ручного перезапуска) - перезапустить службу через 60 с.
    # Результат проверяем: молчаливая потеря автоперезапуска - это ровно тот
    # случай, когда пользователь думает, что защищён, а обход лёг (audit §2.4).
    rc_f, out_f = _sc(["failure", SERVICE_NAME,
                       "reset=", "86400",
                       "actions=", "restart/60000/restart/60000/restart/60000"])
    recovery_ok = rc_f == 0
    if not recovery_ok:
        _svc_log(f"install WARN: sc failure не настроен rc={rc_f} "
                 f"out={out_f.strip()[:200]!r}")
    # Старт проверяем обязательно: служба может создаться, но не запуститься
    # (1053, битый движок, мёртвый ImagePath WinDivert). Раньше результат
    # игнорировался, и пользователь получал «Служба установлена» без обхода.
    ok_s, msg_s = start(args)
    if not ok_s:
        reason = str(msg_s or "").strip() or "причина неизвестна, смотрите лог службы"
        _svc_log(f"install WARN: установлена, но не запустилась: {reason}")
        return True, ("Служба установлена, но не запустилась (" + reason
                      + "). Обхода сейчас нет - нажмите «Запустить службу» "
                        "или откройте «Проверку системы».")
    _svc_log("install OK")
    if not recovery_ok:
        return True, ("Служба установлена и запущена, но автозапуск при падении "
                      "не настроен - если обход отвалится, он не поднимется сам. "
                      "Проверьте «Проверку системы».")
    return True, "Служба zapret2 установлена и запущена"


@_serialized
def reconfigure(args: list[str]) -> tuple[bool, str]:
    """Обновляет параметры службы: args пишутся в logs/service_run.conf,
    binPath становится коротким "exe" @"conf" (лимит SCM ~4К и искажения
    Win10 больше не применимы)."""
    _invalidate_service_cache()
    root_dir = app_root()
    exe = root_dir / "bin" / "winws2.exe"
    if not exe.exists():
        exe = root_dir / "winws2.exe"
    if not str(exe.resolve()).lower().startswith(str(app_root()).lower()):
        return False, f"winws2.exe вне каталога программы: {exe}"
    from core.launcher import write_run_conf
    try:
        conf = write_run_conf(root_dir, args, name="service_run.conf")
    except OSError as e:
        _svc_log(f"reconfigure FAIL: conf write: {e!r}")
        return False, f"не записался service_run.conf: {e}"
    native = _service_binpath(exe, conf)
    _svc_log(f"reconfigure: args={len(args)} conf={conf}")
    ok_a, det_a = _win32_change_service(native)
    if ok_a:
        _svc_log(f"reconfigure: Win32 API change ok (binPath={len(native)})")
    else:
        _svc_log(f"reconfigure: Win32 API change failed: {det_a} - fallback sc-bat")
        cmdline = _service_cmdline(exe, conf)
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
        return False, ("sc config не сохранил binPath дословно - служба "
                       "осталась на старых (запустите переустановку службы)")
    _svc_log("reconfigure OK")
    return True, "Параметры службы обновлены"


@_serialized
def migrate_if_needed() -> tuple[bool, str]:
    """0.11: перевод legacy-службы (аргументы зашиты в binPath) на @conf.

    Legacy-аргументы парсятся из сохранённого binPath и переносятся в
    logs/service_run.conf; binPath становится коротким "exe" @"conf".
    Служба перезапускается, если была запущена. Ничего не делает, если
    службы нет или она уже в новом формате."""
    if not is_installed():
        return True, "службы нет"
    stored = _read_stored_binpath()
    if not stored:
        return True, "binPath не прочитан"
    from core.utils import split_windows_cmdline
    tokens = split_windows_cmdline(stored.replace('\\"', '"'))
    if len(tokens) < 2:
        return True, "аргументов в binPath нет"
    if tokens[1].startswith("@"):
        return True, "уже новый формат"
    args = tokens[1:]
    root_dir = app_root()
    exe = root_dir / "bin" / "winws2.exe"
    if not exe.exists():
        exe = root_dir / "winws2.exe"
    if not str(exe.resolve()).lower().startswith(str(app_root()).lower()):
        return False, f"winws2.exe вне каталога программы: {exe}"
    _invalidate_service_cache()
    _svc_log(f"migrate: legacy binPath args={len(args)} -> @conf")
    was_running = status() == "running"
    if was_running:
        stop()
    from core.launcher import write_run_conf
    try:
        conf = write_run_conf(root_dir, args, name="service_run.conf")
    except OSError as e:
        _svc_log(f"migrate FAIL: conf write: {e!r}")
        if was_running:
            start()
        return False, f"не записался service_run.conf: {e}"
    native = _service_binpath(exe, conf)
    ok_a, det_a = _win32_change_service(native)
    if not ok_a:
        _svc_log(f"migrate: Win32 API change failed: {det_a} - fallback sc-bat")
        cmdline = _service_cmdline(exe, conf)
        code, out = _sc_run_bat([f'sc config {SERVICE_NAME} binPath= "{cmdline}"'])
        if code != 0:
            _svc_log(f"migrate FAIL: sc config rc={code} out={out.strip()[:200]!r}")
            if was_running:
                start()
            return False, f"sc config failed: {out.strip()}"
    okv, msgv = _verify_binpath(exe, conf)
    if not okv:
        _svc_log(f"migrate FAIL: verify: {msgv}")
        if was_running:
            start()
        return False, f"binPath не верифицировался: {msgv}"
    if was_running:
        ok_s, msg_s = start()
        if not ok_s:
            _svc_log(f"migrate WARN: служба не запустилась: {msg_s}")
            return False, f"служба переведена, но не запустилась: {msg_s}"
    _svc_log("migrate OK")
    return True, "служба переведена на conf-формат"


@_serialized
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


@_serialized
def start(args: Optional[list[str]] = None):
    conflict = _zapret1_conflict()
    if conflict:
        return False, conflict
    _invalidate_service_cache()
    from core.tcp_timestamps import enable_for_engine
    enable_for_engine()
    ps, pmsg = path_status()
    if ps == "mismatch":
        _svc_log(f"start WARN: binPath ведёт на другую копию: {pmsg}")
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
    else:
        # 0.11: старт без новых аргументов - заодно мигрируем legacy-службу
        try:
            ok_m, msg_m = migrate_if_needed()
            if not ok_m:
                _svc_log(f"start: migrate warn: {msg_m}")
        except Exception as e:  # noqa: BLE001
            _svc_log(f"start: migrate exception: {e!r}")
    code, out = _sc(["start", SERVICE_NAME])
    _svc_log(f"start: sc start rc={code} out={out.strip()[:200]!r}")
    if code != 0:
        return False, f"sc start failed: {out.strip()}"
    return True, "winws2 запущен"


@_serialized
def stop():
    # Сначала - корректный sc stop (SCM состояние), taskkill как страховка
    # для вручную запущенного winws2.
    _invalidate_service_cache()
    _svc_log("stop")
    _sc(["stop", SERVICE_NAME])
    _taskkill_winws2()
    # P1-2: подтверждаем переход в STOPPED (закрывает гонку «sc start после
    # stop → 1053» детерминированно, а не паузой).
    _wait_service_stopped()
    return True, "winws2 остановлен"


# ── SCM-recovery: пауза/возобновление (2026-09-12) ─────────────────
# Тестер/сканы гасят winws2 на весь прогон. Если SCM-recovery активен, он
# через 60с ПЕРЕЗАПУСКАЕТ службовый winws2 посреди теста → конфликт
# WinDivert, обрыв прогона. На время управляемых остановок recovery
# выключается и восстанавливается ДОСЛОВНО (ревью старшей модели, P1-3:
# сохраняем точную исходную конфигурацию, а не свои restart/60000x3).
_recovery_paused: bool = False
_recovery_was_on: bool = False
_recovery_saved: Optional[dict] = None
_recovery_lock = threading.Lock()


def _read_failure_actions_win32() -> Optional[dict]:
    """Точное чтение failure-конфигурации службы (QueryServiceConfig2W).

    {'reset': int, 'actions': [(SC_ACTION_TYPE, delay_ms), ...]} или None.
    Типы SC_ACTION: 0=NONE, 1=RESTART, 2=REBOOT, 3=COMMAND (P1-3)."""
    try:
        ctypes, wt, adv = _win32_advapi()

        class SC_ACTION(ctypes.Structure):
            _fields_ = [("Type", wt.DWORD), ("Delay", wt.DWORD)]

        class SERVICE_FAILURE_ACTIONSW(ctypes.Structure):
            _fields_ = [("dwResetPeriod", wt.DWORD),
                        ("lpRebootMsg", wt.LPWSTR),
                        ("lpCommand", wt.LPWSTR),
                        ("cActions", wt.DWORD),
                        ("lpsaActions", ctypes.POINTER(SC_ACTION))]

        adv.QueryServiceConfig2W.restype = wt.BOOL
        adv.QueryServiceConfig2W.argtypes = [
            wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD,
            ctypes.POINTER(wt.DWORD)]
        SC_MANAGER_CONNECT = 0x0001
        SERVICE_QUERY_CONFIG = 0x0001
        SERVICE_CONFIG_FAILURE_ACTIONS = 2
        scm = adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
        if not scm:
            return None
        try:
            h = adv.OpenServiceW(scm, SERVICE_NAME, SERVICE_QUERY_CONFIG)
            if not h:
                return None
            try:
                need = wt.DWORD()
                adv.QueryServiceConfig2W(h, SERVICE_CONFIG_FAILURE_ACTIONS,
                                         None, 0, ctypes.byref(need))
                if not need.value:
                    return None
                buf = ctypes.create_string_buffer(need.value)
                if not adv.QueryServiceConfig2W(h, SERVICE_CONFIG_FAILURE_ACTIONS,
                                                buf, need.value,
                                                ctypes.byref(need)):
                    return None
                fa = ctypes.cast(buf,
                                 ctypes.POINTER(SERVICE_FAILURE_ACTIONSW)).contents
                actions = [(int(fa.lpsaActions[i].Type),
                            int(fa.lpsaActions[i].Delay))
                           for i in range(int(fa.cActions))]
                return {"reset": int(fa.dwResetPeriod), "actions": actions}
            finally:
                adv.CloseServiceHandle(h)
        finally:
            adv.CloseServiceHandle(scm)
    except Exception:  # noqa: BLE001
        return None


def _apply_failure_actions(reset_period: int, actions: list) -> bool:
    """Точная запись failure-конфигурации (ChangeServiceConfig2W, P1-3).

    actions: [(SC_ACTION_TYPE, delay_ms), ...]; пустой список = отключить."""
    try:
        ctypes, wt, adv = _win32_advapi()

        class SC_ACTION(ctypes.Structure):
            _fields_ = [("Type", wt.DWORD), ("Delay", wt.DWORD)]

        class SERVICE_FAILURE_ACTIONSW(ctypes.Structure):
            _fields_ = [("dwResetPeriod", wt.DWORD),
                        ("lpRebootMsg", wt.LPWSTR),
                        ("lpCommand", wt.LPWSTR),
                        ("cActions", wt.DWORD),
                        ("lpsaActions", ctypes.POINTER(SC_ACTION))]

        adv.ChangeServiceConfig2W.restype = wt.BOOL
        adv.ChangeServiceConfig2W.argtypes = [wt.HANDLE, wt.DWORD,
                                              ctypes.c_void_p]
        SC_MANAGER_CONNECT = 0x0001
        SERVICE_CHANGE_CONFIG = 0x0002
        SERVICE_CONFIG_FAILURE_ACTIONS = 2
        scm = adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
        if not scm:
            return False
        try:
            h = adv.OpenServiceW(scm, SERVICE_NAME, SERVICE_CHANGE_CONFIG)
            if not h:
                return False
            try:
                n = max(1, len(actions))
                arr = (SC_ACTION * n)()
                for i, (type_, delay) in enumerate(actions):
                    arr[i].Type = int(type_)
                    arr[i].Delay = int(delay)
                info = SERVICE_FAILURE_ACTIONSW(
                    int(reset_period), None, None, len(actions),
                    ctypes.cast(arr, ctypes.POINTER(SC_ACTION)))
                return bool(adv.ChangeServiceConfig2W(
                    h, SERVICE_CONFIG_FAILURE_ACTIONS, ctypes.byref(info)))
            finally:
                adv.CloseServiceHandle(h)
        finally:
            adv.CloseServiceHandle(scm)
    except Exception:  # noqa: BLE001
        return False


def pause_recovery() -> None:
    """На время тестов/починки: отключаем sc.exe restart на время worker (L4).

    Читает ИСХОДНУЮ failure-конфигурацию (P1-3) и сохраняет её; при
    недоступности точного чтения - legacy sc qfailure, fail-closed: не
    прочитали - не мутируем SCM (внешнее ревью 14.10)."""
    global _recovery_paused, _recovery_was_on, _recovery_saved
    with _recovery_lock:
        if _recovery_paused:
            return
        saved = _read_failure_actions_win32()
        if saved is not None:
            _recovery_saved = saved
            _recovery_was_on = any(t in (1, 2, 3) for t, _d in saved["actions"])
            if not _apply_failure_actions(0, []):
                _svc_log("pause_recovery: не удалось отключить failure actions "
                         "(fail-closed: пауза не выставлена)")
                _recovery_saved = None
                return
            _recovery_paused = True
            _svc_log(f"pause_recovery: actions off (saved {saved['actions']})")
            return
        try:
            code, out = _sc(["qfailure", SERVICE_NAME])
            if code != 0:
                return
            _recovery_was_on = ("restart" in (out or "").lower()
                                or "перезапуск" in (out or "").lower())
            _sc(["failure", SERVICE_NAME, "reset=", "0", "actions=", ""])
            _recovery_paused = True
        except Exception:
            pass


def resume_recovery() -> None:
    global _recovery_paused, _recovery_saved
    with _recovery_lock:
        if not _recovery_paused:
            return
        try:
            saved = _recovery_saved
            if saved is not None:
                # P1-3: восстанавливаем РОВНО исходную конфигурацию, даже если
                # она пустая (пользователь/другое ПО могли её менять).
                if not _apply_failure_actions(saved["reset"], saved["actions"]):
                    _svc_log("resume_recovery: точное восстановление не удалось "
                             "- fallback sc failure")
                    if _recovery_was_on:
                        _sc(["failure", SERVICE_NAME, "reset=", "86400",
                             "actions=", "restart/60000/restart/60000/restart/60000"])
            elif _recovery_was_on:
                _sc(["failure", SERVICE_NAME, "reset=", "86400",
                     "actions=", "restart/60000/restart/60000/restart/60000"])
        finally:
            _recovery_paused = False
            _recovery_saved = None