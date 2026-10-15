"""api_reports.py - сбор отчёта (zip-пакет для форума) (аудит #1, Inc C).

Соглашение: (ctx, ...) -> dict."""
from __future__ import annotations

import base64
from pathlib import Path

from core.collector import export_data_package
from server.app_state import AppContext, get_root_dir


def export_report(ctx: AppContext, data: dict) -> dict:
    consent = data.get("consent", False)
    city = data.get("city", "")
    isp = data.get("isp", "")
    vpn_active = data.get("vpn_active", False)
    zapret1_strategy = data.get("zapret1_strategy", "")
    zapret1_filename = data.get("zapret1_filename", "")
    zapret1_cmdline = data.get("zapret1_cmdline", "")
    phase0_results = data.get("phase0_results")
    phase1_results = data.get("phase1_results")
    phase2_results = data.get("phase2_results")
    mode = data.get("mode", "lite")
    root = get_root_dir()

    bat_path = None
    if zapret1_filename and zapret1_strategy:
        # Клиент-контролируемое имя: только базовое имя, без разделителей -
        # иначе запись вне корня (path traversal).
        if Path(zapret1_filename).name != zapret1_filename or any(
                c in zapret1_filename for c in "/\\:*?\"<>|") or \
                ".." in zapret1_filename:
            return {"status": "error", "message": "Недопустимое имя файла стратегии"}
        try:
            bat_bytes = base64.b64decode(zapret1_strategy)
            bat_path = root / zapret1_filename
            bat_path.write_bytes(bat_bytes)
            zapret1_strategy = str(bat_path)
        except Exception:
            pass

    ok, path_or_err = export_data_package(
        consent=consent, city=city, isp=isp,
        vpn_active=vpn_active,
        zapret1_strategy=zapret1_strategy,
        root_dir=root, result_dir=root,
        bat_path=bat_path,
        zapret1_cmdline=zapret1_cmdline,
        phase0_results=phase0_results,
        phase1_results=phase1_results,
        phase2_results=phase2_results,
        mode=mode,
    )
    if bat_path and bat_path.exists():
        try:
            bat_path.unlink()
        except OSError:
            pass
    if ok:
        return {"status": "ok", "file": path_or_err}
    return {"status": "error", "message": path_or_err}
