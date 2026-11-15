from __future__ import annotations

import base64
import contextlib
import datetime
import functools
import json
import os
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
            try:
                return fn(*args, **kwargs)
            finally:
                # После завершения мутации кэш SCM не должен показывать
                # старое состояние ещё 2 секунды.
                _invalidate_service_cache()
    return wrapper

# Короткий TTL-кэш состояния службы: фронтенд поллит /api/service/status
# каждые ~9с, а sc query - подпроцесс. Сбрасывается на любой мутирующей
# операции (install/remove/start/stop/reconfigure).
_STATUS_TTL = 2.0
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


def _winws2_paths() -> set[str]:
    """Пути winws2 ТОЛЬКО этой установки (path-фильтр, не имя вслепую)."""
    root = app_root()
    return {str(root / "bin" / "winws2.exe"), str(root / "winws2.exe")}


def _taskkill_winws2():
    """Единый kill winws2, но ТОЛЬКО этой установки (ревью 18.10:
    name-wide kill убивал движок второй копии GUI в другой папке).
    Возвращает список реально завершённых PID (пустой - ничего не убито)."""
    from core.proc import kill_image_filtered
    return kill_image_filtered("winws2.exe", _winws2_paths(), timeout=10)


def _wait_winws2_exit(pids, *, timeout: float = 5.0) -> bool:
    """Дождаться смерти известных PID winws2 (T19: WaitForSingleObject).

    Раньше remove/repair крутили 20 x tasklist/sleep(0.25) - до 5 с простоя.
    Хендлы известных PID сигналятся за миллисекунды; если Win32-API не дало
    хендлов (права/не-Windows) - прежний поллинг по имени, как fallback."""
    try:
        from core.proc import wait_pids_exit
        leftover = wait_pids_exit([int(p) for p in (pids or [])], timeout=timeout)
    except Exception:  # noqa: BLE001
        leftover = list(pids or [])
    if not leftover:
        return True
    # Не подтвердили по PID - старый путь: ждём исчезновения winws2 по имени.
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _winws2_running():
            return True
        time.sleep(0.15)
    return not _winws2_running()


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
    # T19: QueryServiceStatusEx (единицы микросекунд) вместо sc.exe (~33 мс):
    # /api/status поллится каждые ~4 c, а diagnostics зовёт status() ещё чаще.
    state = _query_service_state()
    if state is not None:
        # SERVICE_RUNNING=4; START_PENDING/STOPPED/PENDING -> "stopped"
        # (прежний разбор sc query искал RUNNING в выводе - поведение то же).
        _status_cache_value = "running" if state == 4 else "stopped"
    else:
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

    Возвращает ("ok"|"mismatch"|"orphaned"|"none"|"unknown", описание).
    Ловит переезд папки и запуск GUI из другой копии: служба молча
    продолжает работать со старым exe, а текущая копия об этом не знает.
    "orphaned" - служба осталась от УДАЛЁННОЙ копии (её exe не существует):
    такая служба безопасна для takeover (переустановки/удаления) и не должна
    блокировать GUI навсегда (аудит 2026-11-14, P1-2)."""
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
    stored_exe = str(tokens[0]).strip('"')
    try:
        if not Path(stored_exe).exists():
            return "orphaned", (f"служба установлена из удалённой папки: "
                                f"{stored_exe} не существует")
    except OSError:
        pass
    if stored_exe.lower() != str(cur).lower():
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
    # Сверяем не только формат: запись того же формата, но на другой exe/conf
    # (вторая копия/старый путь) раньше считалась валидной.
    try:
        got_exe = os.path.normcase(str(Path(tokens[0]).resolve()))
        want_exe = os.path.normcase(str(Path(exe).resolve()))
        got_conf = os.path.normcase(str(conf_path.resolve()))
        want_conf = os.path.normcase(str(Path(conf).resolve()))
    except OSError:
        got_exe = os.path.normcase(str(tokens[0]))
        want_exe = os.path.normcase(str(exe))
        got_conf = os.path.normcase(str(conf_path))
        want_conf = os.path.normcase(str(conf))
    if got_exe != want_exe:
        return False, f"binPath указывает на другой winws2.exe: {tokens[0]}"
    if got_conf != want_conf:
        return False, f"binPath указывает на другой conf: {conf_path}"
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


def _wait_service_running(timeout: float = 10.0) -> tuple[bool, Optional[int]]:
    """Поллинг SCM до SERVICE_RUNNING (4).

    sc start возвращает управление до фактической готовности winws2;
    успешный exit code сам по себе не означает, что служба запущена.
    Возвращает (running, последнее_состояние)."""
    deadline = time.time() + timeout
    last = None
    while True:
        st = _query_service_state()
        last = st
        if st == 4:
            return True, st
        if st in (1, None):
            # STOPPED/служба исчезла: ждать RUNNING уже бессмысленно.
            return False, st
        if time.time() >= deadline:
            _svc_log(f"start-wait: служба не дошла до RUNNING за {timeout:.1f}s "
                     f"(state={st})")
            return False, st
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


@_serialized
def repair(root_dir: Optional[Path] = None) -> dict:
    """«Выгрузить драйвер» + heal службы под durable-журналом (T19)."""
    root = Path(root_dir) if root_dir is not None else app_root()
    with _service_journal(root, "repair") as journal:
        return _repair_impl(root_dir, journal)


def _repair_impl(root_dir: Optional[Path] = None,
                 journal=None) -> dict:
    """Выгрузка драйвера WinDivert (кнопка «Выгрузить драйвер») + heal
    битых записей службы и сообщение о конфликте с Zapret 1.

    Немедленный путь (кейс автора): служба zapret2 и winws2 держат драйвер -
    останавливаем их, затем sc stop WinDivert выгружает драйвер, и отложенное
    удаление/занятые файлы bin/ освобождаются БЕЗ перезагрузки. Служба, если
    была запущена, поднимается обратно. В ответе - перепроверка (resolved)."""
    if journal is None:
        journal = _NullJournal()
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
        killed = _taskkill_winws2() if _winws2_running() else []
        if killed:
            actions.append("winws2.exe остановлен (драйвер освобождён)")
            # Ждём фактического выхода процесса: sc stop WinDivert при живом
            # хендле оставляет драйвер загруженным (ревью 18.10). T19:
            # WaitForSingleObject по известным PID вместо 20 x sleep(0.25).
            _wait_winws2_exit(killed, timeout=5.0)
            journal.step("winws2-stopped")
        actions += fix_stale_windivert_services(root_dir)
        if _winws_running():
            actions.append("Zapret 1 (winws.exe) запущен - драйвер не трогаю")
        else:
            actions += windivert_emergency_unload()
    except Exception as e:  # noqa: BLE001
        actions.append(f"ошибка починки драйвера: {e}")
    finally:
        resume_recovery()
    restart_failed = False
    if was_installed and was_running:
        ok_s, msg_s = start(None)
        restart_failed = not ok_s
        actions.append("служба zapret2 запущена заново" if ok_s
                       else f"служба zapret2 не запустилась: {msg_s}")
    # Start=4/DeleteFlag=1 у WinDivert - ШТАТНОЕ состояние при загруженном
    # драйвере (см. diagnostics._check_windivert_service). Реальная
    # незавершённость: мёртвый ImagePath или неудачная выгрузка/stop.
    state = windivert_service_state()
    dead = ""
    if state is not None:
        try:
            from core.utils import windivert_image_dead
            dead = windivert_image_dead(state[0])
        except Exception:  # noqa: BLE001
            dead = ""
    stuck = (bool(dead) or restart_failed or any(
        ("нужна перезагрузка" in a) or ("stop не помог" in a)
        or ("драйвер занят" in a) for a in actions))
    journal.step("done")
    return {
        "actions": actions,
        "reboot_required": stuck,
        "resolved": not stuck,
        "restart_failed": restart_failed,
        "zapret1": _zapret1_conflict(),
    }


def _backup_install_conf(root_dir: Path) -> tuple[Path, Optional[bytes], bool]:
    path = Path(root_dir) / "logs" / "service_run.conf"
    try:
        return path, path.read_bytes() if path.exists() else None, True
    except OSError as e:
        _svc_log(f"install: conf backup failed: {e!r}")
        return path, None, False


def _restore_install_conf(path: Path, data: Optional[bytes]) -> tuple[bool, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            path.unlink(missing_ok=True)
        else:
            tmp = path.with_name(path.name + ".rollback.tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return True, ""
    except OSError as e:
        _svc_log(f"install: conf restore failed: {e!r}")
        return False, str(e)


def _recreate_old_service(binpath: str, was_running: bool,
                          failure: Optional[dict] = None) -> tuple[bool, str]:
    if not binpath:
        return False, "старый binPath не прочитан"
    ok, det = _win32_create_service(binpath)
    if not ok:
        _svc_log(f"install rollback: Win32 create failed: {det} - sc fallback")
        code, out = _sc_run_bat([
            f'sc create {SERVICE_NAME} binPath= {binpath} '
            f'DisplayName= "Zapret 2 DPI Bypass" start= auto',
        ])
        if code != 0:
            return False, f"sc create: {out.strip()}"
    _sc(["description", SERVICE_NAME, "zapret DPI bypass (Zapret 2)"])
    # T19: до remove() failure actions были отключены и исчезли вместе со
    # службой; возвращаем прочитанную конфигурацию (иначе rollback оставит
    # службу без обещанного автозапуска при падении winws2).
    if failure is not None:
        if not _apply_failure_actions(int(failure.get("reset") or 0),
                                      list(failure.get("actions") or [])):
            _svc_log("install rollback: failure actions restore failed")
    elif was_running:
        # T19: исходную конфигурацию прочитать не удалось - возвращаем
        # штатный auto-restart, иначе откат оставит службу без него молча.
        _sc(["failure", SERVICE_NAME, "reset=", "86400",
             "actions=", "restart/60000/restart/60000/restart/60000"])
    if was_running:
        code, out = _sc(["start", SERVICE_NAME])
        if code != 0:
            return False, f"sc start: {out.strip()}"
    return True, ""


@_serialized
def install(root_dir: Optional[Path] = None, args: Optional[list[str]] = None) -> tuple[bool, str]:
    """Установка/переустановка службы под durable-журналом (T19)."""
    root = Path(root_dir) if root_dir is not None else app_root()
    with _service_journal(root, "install") as journal:
        return _install_impl(root_dir, args, journal)


def _install_impl(root_dir: Optional[Path] = None,
                  args: Optional[list[str]] = None,
                  journal=None) -> tuple[bool, str]:
    if journal is None:
        journal = _NullJournal()
    conflict = _zapret1_conflict()
    if conflict:
        return False, conflict
    _invalidate_service_cache()
    _svc_log(f"install: args={len(args or [])} root={root_dir}")
    if root_dir is None:
        root_dir = app_root()
    exe = Path(root_dir) / "bin" / "winws2.exe"
    if not exe.exists():
        exe = Path(root_dir) / "winws2.exe"
    if not exe.exists():
        return False, "winws2.exe не найден"
    if not str(exe.resolve()).lower().startswith(str(app_root()).lower()):
        return False, f"winws2.exe вне каталога программы: {exe}"
    if args is None:
        args = []
    old_installed = is_installed()
    old_was_running = old_installed and status() == "running"
    old_native = _read_stored_binpath() if old_installed else ""
    # T19: failure actions старой службы исчезнут вместе с ней при remove -
    # сохраняем, чтобы rollback вернул auto-restart, а не молчаливую потерю.
    old_failure = (_read_failure_actions_win32()
                   if old_installed else None)
    conf_path, conf_backup, conf_read_ok = _backup_install_conf(Path(root_dir))
    if not conf_read_ok:
        return False, ("не удалось прочитать старый logs/service_run.conf - "
                       "установка отменена, чтобы не потерять рабочие аргументы")
    old_removed = False
    created = False

    def rollback(reason: str) -> tuple[bool, str]:
        details: list[str] = []
        if created and (old_removed or not old_installed) and is_installed():
            ok, msg = remove()
            if not ok:
                details.append(f"новая служба не удалена: {msg}")
        ok, msg = _restore_install_conf(conf_path, conf_backup)
        if not ok:
            details.append(f"service_run.conf не восстановлен: {msg}")
        if old_installed and old_removed:
            ok, msg = _recreate_old_service(old_native, old_was_running,
                                            old_failure)
            if ok:
                details.append("старая служба восстановлена")
            else:
                details.append(f"старую службу не удалось восстановить: {msg}")
        elif old_installed:
            if not is_installed():
                ok, msg = _recreate_old_service(old_native, old_was_running,
                                                old_failure)
                details.append("старая служба восстановлена" if ok
                               else f"старую службу не удалось восстановить: {msg}")
            else:
                details.append("служба оставлена как была")
        else:
            details.append("изменения отменены")
        suffix = "; ".join(details)
        _svc_log(f"install rollback: {reason}; {suffix}")
        return False, f"{reason}; {suffix}"
    # ПРЕДУСЛОВИЯ ПРОВЕРЯЕМ ДО remove() (ревью 18.10: раньше рабочая служба
    # удалялась, и только потом обнаруживалась ошибка exe/guard/conf -
    # пользователь оставался без обхода).
    # winws2.exe - бинарник службы НАПРЯМУЮ, аргументы - в logs/service_run.conf
    # (binPath короткий: "exe" @"conf"; cmd-обёртку ловит Defender, а длинные
    # binPath исторически искажались SCM Win10).
    from core.launcher import write_run_conf
    try:
        conf = write_run_conf(root_dir, args, name="service_run.conf")
    except OSError as e:
        return False, f"не записался service_run.conf: {e}"
    journal.step("conf")
    ok_r, msg_r = remove()
    if not ok_r:
        # Не перезаписываем/не теряем рабочую службу, если старую не удалось
        # убрать (1072/чужой движок/SCM). Аудит 24.10.
        return rollback(f"не удалось удалить старую службу: {msg_r}")
    old_removed = True
    journal.step("old-removed")
    time.sleep(0.5)
    # Драйвер лечим ПОСЛЕ остановки winws2 (кейс 2026-09-13): править или
    # удалять службу драйвера при живых хендлах нельзя - она получит
    # «marked for deletion» (1072) и починится только перезагрузкой.
    try:
        from core.utils import fix_stale_windivert_services
        fix_stale_windivert_services(root_dir)
    except Exception:
        pass
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
            return rollback(f"sc create failed: {out.strip()}")
    created = True
    journal.step("created")
    _sc(["description", SERVICE_NAME, "zapret DPI bypass (Zapret 2)"])
    # Verify BEFORE start: old/broken SCM может молча исказить binPath
    # (аргументы по пробелам рвутся, кириллические пути не читаются) -
    # тогда служба «стоит», но обхода нет и автозапуск валится.
    okv, msgv = _verify_binpath(exe, conf)
    if not okv:
        _svc_log(f"install FAIL: verify binPath: {msgv}")
        return rollback(f"Установка отменена (кривой binPath): {msgv}")
    journal.step("verified")
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
        if old_installed:
            return rollback(f"новая служба не запустилась ({reason})")
        _svc_log(f"install WARN: установлена, но не запустилась: {reason}")
        journal.step("installed-no-start")
        return True, ("Служба установлена, но не запустилась (" + reason
                      + "). Обхода сейчас нет - нажмите «Запустить службу» "
                        "или откройте «Проверку системы».")
    _svc_log("install OK")
    journal.step("done")
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


def _is_marked_for_delete(out: str) -> bool:
    """SCM: служба отмечена для удаления (1072) - ещё фактически существует."""
    lowered = (out or "").lower()
    return ("1072" in lowered or "marked for deletion" in lowered
            or "отмечен" in lowered)


def _service_absent(*, timeout: float = 2.0) -> bool:
    """Подтверждение отсутствия службы после delete (Win32 + sc fallback).

    T19/T10-2: delete отдаёт успех до фактического исчезновения записи
    (отложенное удаление при живом хендле). Успех сообщаем только когда
    Win32/SCM реально больше не видит службу; статус 1072 «marked for
    deletion» - НЕ отсутствие."""
    deadline = time.time() + max(0.0, timeout)
    while True:
        if _query_service_state() is None:
            code, out = _sc(["query", SERVICE_NAME])
            if code != 0 and not _is_marked_for_delete(out):
                return True
        if time.time() >= deadline:
            return False
        time.sleep(0.1)

@_serialized
def remove():
    """Удаление службы под durable-журналом (T19/T10-1, T10-2)."""
    root = app_root()
    with _service_journal(root, "remove") as journal:
        return _remove_impl(journal)


def _remove_impl(journal=None):
    if journal is None:
        journal = _NullJournal()
    _invalidate_service_cache()
    remove_ps, remove_msg = path_status()
    if remove_ps in ("mismatch", "unknown"):
        _svc_log(f"remove REFUSED: {remove_ps}: {remove_msg}")
        return False, ("Не удалось подтвердить, что служба zapret2 принадлежит "
                       f"этой копии: {remove_msg or remove_ps}. Удалять её нельзя.")
    # T19/T10-2: перед taskkill/delete отключаем SCM failure actions: иначе
    # SCM поднимает winws2 по recovery, тот снова держит хендл (delete -> 1072
    # «отмечена для удаления»). Пауза refcounted: при вызове из install/repair
    # внешняя пауза не снимается этим remove.
    paused = pause_recovery()
    removed = False
    try:
        if paused:
            if not _failure_actions_disabled():
                _svc_log("remove: WARN SCM-recovery не подтверждён выключенным")
        else:
            _svc_log("remove: SCM-recovery не отключён (fail-closed чтение "
                     "failure actions) - удаление продолжаем")
        _svc_log("remove: stop+taskkill")
        _sc(["stop", SERVICE_NAME])
        killed = _taskkill_winws2()
        # Живой winws2 держит хендл: sc delete сразу после taskkill оставляет
        # службу «отмеченной для удаления» (1072) - отсюда «удаляется со
        # второго раза». T19: WaitForSingleObject по известным PID (мс)
        # вместо 20 x tasklist/sleep(0.25) (до 5 с).
        if killed:
            _wait_winws2_exit(killed, timeout=5.0)
        journal.step("stopped")
        ok_d, det_d = _win32_delete_service()
        if ok_d:
            _svc_log("remove: Win32 API delete ok")
        else:
            _svc_log(f"remove: Win32 API delete failed: {det_d} - fallback "
                     "sc delete")
        journal.step("deleting")
        for _ in range(10):
            code, out = _sc(["delete", SERVICE_NAME])
            if code == 0 or "1060" in out:
                if _service_absent():
                    journal.step("deleted")
                    _svc_log(f"remove OK (sc delete rc={code}, отсутствие "
                             "подтверждено)")
                    removed = True
                    return True, "Служба zapret2 удалена"
                _svc_log("remove: delete принят, но запись ещё видна - повтор")
            else:
                _svc_log(f"remove: sc delete rc={code} "
                         f"out={out.strip()[:160]!r} - повтор")
            time.sleep(0.5)
        code, out = _sc(["query", SERVICE_NAME])
        if "1060" in out:
            journal.step("deleted")
            removed = True
            _svc_log("remove OK (службы нет)")
            return True, "Служба zapret2 удалена"
        if _is_marked_for_delete(out):
            _svc_log(f"remove FAIL: служба отмечена для удаления (1072), "
                     f"code={code}")
            return False, ("Служба zapret2 не удалилась: отмечена для удаления "
                           "(winws2 не отпустил хендл) - повторите удаление или "
                           "перезагрузите ПК")
        if code != 0:
            # Ревью 18.10: НЕ выдаём успех, если sc query вообще не выполнился
            # (rc=-1/пустой out): раньше `code != 0` трактовался как «службы нет».
            _svc_log(f"remove FAIL: sc query rc={code} "
                     f"out={out.strip()[:160]!r}")
            return False, ("не удалось подтвердить удаление службы "
                           f"(sc query rc={code}) - проверьте вручную")
        _svc_log(f"remove FAIL: служба осталась (query rc={code})")
        return False, ("Служба zapret2 не удалилась: отмечена для удаления "
                       "(winws2 не отпустил хендл) - повторите удаление или "
                       "перезагрузите ПК")
    finally:
        if removed:
            # Службы больше нет: пауза recovery неактуальна (иначе следующий
            # install/start не сможет её выставить для новой службы).
            _reset_recovery_state()
        else:
            # Не удалили - возвращаем ровно ту failure-конфигурацию, что была.
            resume_recovery()


@_serialized
def start(args: Optional[list[str]] = None):
    """Запуск службы под durable-журналом (T19)."""
    try:
        has_service = bool(is_installed())
    except Exception:  # noqa: BLE001
        has_service = True
    if not has_service:
        # Службы нет - journal/recovery нечего откатывать, а снимок SCM на
        # каждый старт «голого» winws2 - лишняя работа.
        return _start_impl(args, _NullJournal())
    with _service_journal(app_root(), "start") as journal:
        return _start_impl(args, journal)


def _start_impl(args: Optional[list[str]] = None, journal=None):
    if journal is None:
        journal = _NullJournal()
    conflict = _zapret1_conflict()
    if conflict:
        return False, conflict
    _invalidate_service_cache()
    from core.tcp_timestamps import enable_for_engine
    enable_for_engine()
    start_ps, start_msg = path_status()
    if start_ps in ("mismatch", "unknown", "orphaned"):
        _svc_log(f"start REFUSED: {start_ps}: {start_msg}")
        if start_ps == "orphaned":
            return False, ("Служба zapret2 осталась от удалённой копии "
                           f"программы: {start_msg}. Нажмите «Переустановить "
                           "службу» (или «Установить») в этой копии - она "
                           "заменит устаревшую службу.")
        return False, ("Не удалось подтвердить, что служба zapret2 принадлежит "
                       f"этой копии: {start_msg or start_ps}. Не запускаю её.")
    # ПРЕДУСЛОВИЯ ДО stop() (ревью 18.10): кривой exe/guard/conf не должен
    # оставлять пользователя без уже работающей службы.
    if args:
        ok_r, msg_r = reconfigure(args)
        if not ok_r:
            return False, msg_r
    stop()
    journal.step("stopped")
    # Даём SCM время закрыть состояние (иначе первый sc start может дать 1053).
    time.sleep(0.5)
    # Драйвер мог сломаться между запусками (кейс 2026-09-13) - лечим до
    # sc start, иначе winws2 упадёт на WinDivertOpen.
    try:
        from core.utils import fix_stale_windivert_services
        fix_stale_windivert_services(app_root())
    except Exception:
        pass
    if not args:
        # 0.11: старт без новых аргументов - заодно мигрируем legacy-службу
        try:
            ok_m, msg_m = migrate_if_needed()
            if not ok_m:
                _svc_log(f"start: migrate warn: {msg_m}")
        except Exception as e:  # noqa: BLE001
            _svc_log(f"start: migrate exception: {e!r}")
        # P1-3 (аудит 2026-11-14): внутренний start(None) (repair/restore
        # тестера/updater/session-recovery) стартовал службу по УСТАРЕВШЕМУ
        # logs/service_run.conf без валидации. После 1.0.7 такие конфы могут
        # быть фатальны (дубль hostlist-файла в профиле, wf_priority вне
        # диапазона и т.п.) - проверяем перед sc start и не запускаем мусор.
        root0 = app_root()
        exe0 = root0 / "bin" / "winws2.exe"
        if not exe0.exists():
            exe0 = root0 / "winws2.exe"
        conf0 = root0 / "logs" / "service_run.conf"
        try:
            from core.launcher import read_run_conf, validate_args
            if not conf0.exists():
                _svc_log("start REFUSED: service_run.conf отсутствует")
                return False, ("Нет logs/service_run.conf - аргументы службы "
                               "потеряны. Переустановите службу из этой копии "
                               "программы.")
            conf_tokens = read_run_conf(conf0)
            if conf_tokens:
                ok_v, msg_v = validate_args(exe0, conf_tokens)
                if not ok_v:
                    _svc_log(f"start REFUSED: conf invalid: {msg_v}")
                    return False, ("Параметры службы не проходят проверку "
                                   f"winws2: {msg_v}. Переустановите службу "
                                   "из этой копии программы.")
        except OSError as e:
            _svc_log(f"start: conf precheck OSError: {e!r}")
        except Exception as e:  # noqa: BLE001
            _svc_log(f"start: conf precheck warn: {e!r}")
    journal.step("starting")
    code, out = _sc(["start", SERVICE_NAME])
    _svc_log(f"start: sc start rc={code} out={out.strip()[:200]!r}")
    if code != 0:
        # 1056 = уже запущена; это не ошибка, если SCM подтверждает RUNNING.
        if "1056" in out:
            ok_run, state = _wait_service_running(timeout=3.0)
            if ok_run:
                journal.step("done")
                return True, "winws2 уже запущен"
        return False, f"sc start failed: {out.strip()}"
    ok_run, state = _wait_service_running()
    if not ok_run:
        _invalidate_service_cache()
        return False, (f"sc start принят, но служба не перешла в RUNNING "
                       f"(state={state}); проверьте winws2 и драйвер")
    journal.step("done")
    return True, "winws2 запущен"


@_serialized
def stop():
    """Остановка службы под durable-журналом (T19)."""
    try:
        has_service = bool(is_installed())
    except Exception:  # noqa: BLE001
        has_service = True
    if not has_service:
        return _stop_impl(_NullJournal())  # откатывать нечего
    with _service_journal(app_root(), "stop") as journal:
        return _stop_impl(journal)


def _stop_impl(journal=None):
    if journal is None:
        journal = _NullJournal()
    # Сначала - корректный sc stop (SCM состояние), taskkill как страховка
    # для вручную запущенного winws2.
    _invalidate_service_cache()
    stop_ps, stop_msg = path_status()
    if stop_ps in ("mismatch", "unknown"):
        _svc_log(f"stop REFUSED: {stop_ps}: {stop_msg}")
        return False, ("Не удалось подтвердить, что служба zapret2 принадлежит "
                       f"этой копии: {stop_msg or stop_ps}. Не останавливаю её.")
    _svc_log("stop")
    code, out = _sc(["stop", SERVICE_NAME])
    # 1062 = служба не запущена (норма), 1056 = уже остановлена
    if code != 0 and "1062" not in out and "1056" not in out:
        _svc_log(f"stop: sc stop rc={code} out={out.strip()[:160]!r}")
    # Сначала дать SCM штатно остановить службу; taskkill до STOPPED мог
    # выглядеть как падение и запускать recovery через 60 с. Если штатно не
    # вышло - гасим процесс, временно сняв recovery.
    if _wait_service_stopped():
        _taskkill_winws2()
        journal.step("done")
        return True, "winws2 остановлен"
    paused = False
    try:
        pause_recovery()
        paused = True
    except Exception as e:  # noqa: BLE001
        _svc_log(f"stop: pause_recovery failed: {e!r}")
    try:
        _taskkill_winws2()
    finally:
        if paused:
            try:
                resume_recovery()
            except Exception as e:  # noqa: BLE001
                _svc_log(f"stop: resume_recovery failed: {e!r}")
    if not _wait_service_stopped():
        return False, ("служба не дошла до STOPPED за таймаут "
                       "(STOP_PENDING?) - проверьте состояние службы")
    journal.step("done")
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
# T19: pause/resume могут быть вложенными (repair -> start -> stop,
# install -> remove/start): без счётчика внутренний resume возвращал бы
# SCM-recovery посреди операции, и упавший winws2 поднимался бы за спиной.
# Совместимость: непарный resume по-прежнему no-op.
_recovery_refs: int = 0


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


def _recovery_owned() -> tuple[bool, str]:
    """Проверка владельца перед изменением failure actions службы."""
    try:
        state, detail = path_status()
    except Exception as e:  # noqa: BLE001
        return False, f"path_status: {e}"
    if state == "none":
        return False, "служба не установлена"
    if state in ("mismatch", "unknown", "orphaned"):
        return False, detail or state
    return True, ""


def pause_recovery() -> bool:
    """На время тестов/починки: отключаем sc.exe restart на время worker (L4).

    Читает ИСХОДНУЮ failure-конфигурацию (P1-3) и сохраняет её; при
    недоступности точного чтения - legacy sc qfailure, fail-closed: не
    прочитали - не мутируем SCM (внешнее ревью 14.10).

    T19: возвращает True, если пауза активна после вызова; вложенные вызовы
    увеличивают счётчик (resume снимет паузу только последним)."""
    global _recovery_paused, _recovery_was_on, _recovery_saved, _recovery_refs
    with _recovery_lock:
        if _recovery_paused:
            _recovery_refs += 1
            return True
        owned, why = _recovery_owned()
        if not owned:
            _svc_log(f"pause_recovery: пропущено ({why})")
            return False
        saved = _read_failure_actions_win32()
        if saved is not None:
            _recovery_saved = saved
            _recovery_was_on = any(t in (1, 2, 3) for t, _d in saved["actions"])
            if not _apply_failure_actions(0, []):
                _svc_log("pause_recovery: не удалось отключить failure actions "
                         "(fail-closed: пауза не выставлена)")
                _recovery_saved = None
                return False
            _recovery_paused = True
            _recovery_refs = 1
            _svc_log(f"pause_recovery: actions off (saved {saved['actions']})")
            return True
        # fail-closed (ревью 18.10): без точного чтения SCM НЕ мутируем.
        # Legacy-путь по подстрокам restart/перезапуск ломался на не-EN/RU
        # локалях: resume мог ОСТАВИТЬ failure actions выключенными.
        _svc_log("pause_recovery: точное чтение failure actions недоступно "
                 "- пауза пропущена (fail-closed)")
        return False


def _reset_recovery_state() -> None:
    """Служба удалена: пауза recovery больше не актуальна (её конфиг исчез).

    T19: без сброса _recovery_paused осталась бы True, и следующий
    install/start не смог бы снова отключить recovery для новой службы."""
    global _recovery_paused, _recovery_saved, _recovery_was_on, _recovery_refs
    with _recovery_lock:
        _recovery_refs = 0
        _recovery_paused = False
        _recovery_saved = None
        _recovery_was_on = False


def resume_recovery() -> None:
    global _recovery_paused, _recovery_saved, _recovery_refs
    with _recovery_lock:
        if _recovery_refs <= 0:
            return
        _recovery_refs -= 1
        if _recovery_refs > 0:
            return
        if not _recovery_paused:
            _recovery_saved = None
            return
        owned, why = _recovery_owned()
        if not owned:
            _svc_log(f"resume_recovery: пропущено ({why})")
            _recovery_paused = False
            _recovery_saved = None
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


def _failure_actions_disabled() -> bool:
    """Подтверждение, что auto-restart выключен (T19: remove + SCM-recovery).

    None-чтение (нет прав/не-Windows) не доказывает выключенность - отдаём
    False, решение принимает вызывающий (fail-open только для лога)."""
    saved = _read_failure_actions_win32()
    if saved is None:
        return False
    return not any(int(t) in (1, 2, 3) for t, _d in saved.get("actions") or [])


def recovery_snapshot() -> Optional[dict]:
    """Снимок активной паузы recovery (для журнала незавершённой сессии).

    None - пауза не активна; иначе {'was_on': bool, 'saved': {reset, actions}|None}
    (сериализуемо в JSON: actions - списки пар)."""
    with _recovery_lock:
        if not _recovery_paused:
            return None
        saved = _recovery_saved
        return {
            "was_on": _recovery_was_on,
            "saved": ({"reset": saved["reset"],
                       "actions": [list(a) for a in saved["actions"]]}
                      if saved else None),
        }


def restore_recovery_from_snapshot(snapshot: Optional[dict]) -> bool:
    """Восстановление recovery по снимку из журнала (после гибели GUI).

    Точная конфигурация приоритетна; legacy-снимок (только was_on) -
    возвращаем наши штатные restart/60000x3."""
    if not snapshot:
        return True
    owned, why = _recovery_owned()
    if not owned:
        _svc_log(f"restore_recovery: пропущено ({why})")
        return False
    saved = snapshot.get("saved")
    if saved is not None:
        ok = _apply_failure_actions(saved.get("reset", 0),
                                    saved.get("actions", []))
        if ok:
            _svc_log("restore_recovery: точная конфигурация возвращена из журнала")
        return ok
    if snapshot.get("was_on"):
        code, _out = _sc(["failure", SERVICE_NAME, "reset=", "86400",
                          "actions=", "restart/60000/restart/60000/restart/60000"])
        return code == 0
    return True


# ── T19/T10-1: durable-журнал mutating service-операций ────────────────────
# Гибель GUI/краш посреди install/remove/repair/start/stop оставлял службу
# удалённой/остановленной без записи о том, что должно было быть. Журнал
# logs/service_op_state.json пишется ДО первой мутации, обновляется по шагам
# и очищается после нормального завершения. На старте GUI
# recover_service_operation() откатывает/дозавершает операцию (см.
# server/session_recovery.start_startup_recovery). Внутри одной операции
# установки/починки вложенные вызовы (install -> remove/start) журнал НЕ
# перезаписывают: owner - самый внешний вызов.

SERVICE_JOURNAL_NAME = "service_op_state.json"
JOURNAL_TMP_SUFFIX = ".tmp"
# Шаги, после которых операция считается успешно доехавшей: если процесс
# умер между последним step() и удалением журнала, откатывать уже нечего.
_TERMINAL_STEPS = ("done",)

_journal_depth = 0
_recovering = False


class _NullJournal:
    """Вложенная операция: журнал ведёт самый внешний вызов."""

    def step(self, name: str) -> None:
        return


class _ServiceJournal:
    def __init__(self, root_dir: Path, action: str, prev: dict) -> None:
        self.root_dir = Path(root_dir)
        self.payload = {
            "state": "IN_PROGRESS",
            "action": action,
            "step": "begin",
            "started": datetime.datetime.now().isoformat(timespec="seconds"),
            "root": str(self.root_dir),
            "prev": prev,
        }
        self._closed = False
        _service_journal_write(self.root_dir, self.payload)

    def step(self, name: str) -> None:
        if self._closed:
            return
        self.payload["step"] = name
        _service_journal_write(self.root_dir, self.payload)

    def close(self) -> None:
        self._closed = True


def service_op_journal_path(root_dir: Path) -> Path:
    return Path(root_dir) / "logs" / SERVICE_JOURNAL_NAME


def _service_journal_write(root_dir: Path, payload: dict) -> None:
    """Атомарная запись журнала (tmp + os.replace); ошибки не бросаем.

    Журнал - страховка, а не условие операции: недоступный logs/ не должен
    ломать установку/удаление."""
    try:
        path = service_op_journal_path(root_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + JOURNAL_TMP_SUFFIX)
        tmp.write_text(json.dumps(payload, ensure_ascii=False,
                                  sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def read_service_op_journal(root_dir: Path) -> Optional[dict]:
    try:
        data = json.loads(
            service_op_journal_path(root_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def clear_service_op_journal(root_dir: Path) -> None:
    try:
        service_op_journal_path(root_dir).unlink(missing_ok=True)
    except OSError:
        pass


def _service_conf_path(root_dir: Path) -> Path:
    return Path(root_dir) / "logs" / "service_run.conf"


def _read_conf_b64(root_dir: Path) -> Optional[str]:
    try:
        path = _service_conf_path(root_dir)
        if not path.exists():
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except (OSError, ValueError):
        return None


def _write_conf_b64(root_dir: Path, data_b64: Optional[str]) -> tuple[bool, str]:
    """Восстановление logs/service_run.conf из журнала (атомарно)."""
    path = _service_conf_path(root_dir)
    try:
        if data_b64 is None:
            path.unlink(missing_ok=True)
            return True, ""
        raw = base64.b64decode(str(data_b64).encode("ascii"), validate=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".journal.tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, path)
        return True, ""
    except (OSError, ValueError) as e:  # noqa: BLE001
        return False, f"service_run.conf не восстановлен: {e}"


def _failure_to_json(failure: Optional[dict]) -> Optional[dict]:
    if not failure:
        return None
    try:
        return {
            "reset": int(failure.get("reset") or 0),
            "actions": [[int(t), int(d)] for t, d in (failure.get("actions") or [])],
        }
    except (TypeError, ValueError):
        return None


def _failure_from_json(data) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    actions: list[tuple[int, int]] = []
    for pair in data.get("actions") or []:
        try:
            actions.append((int(pair[0]), int(pair[1])))
        except (TypeError, ValueError, IndexError):
            continue
    try:
        reset = int(data.get("reset") or 0)
    except (TypeError, ValueError):
        reset = 0
    return {"reset": reset, "actions": actions}


def _normalize_binpath(value: str) -> str:
    return (value or "").replace('\\"', '"').strip()


def _is_legacy_binpath(native: str) -> bool:
    """Pre-0.11 служба: аргументы зашиты в binPath, @conf-токена нет."""
    try:
        from core.utils import split_windows_cmdline
        tokens = split_windows_cmdline(_normalize_binpath(native))
    except Exception:  # noqa: BLE001
        return False
    return len(tokens) >= 2 and not tokens[1].startswith("@")


def _snapshot_prev_state(root_dir: Path) -> dict:
    """Состояние службы/конфига ДО операции (для отката при краше)."""
    _invalidate_service_cache()
    installed = False
    running = False
    native = ""
    owner = ""
    failure: Optional[dict] = None
    try:
        owner, _detail = path_status()
    except Exception:  # noqa: BLE001
        owner = ""
    try:
        installed = bool(is_installed())
    except Exception:  # noqa: BLE001
        installed = False
    if installed:
        try:
            running = status() == "running"
        except Exception:  # noqa: BLE001
            running = False
        try:
            native = _read_stored_binpath()
        except Exception:  # noqa: BLE001
            native = ""
        try:
            failure = _read_failure_actions_win32()
        except Exception:  # noqa: BLE001
            failure = None
    return {
        "installed": installed,
        "running": running,
        "native": native,
        "owner": owner,
        "conf": _read_conf_b64(root_dir),
        "failure": _failure_to_json(failure),
    }


@contextlib.contextmanager
def _service_journal(root_dir: Optional[Path], action: str):
    """Журнал операции: пишется до мутации, очищается при нормальном выходе.

    Исключение или убийство процесса оставляет журнал -> recovery на старте."""
    global _journal_depth
    if _recovering or _journal_depth > 0:
        _journal_depth += 1
        try:
            yield _NullJournal()
        finally:
            _journal_depth -= 1
        return
    root = Path(root_dir) if root_dir is not None else app_root()
    journal = _ServiceJournal(root, action, _snapshot_prev_state(root))
    _journal_depth = 1
    try:
        yield journal
    except BaseException:
        # Журнал НЕ удаляем: операция прервалась нештатно -> recovery.
        raise
    else:
        clear_service_op_journal(root)
    finally:
        _journal_depth = 0
        journal.close()


# ── recovery незавершённой service-операции (старт GUI) ────────────────────

def _service_installed_safe() -> bool:
    try:
        _invalidate_service_cache()
        return bool(is_installed())
    except Exception:  # noqa: BLE001
        return False


def _service_running_safe() -> bool:
    try:
        _invalidate_service_cache()
        return status() == "running"
    except Exception:  # noqa: BLE001
        return False


def _create_service_native(native: str) -> tuple[bool, str]:
    """Создать службу с сохранённым binPath (Win32, fallback sc-bat)."""
    if not native:
        return False, "нет сохранённого binPath"
    ok, det = _win32_create_service(native)
    if ok:
        return True, ""
    _svc_log(f"service-recovery: Win32 create failed: {det} - fallback sc-bat")
    from core.utils import split_windows_cmdline
    tokens = split_windows_cmdline(native.replace('\\"', '"'))
    if len(tokens) == 2 and tokens[1].startswith("@"):
        cmdline = _service_cmdline(Path(tokens[0].strip('"')),
                                   Path(tokens[1][1:]))
        code, out = _sc_run_bat([
            f'sc create {SERVICE_NAME} binPath= "{cmdline}" '
            f'DisplayName= "Zapret 2 DPI Bypass" start= auto'])
        if code != 0:
            return False, f"sc create: {out.strip()}"
    else:
        return False, det or "CreateService"
    _sc(["description", SERVICE_NAME, "zapret DPI bypass (Zapret 2)"])
    return True, ""


def _change_service_native(native: str) -> tuple[bool, str]:
    """Переписать binPath службы на сохранённый (Win32, fallback sc-bat)."""
    if not native:
        return False, "нет сохранённого binPath"
    ok, det = _win32_change_service(native)
    if ok:
        return True, ""
    _svc_log(f"service-recovery: Win32 change failed: {det} - fallback sc-bat")
    from core.utils import split_windows_cmdline
    tokens = split_windows_cmdline(native.replace('\\"', '"'))
    if len(tokens) == 2 and tokens[1].startswith("@"):
        cmdline = _service_cmdline(Path(tokens[0].strip('"')),
                                   Path(tokens[1][1:]))
        code, out = _sc_run_bat([f'sc config {SERVICE_NAME} binPath= "{cmdline}"'])
        if code != 0:
            return False, f"sc config: {out.strip()}"
        return True, ""
    return False, det or "ChangeServiceConfig"


def _restore_prev_state(root_dir: Path, prev: dict, log) -> tuple[bool, str]:
    """Откат операции к снимку prev (служба + conf + failure actions + running)."""
    notes: list[str] = []
    ok_conf, msg_conf = _write_conf_b64(root_dir, prev.get("conf"))
    if not ok_conf:
        return False, msg_conf
    notes.append("service_run.conf восстановлен")
    want_installed = bool(prev.get("installed"))
    want_running = bool(prev.get("running"))
    native = _normalize_binpath(str(prev.get("native") or ""))
    installed = _service_installed_safe()
    if want_installed:
        if not installed:
            ok, det = _create_service_native(native)
            if not ok:
                return False, f"служба не восстановлена: {det}"
            notes.append("служба создана заново")
            installed = True
        else:
            stored = _normalize_binpath(_read_stored_binpath())
            if native and stored != native:
                ok, det = _change_service_native(native)
                if not ok:
                    return False, f"binPath не восстановлен: {det}"
                notes.append("binPath восстановлен")
        failure = _failure_from_json(prev.get("failure"))
        if failure is not None:
            if _apply_failure_actions(failure["reset"], failure["actions"]):
                notes.append("failure actions восстановлены")
            else:
                notes.append("failure actions не восстановлены")
        elif want_running:
            # Исходную конфигурацию прочитать не удалось (fail-closed чтение):
            # служба пересоздана без auto-restart - ставим штатную, иначе
            # падение winws2 оставит пользователя без обхода молча.
            _sc(["failure", SERVICE_NAME, "reset=", "86400", "actions=",
                 "restart/60000/restart/60000/restart/60000"])
            notes.append("failure actions: штатные (исходные не читались)")
        running = _service_running_safe()
        if want_running and not running:
            if _is_legacy_binpath(native):
                # Pre-0.11 служба хранила аргументы в binPath, conf-файла у
                # неё нет: start(None) отказал бы на валидации conf. Запускаем
                # SCM напрямую восстановленным legacy-binPath.
                code, out = _sc(["start", SERVICE_NAME])
                if code != 0 and "1056" not in out:
                    return False, f"legacy sc start: {out.strip()}"
                running = _service_running_safe()
                if not running:
                    return False, "legacy-служба не перешла в RUNNING"
                notes.append("служба запущена (legacy binPath)")
            else:
                ok, msg = start(None)
                if not ok:
                    return False, f"служба не запущена: {msg}"
                notes.append("служба запущена")
        elif not want_running and running:
            ok, msg = stop()
            if not ok:
                return False, f"служба не остановлена: {msg}"
            notes.append("служба остановлена")
    else:
        if installed:
            ok, msg = remove()
            if not ok:
                return False, f"новая служба не удалена: {msg}"
            notes.append("новая служба удалена (откат установки)")
    log("service-recovery: " + "; ".join(notes))
    return True, "; ".join(notes)


def _recover_service_op_data(root_dir: Path, data: dict, log) -> tuple[bool, str]:
    action = str(data.get("action") or "")
    step = str(data.get("step") or "")
    prev = data.get("prev")
    if not isinstance(prev, dict):
        prev = {}
    if step in _TERMINAL_STEPS:
        # Успешная операция: журнал не успел удалиться (убили процесс между
        # step("done") и unlink) - откат сделал бы хуже.
        return True, "операция уже завершена (журнал не очищен)"
    if action == "stop":
        if not _service_installed_safe() or not _service_running_safe():
            return True, "служба уже остановлена"
        ok, msg = stop()
        return (True, "служба остановлена") if ok else (False, f"stop: {msg}")
    if action == "start":
        if not _service_installed_safe():
            return False, "служба не установлена - запуск невозможен"
        if _service_running_safe():
            return True, "служба уже запущена"
        ok, msg = start(None)
        return (True, "служба запущена") if ok else (False, f"start: {msg}")
    if action == "remove" and step in ("deleted", "verified"):
        if not _service_installed_safe():
            return True, "служба уже удалена"
    if str(prev.get("owner") or "") == "orphaned":
        # Служба осталась от удалённой папки: восстановление её exe
        # невозможно; действие (install/remove/repair) логичнее довести до
        # удаления, чем оставлять заведомо мёртвую запись.
        if _service_installed_safe():
            ok, msg = remove()
            return ((True, "служба от удалённой копии удалена") if ok
                    else (False, f"remove: {msg}"))
        return True, "служба от удалённой копии уже удалена"
    # install/remove/repair/reconfigure/migrate и прочие мутации: безопаснее
    # вернуть исходное работающее состояние (пользователь остаётся с обходом).
    return _restore_prev_state(root_dir, prev, log)


def recover_service_operation(root_dir: Optional[Path] = None, *,
                              log=None) -> Optional[tuple[bool, str]]:
    """Recovery незавершённой service-операции (старт GUI, T10-1).

    Возвращает (ok, summary) или None, если журнала нет/операция не начата.
    При неудаче журнал сохраняется (attempts растёт, после 3 - RECOVERY_FAILED,
    чтобы не дёргать службу на каждом старте)."""
    global _recovering
    root = Path(root_dir) if root_dir is not None else app_root()
    if log is None:
        log = _svc_log
    data = read_service_op_journal(root)
    if not data or data.get("state") != "IN_PROGRESS":
        return None
    if _recovering:  # защита от рекурсии (recovery сам зовёт start/stop/remove)
        return None
    log("service-recovery: найдена незавершённая операция службы "
        f"(action={data.get('action')}, step={data.get('step')}, "
        f"started={data.get('started')})")
    # Recovery - такая же мутирующая операция службы: не пересекаемся с
    # install/remove/start из GUI (запуск GUI и клик пользователя могут
    # совпасть). Не дождались - журнал остаётся, попробуем на следующем старте.
    if not _op_lock.acquire(timeout=10.0):
        log("service-recovery: служба занята другой операцией - recovery пропущен")
        return None
    _recovering = True
    try:
        ok, summary = _recover_service_op_data(root, data, log)
    except Exception as e:  # noqa: BLE001
        ok, summary = False, f"исключение: {type(e).__name__}: {e}"
    finally:
        _recovering = False
        _op_lock.release()
    if ok:
        clear_service_op_journal(root)
        log(f"service-recovery: {summary}")
        return True, summary
    try:
        data["attempts"] = int(data.get("attempts") or 0) + 1
        data["last_error"] = summary
        data["last_attempt"] = datetime.datetime.now().isoformat(
            timespec="seconds")
        if data["attempts"] >= 3:
            data["state"] = "RECOVERY_FAILED"
        _service_journal_write(root, data)
    except Exception:  # noqa: BLE001
        pass
    log(f"service-recovery: НЕ восстановлено ({summary}); "
        "журнал сохранён для повторной попытки")
    return False, summary
