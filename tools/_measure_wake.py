"""Wake-up profiler: сколько времени winws2 реально «просыпается» после старта.

Не «N попыток до успеха», а интервальный график: проба каждые 0.5с с момента
запуска движка (curl timeout 2с — чтобы не блокировать цикл), лог всех проб.
Отвечает на гипотезу «служба долго просыпается»: если первые 20-30с идут 000,
а потом вдруг 200 — это пробуждение движка; если 200 с первой пробы — служба
ни при чём (это было окно ТСПУ/флак клиента).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

MIR = Path(r"C:\Users\TheFirstNoob\Desktop\Zapret 2 GUI\zapret2_gui")
REPO = Path(r"C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI")
sys.path.insert(0, str(REPO))

from core.launcher import build_args_from_preset, validate_args  # noqa: E402

HOST = "updates.discord.com"
PROBE_INTERVAL = 0.5   # сек между пробами
PROBE_TIMEOUT = 2      # curl -m
DURATION = 40          # сколько секунд наблюдать


def build(profile: str = "default") -> list[str]:
    args = build_args_from_preset(
        MIR, MIR / "lua", MIR / "blobs", MIR / "presets" / f"{profile}.txt",
        lists_dir=MIR / "lists", windivert_dir=MIR / "windivert",
        debug=False, game_filter_mode="off", discord_voice=False,
        discord_voice_mode="", autohostlist=False, ipset_catchall=False)
    ok, err = validate_args(MIR / "bin" / "winws2.exe", args, cwd=MIR)
    if not ok:
        raise RuntimeError(f"validate fail: {err}")
    return args


def kill_winws():
    subprocess.run(["taskkill", "/F", "/IM", "winws2.exe"],
                   capture_output=True, creationflags=0x08000000)


def probe_once() -> tuple[float, str]:
    t0 = time.time()
    r = subprocess.run(
        ["curl.exe", "-4", "-s", "-o", "NUL", "-m", str(PROBE_TIMEOUT),
         "-w", "%{http_code}", f"https://{HOST}/"],
        capture_output=True, text=True, encoding="oem", errors="replace",
        creationflags=0x08000000)
    dt = time.time() - t0
    code = (r.stdout or "").strip()
    return dt, (code if code else "000")


def run(profile: str = "default", duration: int = DURATION) -> None:
    kill_winws()
    time.sleep(1.5)
    args = build(profile)
    t_start = time.time()
    subprocess.Popen([str(MIR / "bin" / "winws2.exe")] + args, cwd=str(MIR),
                     creationflags=0x08000000)
    print(f"winws2 запущен на {profile}. Наблюдение {duration}s (проба каждые "
          f"{PROBE_INTERVAL}s, curl timeout {PROBE_TIMEOUT}s):")
    timeline = []
    while time.time() - t_start < duration:
        dt, code = probe_once()
        t_rel = time.time() - t_start
        timeline.append((t_rel, code))
        mark = "✓" if code.isdigit() and int(code) >= 100 else "✗"
        print(f"  {t_rel:6.1f}s {mark} {code:>4} ({dt:.1f}s)")
        time.sleep(max(0.05, PROBE_INTERVAL - (time.time() - t_start)))
    # сводка
    first_ok = next((t for t, c in timeline
                     if c.isdigit() and int(c) >= 100), None)
    n_ok = sum(1 for _, c in timeline if c.isdigit() and int(c) >= 100)
    print(f"\nСводка: проб {len(timeline)}, успешных {n_ok}, "
          f"первый успех через {first_ok if first_ok is not None else '—'}с")


if __name__ == "__main__":
    prof = sys.argv[1] if len(sys.argv) > 1 else "default"
    run(prof)
