# AI_DOCS — индекс документации

> Обновлено 2026-11-15. Актуальная версия — **Pre-Release 0.11.1**
> (опубликован, тег `Pre-Release-0.11.1`). Предыдущие релизы — 0.11 и
> 0.10 (тег `3fd25f0`, immutable). 0.11.1 собирать из HEAD; архивы 27.10
> устарели (1.0.6, пресеты без `midsld`) и не публикуются.

## Читать в таком порядке

1. **`AGENTS.md`** — текущие правила, состояние, архитектура. Главный файл.
2. **`PROJECT_MAP.md`** — карта кода и механизмов.
3. **`ENGINEERING_NOTES.md`** — параметры, источники данных, история
   экспериментов и решения «не переоткрывать».
4. **`RELEASE_CHECKLIST.md`** — выпуск, подпись, ассеты.
5. **`STRATEGY_GUIDE.md`** — как тестировать и какие параметры крутить.
6. **`STRATEGY_ROADMAP.md`** — стратегические решения и бэклог.
7. **`ARG_FILE_RESEARCH_2026-10-14.md`** — механизм `@conf` (внедрён).
8. **`PLAN_WEBVIEW2_FALLBACK.md`** — WebView2 preflight/fallback и его хвосты.
9. **`YOUTUBE_VIDEO_STALL_2026-11.md`** — видео-спиннер 2026-11: GGC/TLS-CH,
   SABR-only, QUIC, что не переоткрывать, что делать в 0.11.
10. **`TECH_AUDIT_2026-11-14.md`** — тех-аудит: исправленные баги, бэклог,
   оптимизации, применимость zapret2 1.0.6/1.0.7.
11. **`UPSTREAM_SYNC_2026-11-14.md`** — dpi-detector/dpi-checkers/Flowseal:
   что актуально, ASN Checker, ipset staged/A-B, лицензии.
12. **`TEAM_PLAYBOOK.md`** — как Lead использует durable-агентов: reuse first,
   контекст-кэш, disjoint scopes, без повторного чтения проекта.
13. **`RELEASE_READINESS_0.11.md`** — готовность 0.11: вердикт, блокеры,
   обязательная последовательность, live-чек-лист.
14. **`RECHECK_2026-11-15.md`** — полный recheck 0.11: P0/P1-фиксы,
   live-матрица и остаточные P2/P3; фиксы выпущены в 0.11.1.

Пользовательский мануал — в корне репозитория: `README.md`.
Список изменений — `CHANGELOG.md`.

## Текущие документы

| Файл | Статус |
|---|---|
| `AGENTS.md` | текущая памятка |
| `PROJECT_MAP.md` | текущая карта |
| `ENGINEERING_NOTES.md` | параметры, источники, история |
| `RELEASE_CHECKLIST.md` | текущий чеклист |
| `STRATEGY_GUIDE.md` | текущая методика |
| `STRATEGY_ROADMAP.md` | текущие принципы/бэклог |
| `ARG_FILE_RESEARCH_2026-10-14.md` | справочник по `@conf` |
| `PLAN_WEBVIEW2_FALLBACK.md` | preflight/fallback, остались проверки |
| `YOUTUBE_VIDEO_STALL_2026-11.md` | YouTube видео-спиннер 2026-11 (курируемая выжимка) |
| `TECH_AUDIT_2026-11-14.md` | тех-аудит 2026-11-14: фиксы + бэклог |
| `TEAM_PLAYBOOK.md` | правила работы Lead с durable-агентами |
| `UPSTREAM_SYNC_2026-11-14.md` | dpi-detector/dpi-checkers/Flowseal: sync + A/B-план |
| `RELEASE_READINESS_0.11.md` | готовность 0.11: вердикт/блокеры/шаги |
| `RECHECK_2026-11-15.md` | полный recheck 0.11: P0/P1-фиксы + live-матрица (0.11.1) |
| `README.md` (корень) | пользовательский мануал |
| `CHANGELOG.md` (корень) | список изменений 0.11 |

## Исторические документы

Исходные ревью, планы 0.9, handoff и research-заметки удалены при чистке
2026-10-24, но остаются в git-истории (`0bd6626^`). Сжатая выжимка и
индекс — `ENGINEERING_NOTES.md`; чувствительные IP/провайдерские детали
в git заново не добавлять.

## Текущее состояние

- winws2 **1.0.7** установлен (HEAD); stock-lua обновлены, `zapret-custom.lua`
  сохранён; dry-run и служба проверены. 0.10 шипится с 1.0.5; черновик 0.11
  от 27.10 — 1.0.6 и пресеты без `midsld`, поэтому релиз — из HEAD.

## Текущие открытые задачи

- WebView2: preflight + автоматический/`--browser` fallback реализованы;
  проверить на чистом Win10 без Runtime, UX/токен браузерного режима.
- `presets/flaky.txt` (широкий UDP 4190-4195, `ACTIVE_GAME_UDP`,
  `repeats=12`) в рабочем дереве отсутствует; в релиз не входит.
- Live-прогон тестера на движке 1.0.7 и живая проверка DNS-профилей на
  разных адаптерах — после стабилизации сети/исключения случайного флака.
- CDN/ASN refresh — запаркован; ipset-база остаётся наша.
- 0.11.1: **опубликован 2026-11-15** (тег `Pre-Release-0.11.1`, 8 pretty-
  ассетов, подпись `50DCECF29451`) — P0/P1-фиксы полного recheck: восстановление
  службы, WinDivert-preflight, tester lock, update correctness. Осталась live-
  приёмка после публикации. В release notes «фикс YouTube» не обещать.
- YouTube: у части пользователей 0.10 видео-спиннер — внешняя волна GGC/TLS-CH
  (см. `YOUTUBE_VIDEO_STALL_2026-11.md`); ждём логи affected
  (DevTools Protocol/Method/Size/Remote Address, форма A/B).
- Тех-аудит 2026-11-14: P0/P1 и fix batch (T9–T14) закрыты —
  `TECH_AUDIT_2026-11-14.md` §3/§6. **Live-приёмка ещё не пройдена:**
  SCM install/remove/restart, portable-апдейт, живой тестер/H3/CDN, живой DNS
  apply/reset, Win10/PS5.1. Portable 0.10→0.11 — переустановка из архива.
- Upstream-sync 2026-11-14: данные dpi-detector/dpi-checkers актуальны,
  атрибуция добавлена, ASN Checker приведён к upstream-семантике; ipset-
  staged (27206 CIDR) ждёт A/B catchall + break-class чек; post-0.11 идеи
  (whitelist-SNI рунг, CIDR-whitelist precheck) — `UPSTREAM_SYNC_2026-11-14.md`.

## Чувствительные данные

Регион/провайдер/публичные IP и медицинские/сетевые детали конкретных
пользователей в репозиторий не писать. Такие кейсы ведутся только локально,
вне репозитория и публичных документов. Сырые измерения расследований
(raw-JSON, логи, pcap, IP/провайдер) — в gitignored `_analysis/`; в репо
попадают только обезличенные выжимки (см. `YOUTUBE_VIDEO_STALL_2026-11.md`).
