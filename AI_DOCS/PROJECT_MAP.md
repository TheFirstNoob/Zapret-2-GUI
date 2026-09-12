# Zapret 2 GUI — Карта проекта (обновлено 2026-09-13, Pre-Release 0.7.1)

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
├── main.py                 точка входа (UAC, webview GUI, проверка места запуска); main.pyw в portable
├── build.py                сборка EXE (PyInstaller onefile)
├── build_portable.py       portable: python-3.13.14-embed + pywebview (БЕЗ паковщика)
├── build_lite.py           lite: winws2 + батники (start-*, service.bat, test.ps1)
├── VERSION                 строка версии для update-check (raw → API фолбэк)
├── version_info.txt        метаданные EXE
├── hosts.txt               ПОЛНЫЙ готовый hosts (ИИ-гео, github-fix, 0.0.0.0-заглушки)
├── core/                   config, launcher, tester, diagnostics, service_manager,
│                           zapret_controller, full_analyzer, collector, updates,
│                           test_logger, admin, utils, conflict_scan, tcp_timestamps,
│                           process_probe, strategy_builder
├── server/server.py        HTTP backend + tester-action runner (threading)
├── frontend/               SPA: index.html, css/app.css, js/app.js
├── presets/                11 release .txt стратегий + exp-/cand- стенды (скрыты)
│                           + custom (генерируется тестером)
├── lua/ blobs/ lists/ bin/ windivert/
├── tools/                  dev-утилиты: pkt_*, ab_candidate, make_blob, ui_dump,
│                           ui_dump_server, run_preset, stat_preset, diag_friend
└── AI_DOCS/                AGENTS.md (критично!), rules, PROJECT_MAP, STRATEGY_GUIDE,
                            STRATEGY_TRIALS, STRATEGY_ROADMAP, ASN_SCAN_NOTES,
                            TESTER_AUDIT, ISP_NOTES, EXTERNAL_NOTES
```

## Ключевые механизмы

- **Пресеты** — .txt, каждая строка = аргумент winws2. Лаунчер резолвит
  `@lua/@blobs/@lists/@windivert` (lua/blobs в `--opt=@путь`!), подставляет
  тогглы (GameFilter/DiscordVoice/ipset_catchall/autohostlist/debug).
- **Тогглы** (AppConfig): game_filter_mode, discord_voice, winws2_debug,
  autohostlist, **ipset_catchall** (заменяет list-general на --ipset+
  --ipset-exclude; выключен по умолчанию), fake_blob (селектор «Блоб фейка»).
- **Тестер** (`/api/tester/action` + polling): naked-базлайн, sanity
  (dry-run профилей + покрытие списков), вердикт+рекомендация, ключевые
  хосты (Discord/YouTube, QUIC_OK-инференс), речек спорных доменов. custom
  пересобирается КАЖДЫМ тестом из лучших сегментов и всегда проходит
  проверку движком. QUIC-класс вне network_rate («≈ QUIC»).
- **Диагностика** (`/api/diagnose`): права/путь/процесс/служба/пресет/
  связь + классификатор типа блокировки (DNS/IP/SNI через SNI-swap) +
  dns_health + launch_spot (0.8 WIP) + отчёт. Детали — человеческим языком;
  техника — в поле `tech` (tooltip + отчёт).
- **Probe (анализ приложения)** (`/api/probe`): pktmon-захват процесса,
  вердикт по sent/recv (UDP-глушение → WARP), домены из DNS-cache.
- **CDN-стабилизация** (`/api/cdn/*`): A/B ipset ON/OFF, вердикты
  «чинит/ломает», «Применить все правки (N)» (планировщик _plan_cdn_action).
- **ASN-скан** (110 IP): диагностический, защита останавливается и
  возвращается сервис-осведомлённо; SNI=example.com (см. ASN_SCAN_NOTES).
- **Служба**: winws2.exe напрямую (см. AGENTS снапшот), reconfigure на старт.
- **Update-check**: raw VERSION → API contents/VERSION фолбэк → баннер
  (GitHub + jsDelivr зеркало).
- **Конфликт Zapret 1**: отказ запуска/службы/теста при winws.exe или
  службе zapret. **Конфликт окружения**: conflict_scan (DPI-тулзы, VPN).
- **Валидация**: validate_args (dry-run + текст ошибок) до старта/службы;
  validate_lua (--intercept=0) компилит lua-init.

## Репозитории

- Канонический: `Documents\GitHub\Zapret-2-GUI` (remote: origin → GitHub).
- Desktop-копия: `Desktop\Zapret 2 GUI\zapret2_gui` — рабочая, синхронизируется
  коммитами (git mirror). Правки всегда в GitHub-репо, потом sync + rebuild.

## Правила (кратко, подробно в AGENTS.md)

- Все три сборщика пересобирать после изменений; артефакты в `Windows build/`
  (zip + sha256).
- hosts пишется только атомарно; гео-записи не удалять без замены.
- См. AGENTS.md «СЕССИЯ-СНАПШОТ» — там полный статус и висяки.