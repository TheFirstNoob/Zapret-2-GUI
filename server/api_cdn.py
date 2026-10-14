"""api_cdn.py - домен «CDN-стабилизатор» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; ApiError - busy-ветки
исторически отдают HTTP 409 Conflict."""
from __future__ import annotations

import ipaddress

from core.config import DEFAULT_PROFILE
from core.service_manager import is_installed as svc_installed
from core.service_manager import start as svc_start
from core.tester import Zapret2Tester
from server import api_service
from server.api_common import ApiError
from server.app_state import (AppContext, checkers_busy, get_config_manager,
                              get_controller, get_root_dir)


def _resolve_many(domains: list[str], concurrency: int = 8) -> set[str]:
    """Параллельный резолв набора доменов - protection-множество для
    «какой префикс трогать безопасно» при ipset-правках CDN."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out: set[str] = set()
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = [pool.submit(Zapret2Tester._resolve_ips, d) for d in domains]
            for f in as_completed(futs):
                out.update(f.result())
    except Exception:
        pass
    return out


def _read_lines(fname: str) -> set[str]:
    """Значимые записи списка (единый парсер core.list_health, аудит #8)."""
    from core import list_health
    return set(list_health.read_entries(get_root_dir() / "lists" / fname))


def _read_networks(fnames: list[str]) -> list:
    """Читает сети/адреса списков в ipaddress.ip_network (strict=False)."""
    nets = []
    for fname in fnames:
        for l in sorted(_read_lines(fname)):
            try:
                nets.append(ipaddress.ip_network(l, strict=False))
            except ValueError:
                pass
    return nets


def _plan_cdn_action(domain: str, action: str, ips: list[str],
                     protection: set[str], ipset_mode: bool) -> tuple[bool, str, list[tuple[str, list[str]]]]:
    """Чистое планирование одной CDN-правки без записи на диск.

    Возвращает (ok, err_msg, entries), где entries = [(fname, values)] -
    значения, которые НУЖНО дописать в списки (дедуп по текущему
    содержимому выполнен). Проверки наложений - как в ручном хендлере:
    ipset-include не включает сети из ipset-exclude[-user], general в
    ipset-режиме пишет сырые IP, ipset-include - префиксы _safe_prefixes
    относительно protection.
    """
    values: list[str] = []
    if action in ("ipset-include", "ipset-exclude"):
        fname = "ipset-include-user.txt" if action == "ipset-include" else "ipset-exclude-user.txt"
        if not ips:
            return False, "у кандидата нет резолвнутых IP - добавьте вручную", []
        try:
            ip_list = [str(ipaddress.ip_address(i)) for i in ips]
        except ValueError:
            return False, "Некорректный IP в запросе", []
        prefixes = Zapret2Tester._safe_prefixes(ip_list, protection)
        if not prefixes:
            return False, f"{domain}: все адреса пересекаются с рабочими IP - пропускаем", []
        if action == "ipset-include":
            blocked = [p for p in prefixes
                       if any(ipaddress.ip_network(p, strict=False).overlaps(n)
                              for n in _read_networks(["ipset-exclude.txt", "ipset-exclude-user.txt"]))]
            if blocked:
                return False, f"Наложение: {domain} ({', '.join(blocked)}) уже в ipset-исключениях - пропускаем", []
        existing = _read_lines(fname)
        values = [p for p in prefixes if p not in existing]
        if not values:
            return True, "уже в списке", []
        return True, "", [(fname, values)]
    if action == "exclude":
        fname = "list-exclude.txt"
        from core import list_health
        cov = list_health.coverage(get_root_dir(), [domain]).get(domain, {})
        if cov.get("excludes"):
            return True, f"уже в исключениях ({', '.join(cov['excludes'])})", []
        existing = _read_lines(fname)
        values = [domain] if domain not in existing else []
        if not values:
            return True, "уже в списке", []
        return True, "", [(fname, values)]
    # action == "general"
    if ipset_mode:
        fname = "ipset-include-user.txt"
        if not ips:
            return False, "ipset-режим: у кандидата нет резолвнутых IP - добавьте вручную", []
        try:
            ip_list = [str(ipaddress.ip_address(i)) for i in ips]
        except ValueError:
            return False, "Некорректный IP в запросе", []
        blocked = [ip for ip in ip_list
                   if any(ipaddress.ip_address(ip) in n
                          for n in _read_networks(["ipset-exclude.txt", "ipset-exclude-user.txt"]))]
        if blocked:
            return False, f"Наложение: {domain} ({', '.join(blocked)}) уже в ipset-исключениях - пропускаем", []
        existing = _read_lines(fname)
        values = [ip for ip in ip_list if ip not in existing]
        if not values:
            return True, "уже в списке", []
        return True, "", [(fname, values)]
    fname = "list-general.txt"
    from core import list_health
    cov = list_health.coverage(get_root_dir(), [domain]).get(domain, {})
    if any(n in list_health.DOMAIN_EXCLUDE_BUNDLED for n in cov.get("excludes", [])):
        return False, (f"{domain} уже в стандартных исключениях - исключение "
                       "сильнее, пропускаем"), []
    if cov.get("includes"):
        return True, f"уже в обходе ({', '.join(cov['includes'])})", []
    existing = _read_lines(fname)
    values = [domain] if domain not in existing else []
    if not values:
        return True, "уже в списке", []
    return True, "", [(fname, values)]


def cdn_recommendation(ctx: AppContext, data: dict) -> dict:
    """Полу-автономное применение вердикта CDN-скана без наложений.

    general - домен → list-general.txt (в ipset-режиме IP кандидата →
    ipset-include-user.txt, с проверкой пересечения с ipset-exclude);
    exclude - домен → list-exclude.txt (работает в обоих режимах);
    ipset-include/ipset-exclude - IP → ipset-include-user.txt.
    Применение перезапускает обход - busy-чек не даёт делать это во время
    теста (M1: кнопки строк CDN активны во время прогона)."""
    busy = checkers_busy()
    if busy:
        raise ApiError(409, {"status": "error", "message": busy})
    domain = (data.get("domain") or "").strip().lower().rstrip(".")
    action = data.get("action", "")
    ips = [str(i).strip() for i in (data.get("ips") or []) if str(i).strip()]
    if not domain or action not in ("general", "exclude", "ipset-include", "ipset-exclude"):
        return {"status": "error",
                "message": "Нужны domain и action (general|exclude|ipset-include|ipset-exclude)"}
    cfg = get_config_manager().load()
    ipset_mode = bool(cfg.ipset_catchall)
    working_domains = [str(d).strip().lower().rstrip(".")
                       for d in (data.get("working_domains") or []) if str(d).strip()]
    protection: set[str] = set()
    if working_domains:
        protection = _resolve_many(working_domains)
    ok, msg, entries = _plan_cdn_action(domain, action, ips, protection, ipset_mode)
    if not ok:
        return {"status": "error", "message": msg}
    fname = entries[0][0] if entries else ""
    values = entries[0][1] if entries else []
    if not values:
        return {"status": "ok",
                "message": msg or "Нечего применять - правки уже в списках"}
    from core import list_health
    list_health.append_lines(get_root_dir() / "lists" / fname, values)
    ctrl = get_controller()
    if not ctrl.status().running:
        return {"status": "ok",
                "message": f"{domain}: правки записаны в {fname}. "
                           "Обход не был запущен - применится при "
                           "следующем запуске"}
    profile = cfg.last_profile or DEFAULT_PROFILE
    restart_ok, restart_msg = _restart_after_edit(cfg, data)
    if restart_ok:
        if action in ("ipset-include", "ipset-exclude") or (action == "general" and ipset_mode):
            detail = f"{len(values) or 'все'} сети -> {fname}"
        else:
            detail = f"{domain} -> {fname}"
        return {"status": "ok",
                "message": f"{domain}: {detail}, пресет {profile} перезапущен"}
    return {"status": "error",
            "message": f"{domain}: {fname} обновлён, но перезапуск не удался: {restart_msg}"}


def _restart_after_edit(cfg, data: dict) -> tuple[bool, str]:
    """Перезапуск обхода после правки списков (служба - через SCM)."""
    ctrl = get_controller()
    if svc_installed():
        svc_args, svc_err = api_service.prepare_service_args(
            data if isinstance(data, dict) else {})
        if svc_err:
            return False, f"аргументы службы не собрались: {svc_err}"
        return svc_start(svc_args)
    profile = cfg.last_profile or DEFAULT_PROFILE
    return ctrl.start(
        profile,
        game_filter_mode=cfg.game_filter_mode,
        discord_voice=cfg.discord_voice,
        discord_voice_mode=cfg.discord_voice_mode,
        fake_blob=cfg.fake_blob,
        winws2_debug=cfg.winws2_debug,
        autohostlist=cfg.autohostlist,
        ipset_catchall=cfg.ipset_catchall,
        discord_alt=cfg.discord_alt,
    )


def cdn_apply_all(ctx: AppContext, data: dict) -> dict:
    """«Применить всё по матрице»: батч вердиктов CDN-скана за один перезапуск.

    actions = [{domain, action, ips}, ...]; working_domains - живые в основном
    прогоне (protection для safe_prefixes). Каждая правка планируется как в
    ручном хендлере; наложения/ошибки не валят батч, а пропускаются с причиной.
    Записи дедуплицируются по файлам, затем один перезапуск."""
    busy = checkers_busy()
    if busy:
        raise ApiError(409, {"status": "error", "message": busy})
    actions = data.get("actions") or []
    if not isinstance(actions, list) or not actions:
        return {"status": "error", "message": "Нет правок в запросе"}
    clean = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        domain = (a.get("domain") or "").strip().lower().rstrip(".")
        action = a.get("action", "")
        ips = [str(i).strip() for i in (a.get("ips") or []) if str(i).strip()]
        if domain and action in ("general", "exclude", "ipset-include", "ipset-exclude"):
            clean.append((domain, action, ips))
    if not clean:
        return {"status": "error", "message": "Нет валидных правок в запросе"}
    cfg = get_config_manager().load()
    ipset_mode = bool(cfg.ipset_catchall)
    working_domains = [str(d).strip().lower().rstrip(".")
                       for d in (data.get("working_domains") or []) if str(d).strip()]
    protection: set[str] = set()
    if working_domains:
        protection = _resolve_many(working_domains)
    pending: dict[str, list[str]] = {}
    applied: list[str] = []
    skipped: list[dict] = []
    for domain, action, ips in clean:
        ok, msg, entries = _plan_cdn_action(domain, action, ips, protection, ipset_mode)
        if not ok:
            skipped.append({"domain": domain, "reason": msg})
            continue
        for fname, values in entries:
            pending.setdefault(fname, []).extend(values)
        applied.append(domain)
    written: dict[str, list[str]] = {}
    if pending:
        for fname, values in pending.items():
            existing = _read_lines(fname)
            values = [v for v in values if v not in existing]
            if not values:
                continue
            from core import list_health
            list_health.append_lines(get_root_dir() / "lists" / fname, values)
            written[fname] = values
    # После дедупа могло не остаться реальных записей - перезапуск не нужен.
    if not written:
        return {"status": "ok",
                "message": "Нечего применять - правки уже в списках",
                "applied": [], "skipped": skipped}
    ctrl = get_controller()
    if not ctrl.status().running:
        files_touched = ", ".join(sorted(written))
        return {"status": "ok",
                "message": f"Применено {len(applied)} правок "
                           f"({files_touched}). Обход не был запущен - "
                           "применится при следующем запуске",
                "applied": applied, "skipped": skipped}
    profile = cfg.last_profile or DEFAULT_PROFILE
    restart_ok, restart_msg = _restart_after_edit(cfg, data)
    if not restart_ok and written:
        return {"status": "error",
                "message": f"Применено {len(applied)} правок, но перезапуск не удался: {restart_msg}",
                "applied": applied, "skipped": skipped}
    files_touched = ", ".join(sorted(written)) if written else "-"
    return {"status": "ok",
            "message": f"Применено {len(applied)} правок ({files_touched}), пресет {profile} перезапущен",
            "applied": applied, "skipped": skipped}
