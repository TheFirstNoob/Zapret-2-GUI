# Zapret 2 GUI — Аудит тестера (обновлено 2026-07-29, Pre-release 0.1)

## Решённые проблемы

| # | Проблема | Решение | Статус |
|---|----------|---------|--------|
| 1 | aiohttp -> ложные TIMEOUT (IPv6) | curl.exe -4 --http1.1 | ✅ |
| 2 | JSON-профили -> баги путей | .txt пресеты | ✅ |
| 3 | subprocess.Popen -> WinDivert не грузится | Привилегии + Popen | ✅ |
| 4 | hostlist include -> стратегия не применяется | hostlist-exclude only | ✅ |
| 5 | fake+multisplit -> самоглушение | Сбалансировано в default.txt | ✅ |
| 6 | tcp_ts fooling | Работает в default.txt | ✅ |
| 7 | SMOKE_THRESHOLD=0.5 | 0.2 | ✅ |
| 8 | TIMEOUT=-0.2 штраф | 0.0 | ✅ |
| 9 | WinDivert cleanup без задержки | 0.5s | ✅ |
| 10 | Фаззер невалидные мутации | Удалён | ✅ |
| 11 | Блоб-тестирование ломает профили | Удалено | ✅ |
| 12 | 90+ профилей слишком долго | 8 пресетов | ✅ |
| 13 | **winws2 не пробивал DPI вообще** | **default.txt универсален** | **✅** |
| 14 | HEAD-запросы давали ложные 403/418 | GET + --max-redirs 2 | ✅ |
| 15 | Пустой User-Agent ломал CDN | Браузерный UA | ✅ |
| 16 | HTTP 403/498/503 считались блокировкой | Любой код ≥ 100 -> OK | ✅ |
| 17 | Naked test зависал | Правильный порядок kill | ✅ |
| 18 | Python-процесс оставался после закрытия | `os._exit(0)` | ✅ |
| 19 | SeLoadDriverPrivilege на фильтр. токенах | Fallback через linked token | ✅ |
| 20 | `test_profile` 200 строк | Разбит на подфункции | ✅ |
| 21 | `_curl_http` + `_curl_tls` | Единый `_curl_test` | ✅ |
| 22 | Мёртвые REST-ручки | Удалены | ✅ |
| 23 | `time.sleep(0.5)` в async функциях | `await asyncio.sleep(0.5)` | ✅ |
| 24 | Копипаста колбэков | Фабрики | ✅ |
| 25 | Дублирование сериализации | `_serialize_result` | ✅ |
| 26 | `_short_path` копипаста | `core/utils.py` | ✅ |
| 27 | Нет `--debug` лога | Добавлен | ✅ |
| 28 | PID проверка при каждом `is_running()` | PID cache 1s TTL | ✅ |
| 29 | Нет统一ного exception для abort | `_TestAbort` | ✅ |
| 30 | Служба: путь из `__file__` в frozen exe | Параметр `root_dir` | ✅ |
| 31 | Служба: статус по tasklist | Парсинг sc query STATE | ✅ |
| 32 | **Ложные 000 (флак) — ютуб открывался, тестер показывал 000** | **Речек спорных RATED-доменов в конце прогона (`_recheck_contested`): «заблокирован» vs «временно недоступен — ретест»** | **✅** |
| 33 | Фон: поллинг `/api/service/status` гонял 2× `sc query` каждые 9с | TTL-кэш статуса службы (10с) + инвалидация на мутациях | ✅ |
| 34 | `blocked_domains` = union по всем стратегиям (домен, пробитый другой стратегией, числился «не пробито») | Считается по лучшей стратегии | ✅ |
| 35 | Речек спорных доменов конфликтовал с YouTube-QUIC-вердиктом («заблокирован» при вердикте ok) | `quirk_skip` — quirk-домены не перепроверяются | ✅ |

## Текущее состояние

### Работает
- default.txt — универсальная стратегия (все провайдеры)
- curl-тесты (HTTP GET, TLS handshake, ping)
- Запуск winws2 с привилегиями
- @presets/name.txt загрузка пресетов
- Тестирование профилей через WebSocket
- ZIP-отчёты с системной информацией
- CDN-хосты проверка
- Установка/удаление службы Windows
- Тогглы: GameFilter, Discord Voice, DEBUG, Auto Hostlist
- Прогрессивная отдача результатов (result_cb)

### Удалено (мёртвый код)
- `core/strategy_parser.py`, `fuzzer.py`, `hosts_manager.py`, `custom_lists.py`
- `profiles/*.json`, `test_connectivity.py`
- `_tcp1620_test_async`, `_cache_key/put`, `test_profile_with_blob`
- API: hostlists, custom-lists, diagnose, fuzz
- 17 тестовых пресетов

### Требует доработки
- Game TCP fallback для игр (Minecraft)
- Diagnoser (diagnoser.py) — реворк
- Profile editor в UI
- `full_analyzer.py` — `time.sleep()` → `asyncio.sleep()`
