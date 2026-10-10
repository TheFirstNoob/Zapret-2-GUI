"""Живой монитор голосового канала Discord (без ручных кнопок).

Читает свежий `%APPDATA%/discord/logs/discord-webrtc*`, раз в 30 с печатает
таблицу по минутам: отправленные/полученные keepalive-пинги по каждому
эндпоинту + вердикт. Пишет и в stdout, и в `tools/voice_flap_watch.log`.

Запуск: python tools/voice_flap_watch.py [--once]   (--once = один снимок;
вечный цикл через оболочку держит сессию — для фона не использовать).
"""
from __future__ import annotations

import re
import sys
import time
from collections import Counter
from pathlib import Path

LOGS = Path.home() / "AppData/Roaming/discord/logs"
OUT = Path(__file__).resolve().parent / "voice_flap_watch.log"
TS = re.compile(r"^\[(\d{4}-\d{2}-\d{2} (\d\d:\d\d):\d\d)")
PING_S = re.compile(r"Sending ping to ([\d.]+:\d+), seq: \d+")
PING_R = re.compile(r"Ping received from ([\d.]+:\d+), seq: \d+, rtt: (\d+)")


def newest_log() -> Path | None:
    files = sorted(LOGS.glob("discord-webrtc*"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def snapshot(path: Path) -> None:
    sent: Counter = Counter()
    recv: Counter = Counter()
    rtt: dict[str, list[int]] = {}
    cur = "?"
    for l in path.read_text(encoding="utf-8", errors="replace").splitlines():
        t = TS.match(l)
        if t:
            cur = t.group(2)
        m = PING_S.search(l)
        if m:
            sent[(cur, m.group(1))] += 1
            continue
        m = PING_R.search(l)
        if m:
            recv[(cur, m.group(1))] += 1
            rtt.setdefault(m.group(1), []).append(int(m.group(2)))
    mins = sorted({m for (m, _ep) in list(sent) + list(recv)})[-10:]
    eps = sorted({ep for (_m, ep) in list(sent) + list(recv)})
    lines = [f"===== {path.name}  (последние 10 минут) ====="]
    header = "минута  " + "".join(f"{ep:>26s}" for ep in eps)
    lines.append(header)
    for m in mins:
        row = f"{m} "
        for ep in eps:
            s, g = sent.get((m, ep), 0), recv.get((m, ep), 0)
            if not s:
                cell = "-"
            elif g >= s * 0.8:
                cell = f"OK {g}/{s}"
            elif g == 0:
                cell = f"ГЛУХО 0/{s}"
            else:
                cell = f"флап {g}/{s}"
            row += f"{cell:>26s}"
        lines.append(row)
    for ep in eps:
        r = rtt.get(ep, [])
        if r:
            lines.append(f"  {ep}: rtt min/avg/max = "
                         f"{min(r)}/{sum(r)//len(r)}/{max(r)} мс")
    out = "\n".join(lines)
    print("\n" + out, flush=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(f"\n[{time.strftime('%H:%M:%S')}]\n{out}\n")


def main() -> int:
    p = newest_log()
    if not p:
        print("нет discord-webrtc логов")
        return 1
    if "--once" in sys.argv:
        snapshot(p)
        return 0
    print(f"монитор: {p}")
    while True:
        try:
            p2 = newest_log()
            if p2 and p2 != p:
                p = p2
                print(f"лог сменился на {p}")
            snapshot(p)
        except KeyboardInterrupt:
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"ошибка чтения: {e}", file=sys.stderr)
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
