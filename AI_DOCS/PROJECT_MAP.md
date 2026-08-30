# Zapret 2 GUI — Карта проекта (2026-08-30, Pre-Release 0.4)

## Что делает программа

**Zapret 2 GUI** — обход DPI (ТСПУ) на Windows: winws2.exe (lua-desync) +
GUI (webview) + тестер + диагностика + служба.

**Поток:** Пользователь → Главная (запуск/пресет/тогглы) → winws2 → обход DPI.

## Архитектура

```
Frontend (SPA)                    Backend (HTTP)              Core                Система
index.html + css + js/app.js      server/server.py            core/*.py           winws2.exe
HTTP REST + polling (нет WS) <--> BaseHTTP + /api/* + tester  curl + subprocess   WinDivert + Lua
GUI-оболочка: main.py (pywebview, локальный HTTP-сервер, UAC-самоподъём)
```

## Файлы и дистрибутивы

```
zapret2_gui/
├── main.py                 точка входа (UAC, webview GUI); main.pyw в portable
├── build.py                сборка EXE (PyInstaller onefile, --exclude-module...)
├── build_portable.py       portable: python-3.13.14-embed + pywebview (БЕЗ паковщика)
├── build_lite.py           lite: папка winws2 + батники (start-*, service.bat, test.bat)
├── VERSION                 строка версии для update-check (raw → API фолбэк)
├── version_info.txt        метаданные EXE (версия/издатель — против ложняков)
├── hosts.txt               ПОЛНЫЙ готовый hosts для раздачи (см. AGENTS §27)
├── core/                   config, launcher, tester, diagnostics, service_manager,
│                           zapret_controller, full_analyzer, collector, updates,
│                           test_logger, admin, utils
├── server/server.py        HTTP backend + tester-action runner (threading)
├── frontend/               SPA: index.html, css/app.css, js/app.js
├── presets/                8 .txt стратегий (default + 7)
├── lua/ blobs/ lists/ bin/ windivert/
└── AI_DOCS/                AGENTS.md (критично!), rules, PROJECT_MAP, STRATEGY_GUIDE,
                            TESTER_AUDIT, ISP_NOTES
```

## Ключевые механизмы

- **Пресеты** — .txt, каждая строка = аргумент winws2. Лаунчер резолвит
  `@lua/@blobs/@lists/@windivert` (lua/blobs в `--opt=@путь`!), подставляет
  тогглы (GameFilter/DiscordVoice/ipset_catchall/autohostlist/debug).
- **Тогглы** (AppConfig): game_filter_mode, discord_voice, winws2_debug,
  autohostlist, **ipset_catchall** (заменяет list-general на --ipset+
  --ipset-exclude; выключен по умолчанию).
- **Тестер** (`/api/tester/action` + polling): naked-базлайн, sanity
  (dry-run профилей + покрытие списков), вердикт+рекомендация, ключевые
  хосты (Discord/YouTube), «Запустить рекомендованную».
- **Диагностика** (`/api/diagnose`): права/путь/процесс/служба/пресет/
  связь + **тип блокировки** (DNS/IP/SNI через SNI-swap) + отчёт.
- **Служба**: winws2.exe напрямую (см. AGENTS-снапшот), reconfigure на старт.
- **Update-check**: raw VERSION → API contents/VERSION фолбэк → баннер
  (GitHub + jsDelivr зеркало).
- **Конфликт Zapret 1**: отказ запуска/службы/теста при winws.exe или
  службе zapret.

## Репозитории

- Канонический: `Documents\GitHub\Zapret-2-GUI` (remote: origin → GitHub).
- Desktop-копия: `Desktop\Zapret 2 GUI\zapret2_gui` — рабочая, синхронизируется
  коммитами (git mirror). Правки всегда в GitHub-репо, потом sync + rebuild.

## Правила (кратко, подробно в AGENTS.md)

- Все три сборщика пересобирать после изменений; артефакты в `Windows build/`
  (только zip + sha256).
- hosts пишется только атомарно; гео-записи не удалять без замены.
- См. AGENTS.md «СЕССИЯ-СНАПШОТ» — там полный статус и висяки.