"""Метрики и вердикты проверки доставки YouTube (без браузера и сети).

Модуль чистый: принимает сэмплы и агрегаты наблдателя, возвращает метрики и
вердикт. Здесь НЕТ вывода о причинах блокировки: только наблюдаемое
воспроизведение и достаточность данных.

Термины:
  * sample  — отсчёт состояния <video> раз в секунду;
  * ahead   — buffer-ahead = конец буфера, содержащего currentTime, минус t;
  * stall   — >=1.5 c без продвижения медиа-времени при намерении играть.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Допустимые длительности наблюдения (сек). Короткий клип не даёт сравнения.
MIN_WINDOW_S = 20.0
CONFIDENT_WINDOW_S = 30.0
DEFAULT_WINDOW_S = 30.0
MAX_WINDOW_S = 60.0

STALL_MIN_S = 1.5

# Минимальный порог «устойчиво играет».
STABLE_ADVANCE = 0.95
STABLE_STALL_S = 1.0

# Порог «доставка голодает».
STARVATION_STALL_S = 5.0
STARVATION_ADVANCE = 0.8
STARVATION_AHEAD_S = 1.0
STARVATION_GAP_S = 5.0

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(url: str) -> Optional[str]:
    """Достать 11-символьный id из watch/shorts/youtu.be URL."""
    if not url:
        return None
    u = url.strip()
    if _YT_ID.match(u):
        return u
    try:
        from urllib.parse import parse_qs, urlparse
    except ImportError:  # pragma: no cover
        return None
    try:
        p = urlparse(u)
    except ValueError:
        return None
    if p.scheme not in ("http", "https"):
        return None
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
        return vid if _YT_ID.match(vid) else None
    if host not in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        return None
    if p.path == "/watch":
        vid = (parse_qs(p.query).get("v") or [""])[0]
        return vid if _YT_ID.match(vid) else None
    m = re.match(r"^/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})", p.path)
    return m.group(1) if m else None


def canonical_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass
class RunSpec:
    label: str
    video_id: str
    condition: str = "direct"
    window_s: float = DEFAULT_WINDOW_S
    quality: str = "480"
    start_at: float = 0.0


@dataclass
class RunMetrics:
    window_s: float = 0.0
    samples: int = 0
    playback_started: bool = False
    startup_ms: Optional[float] = None
    advancement: float = 0.0
    stalls: int = 0
    stall_total_s: float = 0.0
    longest_stall_s: float = 0.0
    buffer_ahead_min_s: Optional[float] = None
    resolution_max: str = "-"
    resolutions: list[str] = field(default_factory=list)
    media_bytes: int = 0
    traffic_mb: float = 0.0
    delivery_gaps_s: list[float] = field(default_factory=list)
    request_errors: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "window_s": round(self.window_s, 1),
            "samples": self.samples,
            "playback_started": self.playback_started,
            "startup_ms": (round(self.startup_ms, 1)
                           if self.startup_ms is not None else None),
            "advancement": round(self.advancement, 3),
            "stalls": self.stalls,
            "stall_total_s": round(self.stall_total_s, 1),
            "longest_stall_s": round(self.longest_stall_s, 1),
            "buffer_ahead_min_s": (round(self.buffer_ahead_min_s, 2)
                                   if self.buffer_ahead_min_s is not None else None),
            "resolution_max": self.resolution_max,
            "resolutions": self.resolutions,
            "media_bytes": self.media_bytes,
            "traffic_mb": round(self.traffic_mb, 2),
            "delivery_gaps_s": [round(g, 1) for g in self.delivery_gaps_s],
            "request_errors": self.request_errors,
            "notes": self.notes,
        }


def _res_label(sample: dict) -> str:
    h = sample.get("h") or 0
    if isinstance(h, (int, float)) and h > 0:
        return f"{int(h)}p"
    return "-"


def compute_metrics(samples: list[dict], *, window_s: float,
                    byte_events: Optional[list[dict]] = None,
                    request_errors: Optional[dict[str, int]] = None,
                    startup_ms: Optional[float] = None) -> RunMetrics:
    """Свести сэмплы наблюдателя в метрики.

    samples: [{t, ahead, ready, w, h, paused, ended, dropped, total}, ...]
    byte_events: [{ts, delta}] — приращения медиа-байт (для разрывов доставки).
    """
    m = RunMetrics(window_s=float(window_s), request_errors=dict(request_errors or {}))
    pts = [s for s in samples if isinstance(s.get("t"), (int, float))]
    m.samples = len(pts)
    if not pts:
        m.notes.append("нет отсчётов состояния плеера")
        return m

    m.playback_started = any((s.get("t") or 0) > 0 for s in pts)
    if m.playback_started:
        m.startup_ms = startup_ms

    # Медиа-время против реального времени наблюдения: стены 1 Гц-выборки
    # недостаточно, поэтому длительности фризов меряем по wall-clock (ts),
    # а продвижение — по медиа-времени.
    times = [float(s["t"]) for s in pts]
    wall = [float(s["ts"]) if isinstance(s.get("ts"), (int, float))
            else float(i) for i, s in enumerate(pts)]
    wall_span = wall[-1] - wall[0]
    if wall_span > 0:
        m.advancement = max(0.0, min(1.0, (times[-1] - times[0]) / wall_span))

    # Фризы: участки, где медиа-время стоит при намерении играть, длиной
    # >= STALL_MIN_S по wall-clock.
    stall_runs: list[float] = []
    run_wall: Optional[float] = None
    for i in range(1, len(pts)):
        prev, cur = pts[i - 1], pts[i]
        intended = not prev.get("paused") and not prev.get("ended")
        frozen = (float(cur["t"]) - float(prev["t"])) <= 0.05 and intended
        if frozen:
            if run_wall is None:
                run_wall = wall[i - 1]
        else:
            if run_wall is not None:
                dur = wall[i] - run_wall
                if dur >= STALL_MIN_S:
                    stall_runs.append(dur)
                run_wall = None
    if run_wall is not None:
        dur = wall[-1] - run_wall
        if dur >= STALL_MIN_S:
            stall_runs.append(dur)
    m.stalls = len(stall_runs)
    m.stall_total_s = sum(stall_runs)
    m.longest_stall_s = max(stall_runs) if stall_runs else 0.0

    ahead_vals = [s.get("ahead") for s in pts if isinstance(s.get("ahead"), (int, float))]
    m.buffer_ahead_min_s = min(ahead_vals) if ahead_vals else None

    res = [_res_label(s) for s in pts if _res_label(s) != "-"]
    if res:
        m.resolutions = res
        m.resolution_max = max(res, key=lambda r: int(r[:-1]))

    if byte_events:
        m.media_bytes = int(sum(e.get("delta") or 0 for e in byte_events))
        m.traffic_mb = m.media_bytes / 1e6
        gap = 0.0
        for e in byte_events:
            delta = int(e.get("delta") or 0)
            if delta > 0:
                if gap >= STARVATION_GAP_S:
                    m.delivery_gaps_s.append(gap)
                gap = 0.0
            else:
                gap += float(e.get("dt") or 0)
        if gap >= STARVATION_GAP_S:
            m.delivery_gaps_s.append(gap)

    if m.window_s < MIN_WINDOW_S:
        m.notes.append("окно короче минимального")
    return m


def verdict(m: RunMetrics, *, ads_or_consent: bool = False,
            player_error: str = "", content_unavailable: str = "",
            interrupted: str = "") -> dict:
    """Вердикт по наблюдаемым данным. Причина (DPI/маршрут/бэкенд) не выводится."""
    if interrupted:
        return {"code": "inconclusive", "label": "Замер прерван",
                "text": interrupted, "confidence": "low"}
    if content_unavailable:
        return {"code": "content_unavailable", "label": "Ролик недоступен",
                "text": content_unavailable, "confidence": "high"}
    if player_error:
        return {"code": "player_error", "label": "Ошибка плеера",
                "text": player_error, "confidence": "high"}
    if ads_or_consent or not m.playback_started:
        if m.window_s < 40:
            return {"code": "inconclusive", "label": "Данных недостаточно",
                    "text": "Воспроизведение не началось за отведённое окно.",
                    "confidence": "low"}
        return {"code": "startup_failure", "label": "Старт не состоялся",
                "text": "Кадр не появился за 40 с; транспортных данных нет.",
                "confidence": "medium"}
    if m.window_s < MIN_WINDOW_S:
        return {"code": "inconclusive", "label": "Данных недостаточно",
                "text": "Слишком короткое окно наблюдения.", "confidence": "low"}

    starvation = (m.stall_total_s >= STARVATION_STALL_S
                  or m.advancement < STARVATION_ADVANCE
                  or (m.buffer_ahead_min_s is not None
                      and m.buffer_ahead_min_s < STARVATION_AHEAD_S))
    if starvation and (m.delivery_gaps_s or m.stall_total_s >= STARVATION_STALL_S):
        return {"code": "starvation", "label": "Доставка голодает",
                "text": "Воспроизведение останавливается: паузы, буфер у нуля.",
                "confidence": ("high" if m.window_s >= CONFIDENT_WINDOW_S
                               else "medium")}
    if (m.advancement >= STABLE_ADVANCE and m.stall_total_s <= STABLE_STALL_S):
        return {"code": "stable", "label": "Воспроизведение стабильно",
                "text": f"Кадр на {m.resolution_max}, пауз почти нет.",
                "confidence": ("high" if m.window_s >= CONFIDENT_WINDOW_S
                               else "medium")}
    return {"code": "warning", "label": "Пограничный результат",
            "text": "Есть паузы, но порог голодания не достигнут. Повторите тест.",
            "confidence": "low"}


def compare(left: dict, right: dict) -> dict:
    """Сравнить два вердикта: подтверждена ли разница."""
    lc = (left or {}).get("verdict", {}).get("code", "")
    rc = (right or {}).get("verdict", {}).get("code", "")
    if "inconclusive" in (lc, rc) or not lc or not rc:
        return {"code": "incomplete", "label": "Сравнение неполное",
                "text": "Не по обоим роликам достаточно данных."}
    if lc == "stable" and rc == "starvation":
        return {"code": "difference", "label": "Разница подтверждена",
                "text": "Один ролик играет, второй голодает. Причина не определена."}
    if lc == "starvation" and rc == "stable":
        return {"code": "difference", "label": "Разница подтверждена",
                "text": "Один ролик голодает, второй играет. Причина не определена."}
    if lc == "stable" and rc == "stable":
        return {"code": "both_stable", "label": "Оба играют",
                "text": "Сейчас оба ролика играют; сравнение разницы не показывает."}
    if lc == "starvation" and rc == "starvation":
        return {"code": "both_impaired", "label": "Оба голодают",
                "text": "Оба ролика с паузами — похоже на общую деградацию доставки."}
    return {"code": "incomplete", "label": "Сравнение неполное",
            "text": "Результаты не образуют пары stable/starvation."}
