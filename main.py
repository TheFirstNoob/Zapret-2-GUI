from __future__ import annotations

import ctypes
import os
import secrets
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

# Embeddable Python (portable-сборка) с ._pth не добавляет папку скрипта
# в sys.path - без этого импорт core на portable-сборке падает.
if not getattr(sys, "frozen", False):
    _app_dir = os.path.dirname(os.path.abspath(__file__))
    if _app_dir not in sys.path:
        sys.path.insert(0, _app_dir)

from core.admin import is_admin, relaunch_as_admin
from core.applog import log as _applog
from core.config import VERSION
from core.utils import known_desktop_dir, short_path


_DATA_DIRS = ["bin", "blobs", "lua", "presets", "lists", "windivert", "frontend"]


def _cleanup_stale_mei() -> None:
    """Убирает брошенные распаковки PyInstaller (%TEMP%\\_MEI*, старше 24ч):
    после аварийного выхода onefile оставляет их (живой webview или AV держит
    файл). Текущий _MEIPASS и свежие папки (чужие запуски) не трогаем."""
    if not getattr(sys, "frozen", False):
        return
    current = getattr(sys, "_MEIPASS", "")
    now = time.time()
    try:
        for d in Path(tempfile.gettempdir()).glob("_MEI*"):
            if str(d) == current:
                continue
            try:
                if now - d.stat().st_mtime > 24 * 3600:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        pass


def _warn_if_bad_path(exe_dir: Path) -> bool:
    """True, если путь установки безопасен для winws2.

    ASCII-путь (с пробелами) безопасен - лаунчеры его квотируют. Не-ASCII
    работает только при наличии короткого имени 8.3 (bat-лаунчеры пишутся
    в ASCII через короткие пути). Предупреждаем лишь о реальном провале:
    не-ASCII путь без короткой формы.
    """
    s = str(exe_dir)
    if all(ord(c) < 128 for c in s):
        return True
    if str(short_path(exe_dir)) != s:
        return True  # короткая форма есть - лаунчер справится

    title = "Zapret2 \u2014 \u041f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u0435"
    msg = (
        "\u041f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u0430 \u0440\u0430\u0441\u043f\u0430\u043a\u043e\u0432\u0430\u043d\u0430 \u0432 \u043f\u0430\u043f\u043a\u0443 \u0441 \u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0435\u0439 \u0438 \u0431\u0435\u0437 \u043a\u043e\u0440\u043e\u0442\u043a\u0438\u0445 \u0438\u043c\u0451\u043d (8.3):\n\n"
        f"{exe_dir}\n\n"
        "\u0417\u0430\u043f\u0443\u0441\u043a winws2 \u0431\u0443\u0434\u0435\u0442 \u0441\u043b\u043e\u043c\u0430\u043d.\n"
        "\u041f\u0435\u0440\u0435\u043c\u0435\u0441\u0442\u0438\u0442\u0435 Zapret2GUI.exe \u0432 \u043f\u0430\u043f\u043a\u0443 \u0431\u0435\u0437 \u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u044b,\n"
        "\u043d\u0430\u043f\u0440\u0438\u043c\u0435\u0440: C:\\Zapret2GUI\\"
    )
    ctypes.windll.user32.MessageBoxW(0, msg, title, 0x30)
    return False


def _ensure_data_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent

    exe_dir = Path(sys.executable).resolve().parent
    src = Path(sys._MEIPASS)

    # Обновляем данные только при смене версии: правки пользователя в
    # presets/lists переживают обычные запуски. copytree не удаляет лишние
    # файлы - user-пресеты и *-user.txt в безопасности.
    marker = exe_dir / "data_version.txt"
    try:
        current = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    except OSError:
        current = ""
    if current != VERSION:
        _applog("layout", f"data copy: marker={current!r} -> {VERSION!r} "
                          f"exe_dir={exe_dir}")
        for d in _DATA_DIRS:
            target = exe_dir / d
            try:
                shutil.copytree(src / d, target, dirs_exist_ok=True)
            except OSError as e:
                # файл под локом AV/OneDrive - молчаливая смерть pythonw
                # недопустима (M3): показываем причину и выходим чисто
                _applog("layout", f"data copy FAIL {d}: {e!r}")
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "Не удалось подготовить данные программы:\n\n"
                    f"{e}\n\nЗакройте антивирус/OneDrive, снимите залоченные "
                    "файлы и запустите снова.",
                    "Zapret2 - ошибка", 0x30)
                return None
        try:
            marker.write_text(VERSION, encoding="utf-8")
        except OSError as e:
            _applog("layout", f"marker write FAIL: {e!r}")

    _heal_missing_data(exe_dir, src)
    return exe_dir


