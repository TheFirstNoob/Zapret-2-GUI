"""api_common.py - базовые типы API-слоя (аудит #1, Inc C).

Соглашение новых хендлеров (api_*.py): свободная функция принимает
(ctx: AppContext, ...) и ВОЗВРАЩАЕТ dict (JSON-ответ, HTTP 200) либо
кидает ApiError для нестандартного статуса. Роутер (server.py, _dispatch)
сам отправляет результат - хендлеры больше не знают про HTTP-транспорт.
"""
from __future__ import annotations


class ApiError(Exception):
    """HTTP-ошибка API: статус + JSON-payload (как раньше _send_json)."""

    def __init__(self, status: int, payload: dict):
        super().__init__(str(payload.get("message", status)))
        self.status = status
        self.payload = payload
