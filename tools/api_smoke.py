r"""Смоук-стенд HTTP-API (репо-локальный; службу/сеть НЕ трогает).

  python tools/api_smoke.py          # порт 18899 по умолчанию
  python tools/api_smoke.py 18999    # свой порт

Поднимает реальный сервер (init+create_server) и проверяет ключевые роуты:
endpoints 200/ok, 404 на неизвестные, 403 без токена, 404 static-miss.
Exit 0/1. Использовался для приёмки таблиц роутов (аудит #1).
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from server.server import init, create_server, stop_server  # noqa: E402
import server.server as S  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18899
TOKEN = "tok"


def main() -> int:
    init(str(REPO), TOKEN)
    httpd = create_server("127.0.0.1", PORT)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)
    print(f"routes: {len(S._GET_ROUTES)} GET / {len(S._POST_ROUTES)} POST")

    def get(path, token=True):
        h = {"X-App-Token": TOKEN} if token else {}
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}" + path, headers=h)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())

    def post(path, data=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}" + path, method="POST",
            data=json.dumps(data or {}).encode(),
            headers={"X-App-Token": TOKEN, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())

    ok = True
    for path in ("/api/version", "/api/status", "/api/config", "/api/profiles",
                 "/api/service/status", "/api/bundled-domains",
                 "/api/fake-blobs", "/api/process-probe/status", "/api/games",
                 "/api/zapret1/strategies", "/api/contested/status",
                 "/api/lists/health", "/api/diagnose/status"):
        try:
            st, j = get(path)
            good = st == 200 and j.get("status") == "ok"
            print(("PASS" if good else "FAIL"), "GET", path, st, j.get("status"))
            ok = ok and good
        except Exception as e:  # noqa: BLE001
            print("FAIL GET", path, repr(e)[:120])
            ok = False

    try:
        st, j = get("/api/tester/status")
        good = st == 200 and "running" in j
        print(("PASS" if good else "FAIL"), "GET /api/tester/status", st)
        ok = ok and good
    except Exception as e:  # noqa: BLE001
        print("FAIL GET tester/status", repr(e)[:120])
        ok = False

    try:
        st, _j = post("/api/frontend-log", {"msg": "smoke"})
        print(("PASS" if st == 200 else "FAIL"), "POST /api/frontend-log", st)
        ok = ok and st == 200
    except Exception as e:  # noqa: BLE001
        print("FAIL POST frontend-log", repr(e)[:120])
        ok = False

    try:
        post("/api/nope")
        print("FAIL POST unknown: не вернул 404")
        ok = False
    except urllib.error.HTTPError as e:
        print(("PASS" if e.code == 404 else "FAIL"), "POST unknown ->", e.code)
        ok = ok and e.code == 404

    try:
        get("/nope.js")
        print("FAIL GET static-miss: не вернул 404")
        ok = False
    except urllib.error.HTTPError as e:
        print(("PASS" if e.code == 404 else "FAIL"), "GET static-miss ->", e.code)
        ok = ok and e.code == 404

    try:
        get("/api/version", token=False)
        print("FAIL: без токена прошло")
        ok = False
    except urllib.error.HTTPError as e:
        print(("PASS" if e.code == 403 else "FAIL"), "GET без токена ->", e.code)
        ok = ok and e.code == 403

    stop_server()
    print("ИТОГ:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
