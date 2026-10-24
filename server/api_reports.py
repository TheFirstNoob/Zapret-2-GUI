"""api_reports.py - сбор отчёта (zip-пакет для форума) (аудит #1, Inc C).

Соглашение: (ctx, ...) -> dict."""
from __future__ import annotations

import base64
import secrets
from pathlib import Path

from core.collector import export_data_package
from server.app_state import AppContext, get_root_dir


def export_report(ctx: AppContext, data: dict) -> dict:
    consent = data.get("consent", False)
    city = str(data.get("city") or "")
    isp = str(data.get("isp") or "")
    vpn_active = bool(data.get("vpn_active", False))
    zapret1_strategy = str(data.get("zapret1_strategy") or "")
    zapret1_cmdline = str(data.get("zapret1_cmdline") or "")
    phase0_results = data.get("phase0_results")
    phase1_results = data.get("phase1_results")
    phase2_results = data.get("phase2_results")
    mode = str(data.get("mode") or "lite")
    root = get_root_dir()

    bat_path = None
    if zapret1_strategy:
        # Никогда не пишем по клиентскому имени: только сгенерированный
        # временный .bat. Имя из запроса игнорируется (ревью 24.10: можно
        # было перезаписать/удалить zapret2_config.json или exe в корне).
        try:
            bat_bytes = base64.b64decode(zapret1_strategy, validate=True)
        except (ValueError, TypeError):
            return {"status": "error", "message": "Некорректные данные стратегии"}
        if len(bat_bytes) > 2 * 1024 * 1024:
            return {"status": "error", "message": "Слишком большой файл стратегии"}
        bat_path = root / f"_report_strategy_{secrets.token_hex(8)}.bat"
        try:
            bat_path.write_bytes(bat_bytes)
        except OSError as e:
            return {"status": "error", "message": f"Не удалось записать стратегию: {e}"}
        zapret1_strategy = str(bat_path)

    try:
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
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"Не удалось собрать отчёт: {e}"}
    finally:
        if bat_path and bat_path.exists():
            try:
                bat_path.unlink()
            except OSError:
                pass
    if ok:
        return {"status": "ok", "file": path_or_err}
    return {"status": "error", "message": path_or_err}