def _heal_missing_data(exe_dir: Path, src: Path) -> None:
    """Докопировать из _MEIPASS критичные файлы, которых нет/битые рядом с exe.

    Маркер data_version.txt пишется ПОСЛЕ копирования, но AV/OneDrive могут
    забрать файл уже потом (или копия была частичной/обрезанной) - тогда смена
    версии не наступит и файл пропадёт навсегда. Лечим на каждом запуске:
    нет файла ИЛИ размер не совпал с источником -> перекопировать.
    """
    key_files = [
        "bin/winws2.exe", "bin/cygwin1.dll", "bin/WinDivert.dll",
        "bin/WinDivert64.sys",
        "lua/zapret-lib.lua", "lua/zapret-antidpi.lua",
        "lists/list-general.txt", "presets/default.txt",
    ]
    for rel in key_files:
        target = exe_dir / rel
        source = src / rel
        if not source.exists():
            continue
        reason = ""
        try:
            if not target.exists():
                reason = "нет файла"
            elif target.stat().st_size != source.stat().st_size:
                reason = (f"размер {target.stat().st_size} != "
                          f"источника {source.stat().st_size}")
        except OSError as e:
            reason = f"stat: {e}"
        if not reason:
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            _applog("layout", f"self-heal: восстановлен {rel} "
                              f"({reason}; стало {target.stat().st_size} байт)")
        except OSError as e:
            _applog("layout", f"self-heal FAIL {rel}: {e!r}")


def _log_layout(root_dir: Path) -> None:
    """Раскладка путей и ресурсов в лог: frozen/MEIPASS/exe (разбор сбоев у юзеров)."""
    import sys as _sys
    checks = [
        "bin/winws2.exe", "bin/cygwin1.dll", "bin/WinDivert.dll",
        "bin/WinDivert64.sys", "lua/zapret-lib.lua", "lua/zapret-antidpi.lua",
        "blobs/tls_clienthello_www_google_com.bin",
        "blobs/quic_initial_www_google_com.bin",
        "lists/list-general.txt", "presets/default.txt", "frontend/index.html",
    ]
    parts: list[str] = []
    miss: list[str] = []
    for c in checks:
        f = root_dir / c
        if not f.exists():
            miss.append(c)
            continue
        try:
            parts.append(f"{c}={f.stat().st_size}B")
        except OSError:
            parts.append(f"{c}=?")
    _applog("layout", f"frozen={bool(getattr(_sys, 'frozen', False))} "
                      f"exe={_sys.executable} file={__file__} "
                      f"meipass={getattr(_sys, '_MEIPASS', None)} "
                      f"cwd={Path.cwd()} root={root_dir}")
    _applog("layout", "resources: " + " ".join(parts) +
                      (f" | MISSING: {'; '.join(miss)}" if miss else ""))
    m = root_dir / "data_version.txt"
    try:
        marker = m.read_text(encoding="utf-8").strip() if m.exists() else ""
    except OSError:
        marker = "?"
    _applog("layout", f"data_version: marker={marker!r} app={VERSION!r}")


