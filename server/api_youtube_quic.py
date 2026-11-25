"""api_youtube_quic.py - тестовый режим «Edge + принудительный QUIC».

Пробник: находит реальные медиа-хосты ролика и открывает его в отдельном
браузере с --origin-to-force-quic-on, чтобы медиа шло по HTTP/3, а не TCP.
Окно остаётся открытым; профиль хранится в logs/yt_quic_profile.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from core import youtube_delivery as yd
from core import youtube_probe
from server.app_state import AppContext, get_root_dir, ui_debug

_LOCK = threading.Lock()
_STATE: dict = {"state": "idle", "phase": "", "error": "", "result": None,
                "started": 0.0, "finished": 0.0}


def _profile(root: Path) -> Path:
    return Path(root) / "logs" / "yt_quic_profile"


def _set(**kw) -> None:
    with _LOCK:
        _STATE.update(kw)


def youtube_quic_start(ctx: AppContext, data: dict) -> dict:
    url = str((data or {}).get("url") or "").strip()
    video_id = yd.parse_video_id(url)
    if not video_id:
        return {"status": "error", "message": "Нужна корректная ссылка YouTube"}
    with _LOCK:
        if _STATE["state"] in ("starting", "running"):
            return {"status": "error", "message": "Уже запускается"}
        _STATE.update({"state": "starting", "phase": "подготовка", "error": "",
                       "result": None, "started": time.time(), "finished": 0.0})
    root = get_root_dir()

    def _worker() -> None:
        try:
            def _p(text: str) -> None:
                _set(phase=text)
            hosts = youtube_probe.discover_media_hosts(video_id, progress=_p)
            if not hosts:
                _set(state="error", phase="ошибка",
                     error="Не удалось определить медиа-хосты (ролик не начал загрузку)",
                     finished=time.time())
                return
            _set(state="running", phase="запуск браузера")
            res = youtube_probe.open_quic_session(
                video_id, _profile(root), hosts=hosts, progress=_p)
            _set(phase="проверка протокола медиа")
            check = youtube_probe.sample_session(int(res.get("port") or 0), seconds=12.0)
            protos = check.get("protocols") or {}
            h3 = int(protos.get("h3", 0))
            total = sum(int(v) for v in protos.values())
            res = {**res, "media_check": check,
                   "h3_share": round(h3 / total, 2) if total else 0.0}
            _set(state="done", phase="браузер открыт", result={**res, "video_id": video_id},
                 finished=time.time())
        except Exception as e:  # noqa: BLE001
            ui_debug(f"youtube_quic: {e}")
            _set(state="error", phase="ошибка", error=f"{type(e).__name__}: {e}",
                 finished=time.time())

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        _set(state="error", error="Не удалось запустить поток")
        return {"status": "error", "message": "Не удалось запустить"}
    return {"status": "ok"}


def youtube_quic_status(ctx: AppContext) -> dict:
    with _LOCK:
        st = dict(_STATE)
    st["elapsed_s"] = round((st.get("finished") or time.time()) - st["started"], 1) if st["started"] else 0
    return {"status": "ok", **st}


def youtube_quic_close(ctx: AppContext) -> dict:
    try:
        youtube_probe.close_quic_session(_profile(get_root_dir()))
    except Exception as e:  # noqa: BLE001
        ui_debug(f"youtube_quic close: {e}")
        return {"status": "error", "message": str(e)[:200]}
    _set(state="idle", phase="", result=None)
    return {"status": "ok", "message": "Окно теста закрыто"}
