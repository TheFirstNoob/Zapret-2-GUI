r"""Проверка целостности JS-бандла (аудит #2).

  python tools/js_bundle_check.py

1. Все части из _JS_BUNDLE_PARTS существуют; в frontend/js/app/ нет
   осиротевших .js (каждый входит в бандл ровно один раз).
2. Склейка собирается; при наличии node - `node --check` (синтаксис JS).
Exit 0/1.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from server.server import _JS_BUNDLE_PARTS  # noqa: E402


def main() -> int:
    ok = True
    app_dir = REPO / "frontend" / "js" / "app"
    on_disk = {p.name for p in app_dir.glob("*.js")}
    listed = {Path(rel).name for rel in _JS_BUNDLE_PARTS}
    if len(_JS_BUNDLE_PARTS) != len(listed):
        print("FAIL: дубли в _JS_BUNDLE_PARTS")
        ok = False
    missing = sorted(listed - on_disk)
    orphans = sorted(on_disk - listed)
    if missing:
        print("FAIL: нет файлов:", missing)
        ok = False
    if orphans:
        print("FAIL: сироты (не в бандле):", orphans)
        ok = False
    try:
        body = b"\n".join((REPO / "frontend" / "js" / rel).read_bytes()
                          for rel in _JS_BUNDLE_PARTS)
    except OSError as e:
        print("FAIL: не собрать бандл:", e)
        return 1
    print(f"parts: {len(_JS_BUNDLE_PARTS)} | bytes: {len(body)}")

    node = None
    try:
        r = subprocess.run(["node", "--version"], capture_output=True,
                           text=True, timeout=10)
        if r.returncode == 0:
            node = (r.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    if node:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td) / "bundle.js"
            t.write_bytes(body)
            r = subprocess.run(["node", "--check", str(t)],
                               capture_output=True, text=True, timeout=30)
        good = r.returncode == 0
        print(("PASS" if good else "FAIL"), "node --check", node,
              (r.stderr or "")[:200])
        ok = ok and good
    else:
        # Ревью 18.10: молчаливый SKIP давал зелёный прогон без проверки
        # синтаксиса. Для чек-скрипта это FAIL.
        print("FAIL: node не найден (проверка синтаксиса обязательна)")
        ok = False

    print("ИТОГ:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