def _check_launch_location(exe_dir: Path) -> None:
    """Предупреждения о «болевых» местах запуска (0.8): архив/временная папка
    и рабочий стол напрямую - важные; Загрузки/Документы - некритичные
    (есть чек в «Проверке системы»)."""
    def show(msg: str) -> None:
        ctypes.windll.user32.MessageBoxW(
            0, msg, "Zapret2 - предупреждение", 0x30)

    s = str(exe_dir)
    low = s.lower() + "\\"
    try:
        in_temp = exe_dir.resolve().is_relative_to(
            Path(tempfile.gettempdir()).resolve())
    except OSError:
        in_temp = False
    if in_temp:
        show(
            "Программа запущена из архива (временная папка):\n\n"
            f"{s}\n\n"
            "При запуске из архива Windows распаковывает программу во временную "
            "папку - списки, пресеты и настройки будут потеряны при её очистке.\n\n"
            "Распакуйте ZIP в отдельную папку (например C:\\Zapret2GUI\\) "
            "и запускайте программу оттуда.")
        return
    desktop = known_desktop_dir()
    if desktop and exe_dir == desktop:
        show(
            "Программа запущена прямо с рабочего стола.\n\n"
            "При первом обновлении данных рядом с программой появятся папки "
            "и файлы (bin, lua, presets...) - рабочий стол замусорится.\n\n"
            "Создайте папку (например C:\\Zapret2GUI\\), перенесите программу "
            "туда и запускайте из подпапки.")
        return
    if "\\downloads\\" in low or low.rstrip("\\").endswith("\\downloads"):
        show(
            "Программа запущена из папки Загрузки.\n\n"
            "Файлы из браузера несут пометку «из интернета» - антивирус проверяет "
            "их агрессивнее, а папка часто чистится. Рекомендую перенести "
            "программу в отдельную папку (например C:\\Zapret2GUI\\).")
        return
    if "\\documents\\" in low or low.rstrip("\\").endswith("\\documents"):
        show(
            "Программа запущена из папки Документы.\n\n"
            "Папка может синхронизироваться (OneDrive) и блокировать файлы "
            "программы во время записи. Рекомендую отдельную папку вне "
            "синхронизации (например C:\\Zapret2GUI\\).")
        return


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def main_gui() -> None:
    if not is_admin():
        relaunch_as_admin()
        return

    _cleanup_stale_mei()

    try:
        import webview
    except Exception:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Не удалось загрузить интерфейс (webview).\n\n"
            "Убедитесь, что установлен WebView2 Runtime:\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/",
            "Zapret2 - ошибка", 0x30)
        return

    from server.server import init, create_server, stop_server

    print(f"[Zapret2 {VERSION}] Starting GUI...")

    root_dir = _ensure_data_dir()
    if root_dir is None:
        return
    _log_layout(root_dir)

    if getattr(sys, "frozen", False):
        if not _warn_if_bad_path(root_dir):
            return
        _check_launch_location(root_dir)

    app_token = secrets.token_hex(16)
    init(root_dir, app_token)

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    httpd = create_server("127.0.0.1", port)

    def run_server() -> None:
        httpd.serve_forever()

    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{base_url}/?token={app_token}", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    def on_closing() -> None:
        print("[zapret2] Window closing, shutting down...")
        stop_server()
        try:
            from server.server import _tester
            if _tester:
                _tester.signal_shutdown()
        except Exception:
            pass
        try:
            from core.utils import run_quiet
            run_quiet(["pktmon", "stop"])
            run_quiet(["pktmon", "filter", "remove"])
        except Exception:
            pass

    window = webview.create_window(
        "Zapret2 Manager",
        f"{base_url}/?token={app_token}",
        width=1280, height=840, min_size=(900, 600),
    )
    try:
        window.events.closing += on_closing
        webview.start()
    except Exception:
        # у pythonw нет консоли - молча падать нельзя.
        ctypes.windll.user32.MessageBoxW(
            0,
            "Ошибка запуска интерфейса (WebView2).\n\n"
            "Убедитесь, что установлен WebView2 Runtime:"
            " https://developer.microsoft.com/microsoft-edge/webview2/",
            "Zapret2 - ошибка", 0x30)
    print("[zapret2] Goodbye.")


if __name__ == "__main__":
    main_gui()