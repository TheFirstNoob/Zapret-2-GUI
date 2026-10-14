from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


def short_path(path: Path) -> Path:
    """Короткий путь 8.3; если короткие имена недоступны - исходный путь."""
    try:
        long_name = str(path.resolve())
        buf = ctypes.create_unicode_buffer(260)
        res = ctypes.windll.kernel32.GetShortPathNameW(long_name, buf, 260)
        if res and res < 260:
            return Path(buf.value)
    except Exception:
        pass
    return path


def app_root() -> Path:
    """Каталог программы: рядом с exe (frozen onefile) или корень проекта.

    ВАЖНО: в PyInstaller-onefile `Path(__file__).parent.parent` указывает в
    ВРЕМЕННУЮ папку `_MEI*` - её нельзя использовать для путей службы и
    драйвера: папка исчезает после закрытия программы, а запущенный из неё
    процесс ещё и блокирует удаление («Failed to remove temporary
    directory _MEI…», кейс 0.7.1)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_temp_dir() -> Path:
    """Постоянный temp-каталог для артефактов probe (etl/txt, отчёты)."""
    d = Path(tempfile.gettempdir()) / "zapret2_probe"
    d.mkdir(exist_ok=True)
    return d


def windivert_image_path(image: str) -> str:
    """Чистый путь .sys из ImagePath.

    Формат Windows: ``\\??\\C:\\...\\WinDivert64.sys`` (одиночный слеш перед
    ``??``), при этом путь может содержать пробелы. Поэтому сначала проверяем
    полный путь и только потом пробуем отбросить аргументы."""
    img = (image or "").strip().strip('"')
    prefix = "\\??\\"
    if img.startswith(prefix):
        img = img[len(prefix):]
    try:
        if Path(img).exists():
            return img
    except OSError:
        pass
    first = img.split(" ")[0]
    try:
        if Path(first).exists():
            return first
    except OSError:
        pass
    return first or img


def windivert_image_dead(image: str) -> str:
    """Путь ImagePath, если файл драйвера НЕ существует; иначе ""."""
    path = windivert_image_path(image)
    try:
        return "" if path and Path(path).exists() else path
    except OSError:
        return ""


def stale_windivert_services() -> list[tuple[str, str]]:
    """Службы драйвера WinDivert с БИТЫМ ImagePath (файл не существует).

    Служба драйвера «WinDivert» ставится ОДИН РАЗ и навсегда запоминает путь
    к .sys. Если на машине раньше стоял другой zapret (Zapret 1 / Flowseal-
    бандл - WinDivert той же мажорной версии) и его папку удалили - служба
    остаётся с мёртвым ImagePath → наш winws2 видит «служба уже есть» (версия
    совпадает), StartService по мёртвому пути → windivert: error opening
    filter: The system cannot find the file specified - НАВСЕГДА, пока службу
    не удалить вручную (кейс друга 2026-09-13)."""
    import winreg
    bad: list[tuple[str, str]] = []
    try:
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Services") as k:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(k, i)
                    i += 1
                except OSError:
                    break
                if not name.lower().startswith("windivert"):
                    continue
                try:
                    with winreg.OpenKey(k, name) as sk:
                        image = winreg.QueryValueEx(sk, "ImagePath")[0]
                except OSError:
                    continue
                dead = windivert_image_dead(str(image))
                if dead:
                    bad.append((name, dead))
    except OSError:
        pass
    return bad


def run_sc(args: list[str]) -> tuple[int, str]:
    """sc.exe с кодом возврата и выводом (детект 1072 «marked for deletion»)."""
    try:
        r = subprocess.run(
            ["sc", *args], capture_output=True, text=True, encoding="oem",
            errors="replace", timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception:
        return -1, ""


def _is_marked_for_delete(out: str) -> bool:
    lowered = out.lower()
    return "1072" in out or "marked for deletion" in lowered or "отмечен" in lowered


def winws2_running() -> bool:
    """winws2.exe запущен? (общий CSV-детектор из core.proc, аудит #7)."""
    from core.proc import image_running
    return image_running("winws2.exe", timeout=10)


def _local_windivert_sys(root_dir: Optional[Path]) -> Optional[Path]:
    """НАШ WinDivert64.sys - цель для перезаписи битого ImagePath."""
    candidates: list[Path] = []
    if root_dir is not None:
        candidates += [Path(root_dir) / "bin" / "WinDivert64.sys",
                       Path(root_dir) / "WinDivert64.sys"]
    base = app_root()
    candidates += [base / "bin" / "WinDivert64.sys", base / "WinDivert64.sys"]
    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def windivert_service_state() -> Optional[tuple[str, int]]:
    """(ImagePath, Start) службы драйвера «WinDivert» - общий ридер для
    heal'а и диагностики (None, если службы нет)."""
    import winreg
    try:
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Services\WinDivert") as sk:
            image = winreg.QueryValueEx(sk, "ImagePath")[0]
            try:
                start = int(winreg.QueryValueEx(sk, "Start")[0])
            except OSError:
                start = 3
            return str(image), start
    except OSError:
        return None


def windivert_delete_flag(name: str = "WinDivert") -> int:
    """DeleteFlag службы драйвера: 1 - помечена на удаление, 0 - нет,
    -1 - службы нет. «Помечена» = отложенное удаление ждёт выгрузки драйвера
    (кейс «bin не заменяется, просит перезагрузку»)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            rf"SYSTEM\CurrentControlSet\Services\{name}") as sk:
            try:
                return int(winreg.QueryValueEx(sk, "DeleteFlag")[0])
            except OSError:
                return 0
    except OSError:
        return -1


def _windivert_unload_now(name: str) -> bool:
    """sc stop + ожидание выгрузки драйвера. True - очищено без перезагрузки.

    Пока драйвер загружен (его держит winws2/winws), «marked for deletion»
    не завершается и bin-файлы заняты; stop выгружает драйвер - отложенное
    удаление после этого завершается само (проверено автором руками)."""
    import time as _time
    run_sc(["stop", name])
    for _ in range(10):
        _time.sleep(0.4)
        flag = windivert_delete_flag(name)
        if flag == -1:
            return True
        if flag == 0 and not any(n.lower() == name.lower()
                                 for n, _i in stale_windivert_services()):
            return True
    return False


def windivert_emergency_unload(names: Optional[list[str]] = None) -> list[str]:
    """Немедленная выгрузка зависшего WinDivert (действие кнопки «Починить»).

    Вызывать ПОСЛЕ остановки winws2/winws - иначе драйвер занят и stop не
    поможет. Возвращает список действий для лога/диагностики."""
    actions: list[str] = []
    for name in (names or ["WinDivert"]):
        flag = windivert_delete_flag(name)
        if flag == -1:
            continue
        if _windivert_unload_now(name):
            actions.append(f"{name}: выгружен (stop, без перезагрузки)")
        else:
            actions.append(f"{name}: драйвер занят - stop не помог")
    return actions


def fix_stale_windivert_services(root_dir: Optional[Path] = None) -> list[str]:
    """Починить службу драйвера WinDivert (кейс друга 2026-09-13).

    Тактика без лишних удалений: (1) битый ImagePath главной службы
    «WinDivert» перезаписываем sc config на НАШ WinDivert64.sys (repair);
    (2) Start=Disabled у живой службы включаем (start= demand); (3) удаляем
    только когда иначе нельзя и winws2 НЕ запущен (иначе служба получит
    «marked for deletion» (1072) и починится только перезагрузкой);
    (4) чужие службы windivert* с битым путём - прежний путь удаления.
    Возвращает список действий (для логов/диагностики)."""
    actions: list[str] = []
    winws2_busy = winws2_running()
    local_sys = _local_windivert_sys(root_dir)

    for name, _image in stale_windivert_services():
        is_main = name.lower() == "windivert"
        if is_main and local_sys is not None:
            code, out = run_sc(["config", name, "binPath=",
                             "\\??\\" + str(local_sys), "start=", "demand"])
            if code == 0:
                actions.append(f"{name}: ImagePath перезаписан на {local_sys}")
                continue
            if _is_marked_for_delete(out):
                if winws2_busy:
                    actions.append(f"{name}: помечена на удаление (winws2 запущен) - "
                                   "остановите обход и нажмите «Починить»")
                elif _windivert_unload_now(name):
                    actions.append(f"{name}: очищена stop'ом без перезагрузки")
                else:
                    actions.append(f"{name}: помечена на удаление - нужна перезагрузка")
                continue
            actions.append(f"{name}: repair не удался - {out.strip()[:100]}")
        if is_main and winws2_busy:
            actions.append(f"{name}: удаление отложено (winws2 запущен)")
            continue
        run_sc(["stop", name])
        code, out = run_sc(["delete", name])
        if code == 0:
            actions.append(f"{name}: удалена (драйвер пересоздастся сам)")
        elif _is_marked_for_delete(out):
            if _windivert_unload_now(name):
                actions.append(f"{name}: очищена stop'ом без перезагрузки")
            else:
                actions.append(f"{name}: помечена на удаление - нужна перезагрузка")
        else:
            actions.append(f"{name}: удаление не удалось - {out.strip()[:100]}")

    state = windivert_service_state()
    if state is not None and state[1] == 4 and not any(
            a.startswith("WinDivert:") for a in actions):
        code, out = run_sc(["config", "WinDivert", "start=", "demand"])
        if code == 0:
            actions.append("WinDivert: включена (start= demand)")
        elif _is_marked_for_delete(out):
            if _windivert_unload_now("WinDivert"):
                actions.append("WinDivert: очищена stop'ом без перезагрузки")
            else:
                actions.append("WinDivert: отключена и помечена на удаление - нужна перезагрузка")
        else:
            actions.append(f"WinDivert: включить не удалось - {out.strip()[:100]}")
    return actions


def known_desktop_dir() -> Path:
    """Реальный рабочий стол через SHGetKnownFolderPath (учитывает
    OneDrive-редирект Known Folder). Фолбэк - профиль\\Desktop.

    Явные argtypes/restype - best practice ctypes на x64 (сигнатуры
    снимают вопросы по умолчанию)."""
    try:
        import ctypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort),
                        ("Data4", ctypes.c_ubyte * 8)]

        g = _GUID()
        # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
        g.Data1, g.Data2, g.Data3 = 0xB4BFCC3A, 0xDB2C, 0x4C24
        g.Data4 = (ctypes.c_ubyte * 8)(
            0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41)
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID), ctypes.c_ulong,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT
        buf = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(
                ctypes.byref(g), 0, None, ctypes.byref(buf)) == 0:
            path = Path(buf.value).resolve()
            ctypes.windll.ole32.CoTaskMemFree(buf)
            return path
    except (OSError, AttributeError):
        pass
    return (Path(os.path.expanduser("~")) / "Desktop").resolve()


def run_quiet(cmd: list[str], timeout: int = 30) -> None:
    """Тихий запуск команды; ошибки игнорируются (best-effort хелпер)."""
    try:
        subprocess.run(cmd, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass


def split_windows_cmdline(s: str) -> list[str]:
    """Разбор командной строки Windows на аргументы (CommandLineToArgvW).

    Точный парсер SCM/CRT: кавычки снимаются (в т.ч. форма `@"path"` ->
    `@path`), backslash-кавычки учитываются. Фолбэк - regex.
    """
    if not s or not s.strip():
        return []
    try:
        import ctypes
        import ctypes.wintypes as wt
        sh = ctypes.WinDLL("shell32", use_last_error=True)
        sh.CommandLineToArgvW.restype = ctypes.POINTER(wt.LPWSTR)
        sh.CommandLineToArgvW.argtypes = [wt.LPCWSTR,
                                          ctypes.POINTER(ctypes.c_int)]
        n = ctypes.c_int(0)
        arr = sh.CommandLineToArgvW(s, ctypes.byref(n))
        if arr:
            try:
                return [arr[i] for i in range(n.value)]
            finally:
                k32 = ctypes.WinDLL("kernel32")
                k32.LocalFree.argtypes = [ctypes.c_void_p]
                k32.LocalFree.restype = None
                k32.LocalFree(arr)
    except Exception:  # noqa: BLE001
        pass
    import re
    return [m.group(1) if m.group(1) is not None else m.group(2)
            for m in re.finditer(r'"([^"]*)"|(\S+)', s)]