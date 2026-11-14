"""probe_h3.py - ядро QUIC/HTTP3-пробы (аудит #9; отмена/дедлайн - T20).

Форсированный H3 (disable_http1/2 + preemptive quic_cache_layer, без TCP),
свежая сессия на пробу, внешний wall-clock дедлайн (поток-сторож),
trust_env=False (env/системные прокси не подхватываем - ревью 13.10, P2-1).

Параметры у потребителей разные и передаются явно:
  * тестер - wall_deadline=H3_WALL_DEADLINE (6.0), lib_timeout=(2, 4);
  * dev-инструмент tools/quic_probe.py - 15.0 / (4, 10) + DoH-патч и
    пропуск тестовых пинов. На это ядро НЕ переводится до живого ре-теста на
    i.ytimg.com (аудит §3.2: шаринг только с живым тестом; DoH в тестере
    сознательно отсутствует - исторический аудит §8).

Отмена (T20): после wall-clock дедлайна у открытой сессии вызывается close()
из потока-сторожа - это будит/роняет блокирующий запрос и рабочий поток
обязан завершиться в пределах _CANCEL_GRACE. Жёстко убить поток в CPython
нельзя, поэтому если поток всё же жив - он учитывается в счётчике
orphan_threads() (daemon, выход процесса не блокирует, но виден в
диагностике/тестах). Контракт detail не меняется: "H3 {code}",
"QUIC {Exc}", "H3 не подтверждён", "H3 висит (дедлайн)", "нет niquests"
(добавлена только строка для отменённой пробы).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

# Кэш наличия niquests+qh3 (опциональный бандл сборки): False - фолбэк на
# прежнюю эвристику QUIC (тестер отдаёт нейтральный статус).
_HAS_NIQUESTS: Optional[bool] = None

# Сколько ждём рабочий поток после того, как дёрнули close() сессии: закрытие
# сокета обычно роняет блокирующий запрос сразу, запас - на планировщик/GC.
_CANCEL_GRACE = 1.0

# Потоки, пережившие дедлайн+close (не смогли быть отменены): не блокируют
# выход (daemon), но диагностика должна их видеть. Только для тестов/логов.
_ORPHANS: list[str] = []
_ORPHANS_LOCK = threading.Lock()


def orphan_threads() -> list[str]:
    """Домены проб, чей рабочий поток не завершился после дедлайна и close()."""
    with _ORPHANS_LOCK:
        return list(_ORPHANS)


def clear_orphans() -> None:
    """Сброс счётчика сирот (тесты/диагностика; рантайм его не зовёт)."""
    with _ORPHANS_LOCK:
        _ORPHANS.clear()


@dataclass
class H3Result:
    ok: bool
    http_version: Optional[int] = None   # 30 == HTTP/3
    status_code: Optional[int] = None
    error: str = ""      # "нет niquests" | "deadline" | "cancelled" | имя исключения
    wall_ms: float = 0.0
    detail: str = ""     # человекочитаемая строка (контракт тестера)


def _cancel_and_join(box: dict, lock: threading.Lock, th: threading.Thread,
                     domain: str) -> None:
    """Отменить пробу: close() сессии из сторожа, короткое ожидание потока.

    Close() будит блокирующий QUIC/сокет-запрос в подавляющем большинстве
    случаев; если поток всё же жив - фиксируем сироту (bounded, не ждём
    дольше _CANCEL_GRACE)."""
    with lock:
        session = box.get("session")
    if session is not None:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass
    th.join(_CANCEL_GRACE)
    if th.is_alive():
        with _ORPHANS_LOCK:
            _ORPHANS.append(domain)


def probe_h3(domain: str, wall_deadline: float,
             lib_timeout: tuple[float, float] = (4, 8),
             cancel_event: Optional[threading.Event] = None) -> H3Result:
    """Проба H3 к домену. detail повторяет исторические строки тестерной
    пробы: "H3 {code}", "QUIC {Exc}", "H3 не подтверждён",
    "H3 висит (дедлайн)", "нет niquests"; отменённая до старта проба - "H3
    отменён" (caller в этом случае результат не ранжирует)."""
    global _HAS_NIQUESTS
    if cancel_event is not None and cancel_event.is_set():
        return H3Result(ok=False, error="cancelled", detail="H3 отменён")
    if _HAS_NIQUESTS is None:
        try:
            import niquests  # noqa: F401
            _HAS_NIQUESTS = True
        except ImportError:
            _HAS_NIQUESTS = False
    if not _HAS_NIQUESTS:
        return H3Result(ok=False, error="нет niquests", detail="нет niquests")
    import niquests

    box: dict = {}
    lock = threading.Lock()
    t0 = time.time()

    def worker() -> None:
        s = None
        try:
            if cancel_event is not None and cancel_event.is_set():
                box["err"] = "cancelled"
                return
            s = niquests.Session(disable_http1=True, disable_http2=True)
            with lock:
                box["session"] = s
            s.trust_env = False
            s.quic_cache_layer.add_domain(domain)
            if cancel_event is not None and cancel_event.is_set():
                box["err"] = "cancelled"
                return
            r = s.get(f"https://{domain}/", timeout=lib_timeout,
                      allow_redirects=False)
            box["ver"] = getattr(r, "http_version", None)
            box["code"] = r.status_code
        except Exception as e:  # noqa: BLE001
            box["err"] = type(e).__name__
        finally:
            with lock:
                box.pop("session", None)
            if s is not None:
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass

    th = threading.Thread(target=worker, daemon=True,
                          name=f"h3-probe:{domain}")
    th.start()
    th.join(max(0.1, float(wall_deadline)))
    wall_ms = (time.time() - t0) * 1000
    if th.is_alive():
        _cancel_and_join(box, lock, th, domain)
        return H3Result(ok=False, error="deadline", wall_ms=wall_ms,
                        detail="H3 висит (дедлайн)")
    ver = box.get("ver")
    code = box.get("code")
    if box.get("err") == "cancelled":
        return H3Result(ok=False, http_version=ver, status_code=code,
                        error="cancelled", wall_ms=wall_ms,
                        detail="H3 отменён")
    if ver == 30:
        return H3Result(ok=True, http_version=ver, status_code=code,
                        wall_ms=wall_ms, detail=f"H3 {code}")
    if "err" in box:
        return H3Result(ok=False, http_version=ver, status_code=code,
                        error=box["err"], wall_ms=wall_ms,
                        detail=f"QUIC {box['err']}")
    return H3Result(ok=False, http_version=ver, status_code=code,
                    wall_ms=wall_ms, detail="H3 не подтверждён")
