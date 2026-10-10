"""Живой монитор голосовых флапов Discord (dev-only).

Читает %APPDATA%\\discord\\logs\\discord-webrtc (подробный лог включается
кнопкой «Загрузить журнал» в панели голоса Discord) и пишет события в
logs/voice_flap_monitor.txt:
  FLAP        — цепочки Ping timeout (>=3), с временем начала/конца;
  DISCONNECT  — обрывы RTC-соединений;
  !!          — рост счётчика Failed audio (шифрование);
  hb          — сводка раз в 30 с (таймауты за 30 с, эндпоинты, NACK).

Запуск: python tools/voice_flap_monitor.py   (Ctrl+C — остановить).
Контекст и методика: AI_DOCS/VOICE_FLAP_FINLAND_2026-10.md.
"""
import os
import re
import time
from pathlib import Path

LOG = Path(os.environ.get("APPDATA", "")) / "discord" / "logs" / "discord-webrtc"
OUT = Path(__file__).resolve().parents[1] / "logs" / "voice_flap_monitor.txt"
TS = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]")
EPT = re.compile(r"Ping timeout from: ([\d.]+):(\d+), seq: (\d+)")

# хвост назад при старте (чтобы поймать уже активную цепочку)
LOOKBACK_LINES = 3000


def _read_text() -> str:
    raw = LOG.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig", errors="replace")
    return raw.decode("utf-8", errors="replace")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as _:
        pass

    def log(s: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {s}"
        print(line, flush=True)
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    log(f"=== monitor start (log: {LOG}) ===")
    seen = 0
    last_hb = time.time()
    chain: dict[str, list] = {}   # ep -> [count, first_ts, last_ts, last_seq]
    win: list[tuple[float, str]] = []
    nack = 0
    last_fail = 0

    while True:
        try:
            lines = _read_text().splitlines()
            if seen == 0:
                seen = max(0, len(lines) - LOOKBACK_LINES)
            for line in lines[min(seen, len(lines)):]:
                tsm = TS.search(line)
                t = tsm.group(1)[11:] if tsm else "?"
                m = EPT.search(line)
                if m:
                    ep = f"{m.group(1)}:{m.group(2)}"
                    seq = int(m.group(3))
                    win.append((time.time(), ep))
                    c = chain.setdefault(ep, [0, t, t, 0])
                    if c[0] == 0:
                        c[1] = t
                    c[0] += 1
                    c[2] = t
                    c[3] = seq
                elif "NACK" in line:
                    nack += 1
                elif "Disconnected from RTC" in line or "VOICE_DISCONNECT" in line:
                    log(f"!! {t} DISCONNECT: {line.split('] ', 1)[-1][:120]}")
                elif "Failed audio:" in line:
                    mm = re.search(r"Failed audio: (\d+)", line)
                    if mm:
                        fv = int(mm.group(1))
                        if fv > last_fail:
                            log(f"!! {t} audio encrypt failed +{fv - last_fail}")
                        last_fail = fv
            seen = len(lines)
            win = [w for w in win if time.time() - w[0] < 60]
            # закрываем цепочки, где тишина больше 12 с
            for ep, c in list(chain.items()):
                last_ts = None
                for w in reversed(win):
                    if w[1] == ep:
                        last_ts = w[0]
                        break
                if c[0] >= 3 and (last_ts is None or time.time() - last_ts > 12):
                    log(f"FLAP {c[1]}..{c[2]} {ep} цепочка={c[0]} (посл.seq={c[3]})")
                    c[0] = 0
            if time.time() - last_hb > 30:
                last_hb = time.time()
                recent = [w for w in win if time.time() - w[0] < 30]
                log(f"hb timeouts(30c)={len(recent)} "
                    f"els={sorted({w[1] for w in recent})} nack_total={nack}")
        except Exception as e:  # noqa: BLE001
            log(f"monitor error: {e!r}")
        time.sleep(5)


if __name__ == "__main__":
    main()
