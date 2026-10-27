"""probe_h3.py - ядро QUIC/HTTP3-пробы (аудит #9).

Форсированный H3 (disable_http1/2 + preemptive quic_cache_layer, без TCP),
свежая сессия на пробу, внешний wall-clock дедлайн (поток-сторож),
trust_env=False (env/системные прокси не подхватываем - ревью 13.10, P2-1).

Параметры у потребителей разные и передаются явно:
  * тестер - wall_deadline=H3_WALL_DEADLINE (12.0), lib_timeout=(4, 8);
  * dev-инструмент tools/quic_probe.py - 15.0 / (4, 10) + DoH-патч и
    пропуск тестовых пинов. На это ядро НЕ переводится до живого ре-теста на
    i.ytimg.com (аудит §3.2: шаринг только с живым тестом; DoH в тестере
    сознательно отсутствует - REVIEW_MAP §8).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

# Кэш наличия niquests+qh3 (опциональный бандл сборки): False - фолбэк на
# прежнюю эвристику QUIC (тестер отдаёт нейтральный статус).
_HAS_NIQUESTS: Optional[bool] = None


@dataclass
class H3Result:
    ok: bool
    http_version: Optional[int] = None   # 30 == HTTP/3
    status_code: Optional[int] = None
    error: str = ""      # "нет niquests" | "deadline" | имя исключения
    wall_ms: float = 0.0
    detail: str = ""     # человекочитаемая строка (контракт тестера)


def probe_h3(domain: str, wall_deadline: float,
             lib_timeout: tuple[float, float] = (4, 8)) -> H3Result:
    """Проба H3 к домену. detail повторяет исторические строки тестерной
    пробы: "H3 {code}", "QUIC {Exc}", "H3 не подтверждён",
    "H3 висит (дедлайн)", "нет niquests"."""
    global _HAS_NIQUESTS
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
    t0 = time.time()

    def worker() -> None:
        s = None
        try:
            s = niquests.Session(disable_http1=True, disable_http2=True)
            s.trust_env = False
            s.quic_cache_layer.add_domain(domain)
            r = s.get(f"https://{domain}/", timeout=lib_timeout,
                      allow_redirects=False)
            box["ver"] = getattr(r, "http_version", None)
            box["code"] = r.status_code
        except Exception as e:  # noqa: BLE001
            box["err"] = type(e).__name__
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:  # noqa: BLE001
                    pass

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(wall_deadline)
    wall_ms = (time.time() - t0) * 1000
    if th.is_alive():
        return H3Result(ok=False, error="deadline", wall_ms=wall_ms,
                        detail="H3 висит (дедлайн)")
    ver = box.get("ver")
    code = box.get("code")
    if ver == 30:
        return H3Result(ok=True, http_version=ver, status_code=code,
                        wall_ms=wall_ms, detail=f"H3 {code}")
    if "err" in box:
        return H3Result(ok=False, http_version=ver, status_code=code,
                        error=box["err"], wall_ms=wall_ms,
                        detail=f"QUIC {box['err']}")
    return H3Result(ok=False, http_version=ver, status_code=code,
                    wall_ms=wall_ms, detail="H3 не подтверждён")
