r"""Контракт статусов на проводе (аудит #10).

  python tools/status_contract.py    # проверка; exit 1 при дрейфе

1) значения core.status.HostStatus == замороженному wire-множеству;
2) FAIL_STATUSES согласован с enum;
3) JS-дрейф: статус-литералы в frontend/js/app.js, которых Python НЕ выдаёт
   (мёртвые ветки, ловим класс OK_BLOCKED/DPI_DROP).
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.status import FAIL_STATUSES, HostStatus  # noqa: E402

# Замороженное множество строк на HTTP-проводе (менять ТОЛЬКО вместе с
# обновлением этого файла и синхронной правкой фронта).
WIRE = {
    "OK", "BLOCKED", "TIMEOUT", "FAIL", "ERROR", "QUIC",
    "H3_NONE", "DETECTED", "SYN DROP", "TCP RST", "TLS RST", "TCP16_20",
    "QUIC_OK", "QUIC_UNKNOWN", "N/A",
}


def main() -> int:
    fails = 0
    values = {s.value for s in HostStatus}
    if values != WIRE:
        fails += 1
        print("FAIL: значения enum != замороженному контракту")
        print("  лишние:", sorted(values - WIRE))
        print("  пропавшие:", sorted(WIRE - values))
    if not FAIL_STATUSES <= frozenset(HostStatus):
        fails += 1
        print("FAIL: FAIL_STATUSES содержит не-enum значения:",
              sorted(set(FAIL_STATUSES) - frozenset(HostStatus)))

    js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    js_used = set(re.findall(
        r"'(OK|OK_BLOCKED|BLOCKED|TIMEOUT|FAIL|ERROR|QUIC[_A-Z]*|H3_NONE"
        r"|TCP16_20|DPI_DROP|DETECTED|SYN DROP|TCP RST|TLS RST|N/A)'", js))
    dead = sorted(js_used - values)
    if dead:
        fails += 1
        print("FAIL: JS использует статусы, которых Python не выдаёт "
              f"(мёртвые ветки): {dead}")
    missing = sorted(values - js_used)
    if missing:
        print(f"info: enum-статусы, не упомянутые в app.js: {missing}")

    print("ИТОГ:", "OK" if fails == 0 else f"FAIL ({fails})")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
