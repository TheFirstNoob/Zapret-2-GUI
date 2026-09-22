"""Скриншоты UI через headless Edge по локальному серверу (для ревью).

Запуск: python tools/_ui_shots.py [страницы...]
Пишет PNG в %TEMP%\\z2shots\\. Сервер поднимается на корне зеркала.
"""
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(r"C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI")
MIR = Path(r"C:\Users\TheFirstNoob\Desktop\Zapret 2 GUI\zapret2_gui")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
OUT = Path(tempfile.gettempdir()) / "z2shots"
sys.path.insert(0, str(REPO))

from server import server as srv  # noqa: E402

PAGES = sys.argv[1:] or ["main", "diagnostics", "tester", "lists",
                         "contested", "games", "cdn", "asn", "probe"]

OUT.mkdir(exist_ok=True)
srv.init(MIR, token="")
s = srv.create_server("127.0.0.1", 0)
port = s.server_address[1]
threading.Thread(target=s.serve_forever, daemon=True).start()
time.sleep(1.0)

def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


profile = Path(tempfile.gettempdir()) / "z2edge_profile"
for page in PAGES:
    png = OUT / f"{page}.png"
    png.unlink(missing_ok=True)
    url = f"http://127.0.0.1:{port}/#{page}"
    # Edge, запущенный напрямую из python, мгновенно «прокидывается» в живой
    # инстанс и выходит; через Start-Process отрабатывает нормально.
    prof = Path(tempfile.gettempdir()) / f"z2edge_{page}"
    arg_list = ",".join(_ps_quote(a) for a in (
        "--headless", "--disable-gpu", "--hide-scrollbars",
        "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={prof}", "--window-size=1440,900",
        "--virtual-time-budget=6000", f"--screenshot={png}", url))
    ps = (f"Start-Process -FilePath {_ps_quote(EDGE)} "
          f"-ArgumentList {arg_list} -Wait")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=150,
                   creationflags=0x08000000)
    ok = png.exists() and png.stat().st_size > 5000
    print(f"{page:12s} {'OK' if ok else 'FAIL'} "
          f"{png.stat().st_size if png.exists() else 0} bytes")
s.shutdown()
print("shots:", OUT)
