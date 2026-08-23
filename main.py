from __future__ import annotations

import ctypes
import secrets
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

from core.admin import is_admin, relaunch_as_admin
from core.config import VERSION
from core.utils import short_path


_DATA_DIRS = ["bin", "blobs", "lua", "presets", "lists", "windivert", "frontend"]


def _warn_if_bad_path(exe_dir: Path) -> bool:
    """Return True when the install path is safe for winws2.

    ASCII paths (spaces included) are safe — launchers quote them correctly.
    Non-ASCII paths only work while 8.3 short names are available (the .bat
    launchers are written in ASCII via short paths).  Warn only for the real
    failure class: non-ASCII path with no short form.
    """
    s = str(exe_dir)
    if all(ord(c) < 128 for c in s):
        return True
    if str(short_path(exe_dir)) != s:
        return True  # short form exists — launcher handles it

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

    # Refresh bundled data only when the application version changes so user
    # edits to bundled presets/lists survive regular launches.  copytree never
    # deletes extra files — user-added presets and *-user.txt lists are safe.
    marker = exe_dir / "data_version.txt"
    try:
        current = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    except OSError:
        current = ""
    if current != VERSION:
        for d in _DATA_DIRS:
            target = exe_dir / d
            shutil.copytree(src / d, target, dirs_exist_ok=True)
        try:
            marker.write_text(VERSION, encoding="utf-8")
        except OSError:
            pass

    return exe_dir


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def main_gui() -> None:
    if not is_admin():
        relaunch_as_admin()
        return

    import webview

    from server.server import init, create_server, stop_server

    print(f"[Zapret2 {VERSION}] Starting GUI...")

    root_dir = _ensure_data_dir()

    if getattr(sys, "frozen", False):
        if not _warn_if_bad_path(root_dir):
            return

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

    window = webview.create_window(
        "Zapret2 Manager",
        f"{base_url}/?token={app_token}",
        width=1200, height=800, min_size=(900, 600),
    )
    window.events.closing += on_closing
    webview.start()
    print("[zapret2] Goodbye.")


if __name__ == "__main__":
    main_gui()
