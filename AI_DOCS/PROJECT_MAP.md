# Zapret 2 GUI — карта проекта

> Обновлено 2026-10-24. Версия — Pre-Release 0.10 (тег `3fd25f0`) + коммиты
> после релиза. Главные правила и текущее состояние — `AGENTS.md`.
> Индекс документации — `AI_DOCS/README.md`.

## Что делает программа

Обход DPI/ТСПУ на Windows: `winws2.exe` (Lua-desync) + GUI (pywebview/WebView2)
+ тестер + диагностика + служба.

```
Пользователь -> GUI -> локальный HTTP API -> winws2 + WinDivert
```

## Архитектура

```
Frontend (SPA)                    Backend (HTTP)              Core                 Система
index.html + css + js/app.js      server/server.py            core/*.py            winws2.exe
HTTP REST + polling <---------->  /api/* (api_*.py)           curl + subprocess    WinDivert + Lua
GUI-оболочка: main.py (pywebview/Local HTTP, UAC, single-instance)
```

- **main.py** — UAC, WebView2, single-instance, место запуска, self-heal.
- **server/** — loopback HTTP, токен, `/api/*`; хендлеры по доменам
  (`api_config`, `api_service`, `api_tester`, `api_games`, `api_probe`, ...).
- **core/** — launcher (`@conf`, args, validate), tester/probes, diagnostics,
  service_manager, zapret_controller, games, process_probe, updater,
  update_verify, session_recovery, collector/logs.
- **frontend/** — HTML/CSS/JS SPA, без pywebview API (только HTTP).
- **presets/** — 11 release-стратегий; `exp-*`/`cand-*` удалены, тестовый
  untracked `flaky.txt` не релиз.
- **bin/lua/blobs/lists/windivert/** — движок и данные.
- **build.py / build_portable.py / build_lite.py** — EXE / portable / lite.

## Ключевые механизмы

- **Пресеты** — текстовые файлы; launcher резолвит `@lua/@blobs/@lists/@windivert`,
  тогглы и `%GameFilter%`. Основной запуск/служба — длинные пути через
  `@conf`; 8.3 — только аварийный `.bat`.
- **Тогглы:** GameFilter, Discord Voice, autohostlist, ipset_catchall,
  fake_blob, debug; изменение аргументов требует перезапуска/переустановки.
- **Тестер:** naked-базлайн, sanity (dry-run + покрытие), рейтинг без QUIC-
  квирков, custom, речек спорных. QUIC-класс — нейтральный статус, не fail.
- **Диагностика:** права/путь/служба/драйвер/тип блокировки, DNS-здоровье,
  launch_spot, отчёт. SYN-блэкхол не лечится десинком.
- **Probe:** история TCP endpoints (порты/состояния) + UDP pktmon
  (sent/recv) + DNS-кэш; вердикт по SYN/UDP.
- **Игры:** домены — union user+games; UDP — пулы по `(cutoff,repeats,wide)`;
  Wardogs 4192-4194 + AWS pool; дубли/wide и first-match учитывать.
- **Служба:** Win32 API создания/конфигурации, чтение ImagePath из реестра,
  recovery `sc failure`; перед удалением — остановить обход.
- **Обновления:** Ed25519 fail-closed, sha256, manifest, откат portable.
- **WebView2:** GUI-зависимость; preflight проверяет Runtime, при отсутствии
  открывает Edge/Chrome app-режим; детали — `PLAN_WEBVIEW2_FALLBACK.md`.
- **Параметры/данные/история:** `ENGINEERING_NOTES.md`; raw archive —
  `0bd6626^:AI_DOCS/archive/`.

## Репозитории и документация

- Истина: `Documents\GitHub\Zapret-2-GUI` (`origin`).
- Зеркало: `Desktop\Zapret 2 GUI\zapret2_gui` (живые user-данные; синк).
- Доки: `AI_DOCS/AGENTS.md` (главное), `AI_DOCS/README.md` (индекс).

## Правила (кратко)

- Все три сборщика пересобирать после изменений; `Windows build/` + `.sha256`.
- hosts — атомарно; user-файлы не перезаписывать; секреты не коммитить.
- Перед «исправлением» — воспроизведение и проверка текущего кода.
