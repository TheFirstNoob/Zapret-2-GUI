from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def short_path(path: Path) -> Path:
    """Windows short (8.3) path; falls back to the original when short
    names are disabled or unavailable."""
    try:
        long_name = str(path.resolve())
        buf = ctypes.create_unicode_buffer(260)
        res = ctypes.windll.kernel32.GetShortPathNameW(long_name, buf, 260)
        if res and res < 260:
            return Path(buf.value)
    except Exception:
        pass
    return path


def get_temp_dir() -> Path:
    """Stable temp dir for probe artifacts (probe etl/txt, reports)."""
    d = Path(tempfile.gettempdir()) / "zapret2_probe"
    d.mkdir(exist_ok=True)
    return d


def windivert_image_dead(image: str) -> str:
    """Путь ImagePath, если файл драйвера НЕ существует; иначе "".

    ImagePath вида «\\??\\C:\\...\\WinDivert64.sys» — префикс \\??\\ отрезаем,
    аргументы после пути (если есть) отбрасываем."""
    img = image.strip().strip('"')
    if img.startswith(chr(92) * 2 + "??" + chr(92)):
        img = img[4:]
    img_first = img.split(" ")[0]
    try:
        return "" if Path(img_first).exists() else img_first
    except OSError:
        return ""


def stale_windivert_services() -> list[tuple[str, str]]:
    """Службы драйвера WinDivert с БИТЫМ ImagePath (файл не существует).

    Служба драйвера «WinDivert» ставится ОДИН РАЗ и навсегда запоминает путь
    к .sys. Если на машине раньше стоял другой zapret (Zapret 1 / Flowseal-
    бандл — WinDivert той же мажорной версии) и его папку удалили — служба
    остаётся с мёртвым ImagePath → наш winws2 видит «служба уже есть» (версия
    совпадает), StartService по мёртвому пути → windivert: error opening
    filter: The system cannot find the file specified — НАВСЕГДА, пока службу
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
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq winws2.exe"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        return False
    text = r.stdout or ""
    return "winws2.exe" in text and "No tasks" not in text


def _local_windivert_sys(root_dir: Optional[Path]) -> Optional[Path]:
    """НАШ WinDivert64.sys — цель для перезаписи битого ImagePath."""
    candidates: list[Path] = []
    if root_dir is not None:
        candidates += [Path(root_dir) / "bin" / "WinDivert64.sys",
                       Path(root_dir) / "WinDivert64.sys"]
    base = Path(__file__).resolve().parent.parent
    candidates += [base / "bin" / "WinDivert64.sys", base / "WinDivert64.sys"]
    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def windivert_service_state() -> Optional[tuple[str, int]]:
    """(ImagePath, Start) службы драйвера «WinDivert» — общий ридер для
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


def fix_stale_windivert_services(root_dir: Optional[Path] = None) -> list[str]:
    """Починить службу драйвера WinDivert (кейс друга 2026-09-13).

    Тактика без лишних удалений: (1) битый ImagePath главной службы
    «WinDivert» перезаписываем sc config на НАШ WinDivert64.sys (repair);
    (2) Start=Disabled у живой службы включаем (start= demand); (3) удаляем
    только когда иначе нельзя и winws2 НЕ запущен (иначе служба получит
    «marked for deletion» (1072) и починится только перезагрузкой);
    (4) чужие службы windivert* с битым путём — прежний путь удаления.
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
                actions.append(f"{name}: помечена на удаление — нужна перезагрузка")
                continue
            actions.append(f"{name}: repair не удался — {out.strip()[:100]}")
        if is_main and winws2_busy:
            actions.append(f"{name}: удаление отложено (winws2 запущен)")
            continue
        run_sc(["stop", name])
        code, out = run_sc(["delete", name])
        if code == 0:
            actions.append(f"{name}: удалена (драйвер пересоздастся сам)")
        elif _is_marked_for_delete(out):
            actions.append(f"{name}: помечена на удаление — нужна перезагрузка")
        else:
            actions.append(f"{name}: удаление не удалось — {out.strip()[:100]}")

    state = windivert_service_state()
    if state is not None and state[1] == 4 and not any(
            a.startswith("WinDivert:") for a in actions):
        code, out = run_sc(["config", "WinDivert", "start=", "demand"])
        if code == 0:
            actions.append("WinDivert: включена (start= demand)")
        elif _is_marked_for_delete(out):
            actions.append("WinDivert: отключена и помечена на удаление — нужна перезагрузка")
        else:
            actions.append(f"WinDivert: включить не удалось — {out.strip()[:100]}")
    return actions


def known_desktop_dir() -> Path:
    """Реальный рабочий стол через SHGetKnownFolderPath (учитывает
    OneDrive-редирект Known Folder). Фолбэк — профиль\\Desktop.

    Явные argtypes/restype — best practice ctypes на x64 (сигнатуры
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
    """Run a command silently; failures are ignored (best-effort helpers)."""
    try:
        subprocess.run(cmd, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass