"""Запуск/остановка кандидата для голосового канала (служба <-> winws2 cand).

  python tools/voice_cand.py start [preset]   # стоп службы, winws2 cand
  python tools/voice_cand.py stop             # снять cand, поднять службу
  python tools/voice_cand.py status

Ход теста: start -> переподключиться в голосовом канале (новый поток) ->
наблюдать через tools/voice_flap_watch.py -> stop (вернуть как было).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _run(args, timeout=20):
    r = subprocess.run(args, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return (r.stdout or "") + (r.stderr or "")


def _winws2_pids() -> list[str]:
    out = _run(["tasklist", "/FI", "IMAGENAME eq winws2.exe", "/NH"])
    return [ln.split()[1] for ln in out.splitlines() if "winws2.exe" in ln]


def cmd_start(preset: str) -> int:
    from core.service_manager import stop as svc_stop
    from core.launcher import build_args_from_preset, launch_winws2

    svc_stop()
    time.sleep(1.5)
    for pid in _winws2_pids():
        _run(["taskkill", "/F", "/PID", pid])
    time.sleep(0.7)

    p = REPO / "presets" / f"{preset}.txt"
    if not p.exists():
        print(f"нет пресета {p}")
        return 1
    args = build_args_from_preset(
        REPO, REPO / "lua", REPO / "blobs", p,
        lists_dir=REPO / "lists", windivert_dir=REPO / "windivert",
        debug=False)
    exe = REPO / "bin" / "winws2.exe"
    ok = launch_winws2(REPO, exe, args, timeout=5.0)
    time.sleep(1.0)
    pids = _winws2_pids()
    print(f"кандидат «{preset}»: запуск={'ok' if ok else 'FAIL'}, "
          f"winws2 PID={pids}")
    if not ok or not pids:
        print("кандидат не поднялся — верни службу: voice_cand.py stop")
        return 1
    print("теперь переподключись в голосовом канале и смотри "
          "tools/voice_flap_watch.py")
    return 0


def cmd_stop() -> int:
    from core.service_manager import start as svc_start
    for pid in _winws2_pids():
        _run(["taskkill", "/F", "/PID", pid])
    time.sleep(0.7)
    ok, msg = svc_start()
    print(f"служба восстановлена: {ok} {msg}")
    return 0 if ok else 1


def cmd_status() -> int:
    print("winws2 pids:", _winws2_pids() or "нет")
    print(_run(["sc", "query", "zapret2"]).splitlines()[3:4])
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "start":
        if len(sys.argv) < 3:
            print("укажи пресет: python tools/voice_cand.py start <preset>")
            sys.exit(1)
        sys.exit(cmd_start(sys.argv[2]))
    if mode == "stop":
        sys.exit(cmd_stop())
    sys.exit(cmd_status())
