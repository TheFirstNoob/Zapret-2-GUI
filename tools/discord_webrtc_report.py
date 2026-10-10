"""Сводка по discord-webrtc логу: таймауты по минутам + топ-цепочек (dev-only).

Читает %APPDATA%\\discord\\logs\\discord-webrtc и пишет в
logs/voice_flap_report.txt:
  - сводку: число Ping timeout / Sending ping, окно времени, доля потерь;
  - гистограмму таймаутов по минутам;
  - топ цепочек подряд идущих таймаутов по эндпоинтам (это и есть «флапы»);
  - последние события disconnect/NACK, если есть.

Запуск: python tools/discord_webrtc_report.py
Контекст и методика: AI_DOCS/VOICE_FLAP_FINLAND_2026-10.md.
"""
import os
import re
from collections import Counter
from pathlib import Path

LOG = Path(os.environ.get("APPDATA", "")) / "discord" / "logs" / "discord-webrtc"
OUT = Path(__file__).resolve().parents[1] / "logs" / "voice_flap_report.txt"
TS = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]")
EPT = re.compile(r"Ping timeout from: ([\d.]+):(\d+), seq: (\d+)")


def _read_text(p: Path) -> str:
    raw = p.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig", errors="replace")
    return raw.decode("utf-8", errors="replace")


def main() -> None:
    text = _read_text(LOG)
    events = []          # (ts, ep, seq)
    sends = 0
    per_min = Counter()
    disconnects = []
    for line in text.splitlines():
        m = EPT.search(line)
        if not m:
            if "Sending ping to" in line:
                sends += 1
            elif "Disconnected from RTC" in line or "VOICE_DISCONNECT" in line:
                tsm = TS.search(line)
                if tsm:
                    disconnects.append(tsm.group(1) + "  " + line[m.end():].strip()[:110])
            continue
        tsm = TS.search(line)
        if not tsm:
            continue
        t = tsm.group(1)
        ep = f"{m.group(1)}:{m.group(2)}"
        events.append((t, ep, int(m.group(3))))
        per_min[t[:16]] += 1

    # цепочки подряд идущих seq по эндпоинту
    state: dict[str, list] = {}
    chains = []
    for t, ep, seq in events:
        st = state.get(ep)
        if st and seq == st[2] + 1:
            st[1] = t
            st[2] = seq
            st[3] += 1
        else:
            if st and st[3] >= 3:
                chains.append((st[0], st[1], ep, st[3]))
            state[ep] = [t, t, seq, 1]
    for ep, st in state.items():
        if st[3] >= 3:
            chains.append((st[0], st[1], ep, st[3]))
    chains.sort(key=lambda c: -c[3])

    lines = []
    lines.append(f"лог: {LOG}")
    lines.append(f"Ping timeout: {len(events)}; Sending ping: {sends}; "
                 f"chain>=3: {len(chains)}")
    if events:
        lines.append(f"окно: {events[0][0]} .. {events[-1][0]}")
    lines.append("")
    lines.append("--- таймауты по минутам ---")
    for k in sorted(per_min):
        lines.append(f"  {k}  {per_min[k]:4d}  {'#' * min(per_min[k], 60)}")
    lines.append("")
    lines.append("--- топ-15 цепочек (это и есть флапы) ---")
    for start, end, ep, n in chains[:15]:
        lines.append(f"  {start} .. {end}  {ep}  цепочка={n}")
    lines.append("")
    lines.append("--- disconnect/NACK события ---")
    lines.extend("  " + d for d in disconnects[-20:])
    if not disconnects:
        lines.append("  (нет)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
