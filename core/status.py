"""status.py - единый реестр строковых статусов на проводе (аудит #10).

Значения - публичный контракт Python<->JS: НЕ менять без обновления
tools/status_contract.py (замороженное множество + JS-дрейф-чек). StrEnum
специально: ведёт себя как обычная строка (json.dumps, `== "OK"`,
форматирование), но даёт автодополнение и типы.
"""
from __future__ import annotations

from enum import StrEnum


class HostStatus(StrEnum):
    """Статус проверки хоста (TestResult.status; уходит в JSON фронта)."""
    OK = "OK"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"
    FAIL = "FAIL"
    ERROR = "ERROR"
    QUIC = "QUIC"
    H3_NONE = "H3_NONE"
    DETECTED = "DETECTED"
    SYN_DROP = "SYN DROP"
    TCP_RST = "TCP RST"
    TLS_RST = "TLS RST"
    TCP16_20 = "TCP16_20"
    # Композитные статусы вердикта (собирает server.py в key_hosts)
    QUIC_OK = "QUIC_OK"
    QUIC_UNKNOWN = "QUIC_UNKNOWN"
    NA = "N/A"


# Провал теста (счётчики ok/fail): раньше этот tuple был скопирован в ДВУХ
# местах тестера (_build_result и _test_baseline) - риск разъезда.
FAIL_STATUSES = frozenset({HostStatus.BLOCKED, HostStatus.TIMEOUT,
                           HostStatus.FAIL, HostStatus.ERROR})
