"""api_youtube_delivery.py - проверка доставки YouTube (два ролика).

Асинхронная job-модель по образцу api_diag: занять operation-slot, запустить
воркер-поток, отдавать статус по job_id. Это диагностика воспроизведения, а не
обход: ничего не меняет в системе, пресетах и службе.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Optional

from core import youtube_delivery as yd
from core import youtube_probe
from server.app_state import (STATE, AppContext, begin_operation,
                              checkers_busy, end_operation)

_LOCK = threading.Lock()
_JOB: Optional[dict] = None
_CANCEL = threading.Event()

MAX_WINDOW_S = yd.MAX_WINDOW_S
MIN_WINDOW_S = yd.MIN_WINDOW_S


def _reset() -> None:
    global _JOB
    with _LOCK:
        _JOB = None
    _CANCEL.clear()


def _set(**fields) -> None:
    with _LOCK:
        if _JOB is not None:
            _JOB.update(fields)


def youtube_delivery_start(ctx: AppContext, data: dict) -> dict:
    global _JOB
    data = data or {}
    ref_url = str(data.get("reference_url") or "").strip()
    prob_url = str(data.get("problem_url") or "").strip()
    ref_id = yd.parse_video_id(ref_url)
    prob_id = yd.parse_video_id(prob_url)
    if not ref_id or not prob_id:
        return {"status": "error",
                "message": "Нужны две корректные ссылки YouTube (рабочая и проблемная)"}
    if ref_id == prob_id:
        return {"status": "error", "message": "Укажите два разных ролика"}
    try:
        window_s = float(data.get("window_s") or yd.DEFAULT_WINDOW_S)
    except (TypeError, ValueError):
        window_s = yd.DEFAULT_WINDOW_S
    window_s = max(MIN_WINDOW_S, min(MAX_WINDOW_S, window_s))
    quality = str(data.get("quality") or "480")
    max_mb = data.get("max_mb")
    try:
        max_bytes = int(float(max_mb) * 1e6) if max_mb else 12_000_000
    except (TypeError, ValueError):
        max_bytes = 12_000_000

    busy = checkers_busy()
    if busy:
        return {"status": "error", "message": busy}
    with _LOCK:
        if _JOB is not None and _JOB.get("state") in ("starting", "running"):
            return {"status": "error", "message": "Проверка уже выполняется"}
    busy = begin_operation("youtube-delivery")
    if busy:
        return {"status": "error", "message": busy}

    job_id = uuid.uuid4().hex[:12]
    _CANCEL.clear()
    with _LOCK:
        _JOB = {
            "job_id": job_id,
            "state": "starting",
            "phase": "подготовка",
            "progress": 0.0,
            "started": time.time(),
            "finished": 0.0,
            "error": "",
            "cancel_requested": False,
            "reference": None,
            "problem": None,
            "comparison": None,
        }

    def _progress(text: str) -> None:
        _set(phase=text)

    def _worker() -> None:
        try:
            _set(state="running", phase="запуск браузера")
            results = {}
            for key, label, vid in (
                    ("reference", "Рабочий ролик", ref_id),
                    ("problem", "Проблемный ролик", prob_id)):
                if _CANCEL.is_set():
                    _set(state="cancelled", phase="отменено пользователем")
                    return
                _set(phase=f"{label}: {vid}")
                run = youtube_probe.probe_video(
                    vid, label=label, window_s=window_s, quality=quality,
                    max_bytes=max_bytes, progress=_progress)
                results[key] = run.as_dict()
                _set(**{key: results[key]})
                _set(progress=0.5 if key == "reference" else 1.0)
            comparison = yd.compare(results.get("reference"), results.get("problem"))
            _set(state="done", phase="готово", comparison=comparison,
                 finished=time.time())
        except Exception as e:  # noqa: BLE001
            _set(state="error", phase="ошибка", error=f"{type(e).__name__}: {e}",
                 finished=time.time())
        finally:
            end_operation("youtube-delivery")

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        _reset()
        end_operation("youtube-delivery")
        return {"status": "error", "message": "Не удалось запустить проверку"}
    return {"status": "ok", "job_id": job_id}


def _snapshot() -> dict:
    with _LOCK:
        if _JOB is None:
            return {"state": "idle"}
        return dict(_JOB)


def youtube_delivery_status(ctx: AppContext) -> dict:
    job = _snapshot()
    if job.get("state") == "idle":
        return {"status": "ok", "state": "idle"}
    elapsed = round((job.get("finished") or time.time()) - job["started"], 1)
    return {"status": "ok", **job, "elapsed_s": elapsed}


def youtube_delivery_cancel(ctx: AppContext, data: dict) -> dict:
    job = _snapshot()
    job_id = str((data or {}).get("job_id") or "")
    if job.get("state") == "idle":
        return {"status": "ok", "message": "Нечего отменять"}
    if job_id and job_id != job.get("job_id"):
        return {"status": "error", "message": "Задача не найдена"}
    _CANCEL.set()
    _set(cancel_requested=True, phase="отмена...")
    return {"status": "ok", "message": "Отмена запрошена"}


def youtube_delivery_report(ctx: AppContext) -> dict:
    job = _snapshot()
    if job.get("state") == "idle":
        return {"status": "error", "message": "Нет результатов"}
    # Без signed URL и служебных полей — только агрегаты.
    return {"status": "ok", "state": job.get("state"),
            "comparison": job.get("comparison"),
            "reference": job.get("reference"),
            "problem": job.get("problem")}
