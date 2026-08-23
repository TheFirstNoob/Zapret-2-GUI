# Zapret 2 GUI — Карта проекта (2026-07-29, Pre-release 0.1)

## Что делает программа

**Zapret 2 GUI** — обход DPI с универсальной стратегией (`default.txt`), тестером и установкой службой.

**Поток:** Пользователь → Выбор стратегии → Запуск winws2 / Установка службы → Обход DPI

---

## Архитектура

```
Frontend (SPA)                        Backend (HTTP)               Core                         Система
index.html + css/app.css + js/app.js  server/server.py             tester.py                    winws2.exe
HTTP REST + WebSocket     <------->   BaseHTTP + /ws/tester  --->  curl-тесты + subprocess    WinDivert + Lua
```

---

## Структура файлов

```
zapret2_gui/
├── main.py                 ← точка входа (UAC elevation, webview GUI)
├── server/server.py        ← HTTP backend + WebSocket tester
├── core/
│   ├── utils.py            ← shared utilities (short_path)
│   ├── tester.py           ← curl-тестер, управление winws2, scoring
│   ├── full_analyzer.py    ← полный анализ (сравнение профилей)
│   ├── collector.py        ← сбор системной информации + ZIP-отчёты
│   ├── zapret_controller.py ← запуск/статус/остановка winws2
│   ├── launcher.py         ← сборка аргументов + валидация (--dry-run) + запуск winws2
│   ├── diagnostics.py      ← самодиагностика для пользователей (проверки + отчёт)
│   ├── service_manager.py  ← установка/удаление службы Windows
│   ├── config.py           ← AppConfig, VERSION
│   ├── test_logger.py      ← логгер тестов
│   └── admin.py            ← is_admin(), привилегии
├── frontend/               ← SPA фронтенд
│   ├── index.html          ← разметка + навигация
│   ├── css/app.css         ← стили тёмной темы
│   └── js/app.js           ← логика приложения
├── presets/                ← .txt пресеты для winws2 (8 шт)
│   ├── default.txt         ← УНИВЕРСАЛЬНАЯ стратегия
│   ├── fake-only.txt       ← pure fake
│   ├── fakedsplit.txt      ← fake + fakedsplit
│   ├── hostfakesplit.txt   ← hostname fake + split
│   ├── fake-disorder.txt   ← fake + disorder
│   ├── fake-multidisorder.txt ← fake + multidisorder
│   └── multisplit-*.txt    ← multisplit вариации
├── lua/                    ← Lua-скрипты (6 файлов)
├── blobs/                  ← бинарные блобы (.bin)
├── lists/                  ← списки доменов (list-general, list-google и др.)
├── bin/                    ← winws2.exe + WinDivert
├── AI_DOCS/                ← документация для агентов ИИ
└── zapret2_config.json     ← конфигурация пользователя
```

---

## API Endpoints

| Method | Endpoint | Описание |
|--------|----------|----------|
| GET | `/api/config` | Настройки |
| POST | `/api/config` | Сохранить настройки |
| GET | `/api/status` | Статус winws2 + zapret1 + profiles |
| POST | `/api/start` | Запустить профиль |
| POST | `/api/stop` | Остановить |
| GET/POST | `/api/exclude-list` | Пользовательские исключения |
| GET/POST | `/api/include-list` | Пользовательские включения |
| GET | `/api/zapret1/strategies` | Список .bat стратегий Zapret 1 |
| POST | `/api/zapret1/start` | Запустить стратегию Zapret 1 |
| POST | `/api/zapret1/stop` | Остановить Zapret 1 |
| WS | `/ws/tester` | Тестирование (test, test_profiles, full_analysis, current, naked) |
| GET | `/api/service/status` | Статус службы zapret2 |
| POST | `/api/service/install` | Установить службу |
| POST | `/api/service/remove` | Удалить службу |
| POST | `/api/export-report` | ZIP-отчёт |

---

## Ключевые технические решения

### default.txt — универсальная стратегия
Работает у всех протестированных провайдеров (Новороссийск, Ижевск, Воронеж, СПб).
Содержит 7 блоков: Discord Voice, Discord Media TCP, Discord TCP tls, Google TCP tls, General TCP, QUIC Google, QUIC General.

### Тестирование: curl.exe
- curl с `-4 --http1.1` + реалистичный `User-Agent` — надёжно
- Любой HTTP-код ≥ 100 считается успехом

### Пресеты: .txt (не JSON)
Каждая строка = 1 аргумент, никакого парсинга.

### Сервисная установка
- `sc create zapret2` + авто-запуск
- Конфликт-проверка с службой Zapret 1

### Тогглы
- GameFilter (TCP/UDP на портах 1024-65535)
- Discord Voice (UDP 19294-19344,50000-50100)
- DEBUG Winws2 (файловый лог)
- Auto Hostlist (автоуправление hostlist)

---

## Что удалено

- JSON-профили → .txt пресеты
- aiohttp → curl.exe
- strategy_parser.py, fuzzer.py, hosts_manager.py, custom_lists.py
- 17 тестовых пресетов → 8 актуальных
- Мёртвые REST-ручки (/api/diagnose, /api/hostlists/* и др.)
