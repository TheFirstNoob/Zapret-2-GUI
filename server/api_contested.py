"""api_contested.py - домен «спорные домены» (аудит #1, Inc C).

Соглашение: (ctx: AppContext, ...) -> dict; исключения - только ApiError."""
from __future__ import annotations

from core import list_health
from server.app_state import AppContext, get_controller, get_root_dir

# Спорные домены (нужен десинк одним, ломается у других - §15)
CONTESTED = [
    {"id": "aws", "domain": "amazonaws.com", "probe": "s3.amazonaws.com",
     "title": "AWS (S3 / DynamoDB)",
     "why": "Часть провайдеров режет AWS по SNI - нужен десинк. У других "
            "AWS жив в голую, а наш десинк ломает DynamoDB/S3. Проверь "
            "пробой и включай только если без десинка не живёт."},
]


def include_user_domains() -> set:
    """Домены пользовательского include-списка (единый парсер, аудит #10)."""
    return set(list_health.read_entries(
        get_root_dir() / "lists" / "list-include-user.txt"))


def contested_status(ctx: AppContext) -> dict:
    items = []
    enabled = include_user_domains()
    for item in CONTESTED:
        items.append({**item, "enabled": item["domain"] in enabled})
    return {"status": "ok", "items": items,
            "protection_running": get_controller().status().running}


def contested_toggle(ctx: AppContext, data: dict) -> dict:
    item_id = str(data.get("id") or "")
    item = next((i for i in CONTESTED if i["id"] == item_id), None)
    if not item:
        return {"status": "error", "message": "Неизвестный домен"}
    # Единый слой list_health: дедуп, переносы из исключений, конфликты
    enable = bool(data.get("enabled"))
    if enable:
        r = list_health.add_domain(get_root_dir(), item["domain"], "include")
        if r.get("result") in ("invalid", "blocked"):
            return {"status": "error", "message": r.get("message", "ошибка")}
        prefix = {"already": "Уже в обходе",
                  "moved": "Перенесён из Исключений"}.get(
                      r.get("result"), "Добавлено в Включения")
    else:
        removed = list_health.remove_domain(get_root_dir(),
                                            item["domain"], "include")
        prefix = ("Убрано из Включений" if removed
                  else "Домен и так не был включён")
    return {"status": "ok",
            "message": prefix + " - применится к новым подключениям "
                                "(перезапуск не нужен)"}


def contested_check(ctx: AppContext, data: dict) -> dict:
    import time as _time
    item_id = str(data.get("id") or "")
    item = next((i for i in CONTESTED if i["id"] == item_id), None)
    if not item:
        return {"status": "error", "message": "Неизвестный домен"}
    engine_running = get_controller().status().running
    # «В обходе» - это про КОНКРЕТНЫЙ домен: движок запущен И домен добавлен
    # в обход (тумблер). Раньше учитывался только статус движка - при
    # выключенном тумблере вердикт врал («оставьте включённым»).
    enabled = item["domain"].lower() in include_user_domains()
    with_protection = engine_running and enabled
    t0 = _time.time()
    from core.probe_http import curl_code
    n = curl_code(f"https://{item['probe']}/", timeout=10, wall_pad=5)
    # TimeoutExpired здесь больше не роняет запрос - "000" (как в соседних
    # пробах; владелец "000" = провал, см. app.js).
    code = str(n) if n else "000"
    return {"status": "ok", "code": code,
            "elapsed": round(_time.time() - t0, 2),
            "with_protection": with_protection,
            "engine_running": engine_running,
            "enabled": enabled}
