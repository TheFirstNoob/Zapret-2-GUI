"""Живой монитор голосового канала Discord (без ручных кнопок).

Читает все `%APPDATA%/discord/logs/discord-webrtc*` (сливает, дедуп по
(минута, эндпоинт, seq)), печатает таблицу по минутам: отправленные/
полученные keepalive-пинги по каждому эндпоинту + вердикт.
Пишет и в stdout, и в `tools/voice_flap_watch.log`.

Запуск:
  python tools/voice_flap_watch.py --once   # один снимок (для планировщика)
  python tools/voice_flap_watch.py          # цикл каждые 30с (НЕ для фона в
                                            # оболочке: вечный процесс держит
                                            # сессию)
Методика: во время замеров не запускать pktmon-захваты (pktmon в пути и под
нагрузкой может сам добавлять дропы), либо короткими узкими окнами.
"""
from __future__ import annotations

import re
import sys
import time
from collections import Counter
from pathlib import Path

LOGS = Path.home() / "AppData/Roaming/discord/logs"
OUT = Path(__file__).resolve().parent / "voice_flap_watch.log"
TS = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d\d:\d\d):\d\d")
PING_S = re.compile(r"Sending ping to ([\d.]+:\d+), seq: (\d+)")
PING_R = re.compile(r"Ping received from ([\d.]+:\d+), seq: (\d+), rtt: (\d+)")


def logs() -> list[Path]:
    return sorted(LOGS.glob("discord-webrtc*"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def snapshot(paths: list[Path]) -> None:
    sent: Counter = Counter()
    recv: Counter = Counter()
    rtt: dict[str, list[int]] = {}
    seen_s: set = set()
    seen_r: set = set()
    for path in paths:
        cur = "?"
        for l in path.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            t = TS.match(l)
            if t:
                cur = t.group(1)
            m = PING_S.search(l)
            if m:
                key = (cur, m.group(1), int(m.group(2)))
                if key not in seen_s:
                    seen_s.add(key)
                    sent[(cur, m.group(1))] += 1
                continue
            m = PING_R.search(l)
            if m:
                key = (cur, m.group(1), int(m.group(2)))
                if key not in seen_r:
                    seen_r.add(key)
                    recv[(cur, m.group(1))] += 1
                    rtt.setdefault(m.group(1), []).append(int(m.group(3)))
    mins = sorted({m for (m, _ep) in list(sent) + list(recv)})[-12:]
    eps = sorted({ep for (_m, ep) in list(sent) + list(recv)})
    lines = ["===== discord-webrtc* (последние минуты) ====="]
    lines.append("минута  " + "".join(f"{ep:>24s}" for ep in eps))
    for m in mins:
        row = f"{m[5:]:>11s} "
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
            row += f"{cell:>24s}"
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
    if "--once" in sys.argv:
        files = logs()
        if not files:
            print("нет discord-webrtc логов")
            return 1
        snapshot(files)
        return 0
    print("монитор (Ctrl+C для выхода)")
    while True:
        try:
            snapshot(logs())
        except KeyboardInterrupt:
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"ошибка чтения: {e}", file=sys.stderr)
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
