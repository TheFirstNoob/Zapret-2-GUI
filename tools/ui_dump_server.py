"""Dev tool: real Zapret2 backend on a fixed port for UI layout dumps.

Usage:
    python ui_dump_server.py
Serves http://127.0.0.1:18888/?token=dump until Ctrl+C.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from server.server import init, create_server, stop_server  # noqa: E402

HOST = "127.0.0.1"
PORT = 18888
TOKEN = "dump"


def main() -> None:
    init(APP_ROOT, TOKEN)
    httpd = create_server(HOST, PORT)
    print(f"UI dump server: http://{HOST}:{PORT}/?token={TOKEN}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_server()
        print("stopped")


if __name__ == "__main__":
    main()