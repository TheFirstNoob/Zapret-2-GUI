> Снимок аудита на коммите `86d1634`; номера строк могут сплыть.
> Это план-рекорд фазы рефакторинга (прогресс — в §8 внизу).

# Архитектурный аудит Zapret 2 GUI (deep-dive, read-only)

Дата: 2026-10-14. Репо: `C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI` (HEAD `86d1634`).
База: `arch_census.json` (механическая перепись уже сделана, повторно не запускалась).
Формат: только чтение кода/статический анализ; сборки и полный тестер не запускались;
служба `zapret2`, hosts, сеть не трогались.
Легенда достоверности: без пометки — проверено по коду; «гипотеза» — вывод по косвенным данным.

## Оглавление

1. [Карта слоёв, потоки, зависимости](#1-карта-слоёв-потоки-зависимости)
2. [God objects: server.py / app.js / tester.py / launcher.py / diagnostics.py](#2-god-objects-и-предложения-по-распилу)
3. [Дубли и близкие дубли](#3-дубли-и-близкие-дубли)
4. [Инкапсуляция и OOP-практика](#4-инкапсуляция-и-oop-практика)
5. [Anti-список: что не трогать](#5-anti-список-что-не-трогать)
6. [Топ-10 находок по приоритету](#6-топ-10-вектор-полировки)
7. [Приложение: как проверять без регрессий](#7-приложение-как-проверять-без-регрессий)

---

## 1. Карта слоёв, потоки, зависимости

### 1.1 Схема слоёв (поток управления)

```
main.py (491 LOC)  ── entry: admin-elevation, single-instance mutex,
  │                   MOTW-strip, self-heal data-dir, WebView2
  │  HTTP 127.0.0.1:<free-port> + X-App-Token + Host-guard
  ▼
server/server.py (3030 LOC, 124 funcs: 40 top-level + 56 _handle_* + транспорт)
  │   ▲ polling /api/* (47 уникальных эндпоинтов; GET 24 + POST 38 маршрутов)
  │   │
  │   └── frontend/js/app.js (4394 LOC, 462 funcs, 14 объектов: Status, App,
  │        MainPage, TesterPage(1341), ListsPage, CdnStab, GamesPage, AsnPage,
  │        DiagnosticsPage, AppInfo, Popover, Modal, Confirm, Activity)
  ▼
core/* (8075 LOC)
  core.launcher(696) ── core.games, core.admin, core.applog, core.utils
  core.utils(337)   ── run_sc/tasklist/winreg/WinDivert-heal   [хаб]
  core.tester(1655) ── core.launcher, core.test_logger
  core.zapret_controller(151) ── core.launcher, core.tcp_timestamps
  core.service_manager(687) ── core.utils (sc.exe/SCM/registry)
  core.updater(590) ── core.updates ── core.config
  core.diagnostics(814) ── tester, launcher, utils, admin, conflict_scan,
  │                        tcp_timestamps, service_manager
  core.list_health(342), core.games(541), core.collector(220),
  core.process_probe(712), core.full_analyzer(126), core.strategy_builder(231),
  core.conflict_scan(156), core.config(82), core.applog(47), core.test_logger(95)
  ▼
ОС/движок: sc.exe, tasklist/taskkill, curl.exe, winws2.exe(+WinDivert.dll/sys),
           netsh, pktmon, tracert/ping/nslookup/arp, реестр (winreg)
```

### 1.2 Фактическое направление зависимостей

- **core не зависит от server/frontend** — ни одного импорта `server`/`frontend`
  из `core/*` (проверено обходом всех .py; opposite: `server.server` импортирует
  `core.*` 17 раз — census `imports`).
- `main.py → server.server` (2 импорта: `main.py:419`, `main.py:459` — второй
  приватный: `from server.server import _tester`).
- **Циклов импортов 0** (полный обход графа `core/ server/ main.py tools/`, DFS;
  включая gitignore-копию `portable/app/` — она вне сборки и вне git, см. §5).
- Хабы подтверждены census: `core.launcher` (in-degree 16), `core.utils` (16),
  `core.config` (11), `core.service_manager` (11). Фактический «скрытый» хаб —
  сам `server.py`: 17 core-модулей + 41 `except Exception`.
- `tools/* → server.server` есть в 5 dev-файлах (`ui_dump_server.py:17`,
  `_ui_shots.py:21`, `security/test_updates_security.py:19`, `_test_fast_once.py:48`,
  `_test_server_fast.py:20`) — допустимо: tools не входят в поставку.
- Ленивые импорты внутри функций server.py (`core.diagnostics` в
  `_handle_diagnose_action:2588`, `core.updater` в `_run_update_worker:182`,
  `core.games` в хендлерах 2099/2124/2162 и т.п.) — де-факто это «разрыв слоя»
  в сторону: server знает детали каждого core-модуля, но делает импорт в момент
  вызова. Стилистически это скрывает реальный размер связанности server.py.

### 1.3 «Скрытые» связи (не импорт)

| Тип связи | Места | Комментарий |
|---|---|---|
| subprocess (`sc.exe`) | `core/utils.run_sc:116` (единственная точка), используют: `service_manager`, `server:779`, `utils.fix_stale_windivert_services` | ок, один транспорт |
| subprocess (`tasklist/taskkill`) | 9 независимых tasklist-обёрток (см. §3.7), taskkill в 5+ файлах | дубли |
| subprocess (`curl.exe`) | 7 product-сайтов (tester 3, diagnostics 2, server 2) + ~11 в tools | дубли |
| subprocess (прочее) | `pktmon` (`process_probe.py:168`, `main.py:466-468`), `netsh` (`collector:75`, `tcp_timestamps`), `tracert` (`tester:814`, `collector:84`), `ping`, `nslookup`, `arp`, `ipconfig`, powershell (`process_probe.PS_BASE:25`, `server._check_vpn:492`, `tester._kill_never_hang:460`) | скрытая ОС-обвязка |
| Файлы как интерфейс | `presets/*.txt` (launcher читает, tester пишет `_probe_cdn.txt:1359`), `lists/*.txt` (launcher инжектит, `list_health` пишет, games пишет `list-games.txt`/`list-include-all.txt:452`, tester пишет `list-probe.txt:1358` и временно `ipset-include-user.txt:1396-1433`), `tcp1620_test_body.bin`, `asn_probe_body.bin:1253`, `games.json`, `zapret2_config.json`, `test_session.log`, `data_version.txt` | launcher/tester «разговаривают» через одни и те же файлы с разными модулями |
| Реестр | `service_manager._read_stored_binpath:112`, `utils.windivert_service_state:162`, `utils.windivert_delete_flag:180`, `utils.stale_windivert_services:78`, `tcp_timestamps` | SCM ImagePath читается в обход sc/CIM (осознанно — длинные binPath) |
| Объекты ОС | single-instance мьютекс `main.py:332-384`; служба `zapret2`; служба драйвера `WinDivert`; `pktmon`-сессия | скрытое глобальное состояние машины |
| Процессный контракт JS↔Python | токен-инъекция `app.js:23-30`; строковые статусы (см. §3.3); `frontend-log` `app.js:52-68` ↔ `server:2011` | нет схемы/версии контракта |

Вывод §1: слои в целом чистые (UI→HTTP→core→OS), нарушений core→server нет,
циклов нет. Основная проблема — не направление, а **толщина server.py** (он и
транспорт, и вся доменная оркестрация) и **conтракт-через-строки** (статусы,
пути файлов, имена пресетов).

---

## 2. God objects и предложения по распилу

### 2.1 server/server.py — 3030 LOC, 124 функции, 3 класса

Внутренние группы ответственности (фактические диапазоны строк):

| Группа | Строки | Объём |
|---|---|---|
| Импорты + глобальное состояние (`_root_dir`…`_server`, кэши) | 1-58, 164-176 | ~70 |
| `TesterState` (lock/progress/results/final) | 63-121 | 58 |
| Debug-логи (`_debug_append/_probe_debug/_ui_debug`) | 135-162 | 28 |
| Апдейтер-воркер `_run_update_worker` | 179-318 | 140 |
| Фабрики/хелперы (`get_root_dir/get_tester/_ui_presets/_checkers_busy/init`) | 321-422 | 100 |
| List/IP-хелперы (`_clean_list_text/_read_lines/_read_networks/_plan_cdn_action`) | 553-658 | 106 |
| Восстановление защиты + timeout-обвязки + `_scan_winws_exe/_zapret1_installed` | 661-784 | 124 |
| Вердикт/блобы/речек (`_build_recommendation:798` 150 строк, `_recommended_blob_keys:973`, `_recheck_contested:1002` 86) | 790-1087 | 298 |
| ASN/blob/тестер-воркеры (`_run_asn_scan:1090`, `_run_blob_probe:1125`, `_run_tester_action:1168` — **399 строк**) | 1090-1567 | 478 |
| `ZapretHandler` (56 `_handle_*`, транспорт, do_GET/do_POST) | 1571-2997 | **1427** |
| Lifecycle (`ThreadedHTTPServer`, `create_server/stop_server`) | 3002-3030 | 29 |

Группы хендлеров: service×6, probe×6, games×5, zapret1×4, update×4, contested×3,
lists×3, config×2, settings×2, diagnose×2, tester×2, cdn×2, +15 одиночных.

**Предложение по распилу (файлы, границы интерфейсов):**

1. `server/app_state.py` — `TesterState`, `_tester_state`, `_diag_state`, `_updater_state`
   (dataclass — см. §4), локи, кэши, фабрики `get_root_dir/get_tester/get_controller/...`,
   `_checkers_busy`. Интерфейс: «доступ к синглтонам», ноль импортов из хендлеров.
2. `server/http_app.py` — `ThreadedHTTPServer`, `create_server/stop_server`,
   `ZapretHandler` **только транспорт**: `_host_allowed/_check_token/_send_*/_parse_body/_handle_static/_handle_index`,
   `do_GET/do_POST` как таблицы `{path: handler}` (роутер ~60 строк вместо 300+ ветвлений).
3. `server/api_*.py` — доменные хендлеры как свободные функции/мини-модули
   (`api_config.py`, `api_lists.py`, `api_service.py`, `api_tester.py`, `api_probe.py`,
   `api_games.py`, `api_update.py`, `api_diag.py`, `api_cdn.py`). Таблицы роутов
   собираются в `http_app.py`.
4. `server/tester_flow.py` — `_run_tester_action` + `_run_asn_scan/_run_blob_probe`,
   `_serialize_result`, `_make_progress_cb/_make_result_cb`, `_restore_protection_after_naked`.
5. `server/recommend.py` — `_build_recommendation`, `_recheck_contested`,
   `_recommended_blob_keys`, `KEY_HOST_LABELS`, `_BLOB_PRIORITY/_BLOB_STOPLIST`.
6. `server/updater_flow.py` — `_run_update_worker`.
7. `server/list_actions.py` — `_plan_cdn_action`, `_read_lines/_read_networks/_clean_list_text`,
   `_resolve_many` (или перевести на `core.list_health.read_entries`, см. §3.5).

**Порядок:** (1) http_app+роутер-таблицы (механическая работа, максимальный
эффект для понимания), (2) tester_flow+recommend, (3) list_actions, (4) updater_flow.

**Риски (замороженные сборки, PyInstaller):**
- PyInstaller `Analysis([main.py])` следует импортам — новые модули попадут в
  exe автоматически; `Zapret2GUI.spec` списков модулей не содержит
  (только `hiddenimports=NIQ_HIDDEN` для niquests) — **риск сборки низкий**.
- `build_portable.py` копирует каталоги целиком (`COPY_DIRS` включает `core`,`server`,
  `build_portable.py:34`) → новые файлы внутри пакетов копируются сами; `build_lite.py`
  Python-код вообще не шипит, но **импортирует** `core.launcher.build_args_from_preset`
  и `core.updater.write_manifest` (`build_lite.py:18-19, 218-219, 269`) — сохранять
  публичные сигнатуры этих функций.
- Циклы: держать DAG `http_app → api_* → app_state → core`; хендлеры не должны
  импортировать друг друга, общие утилиты — только вниз.
- Глобальные локи: `_tester_lock` и `_tester_state.lock` используются и в воркерах,
  и в хендлерах — при распиле передавать их явно через `app_state`, не размножать.
- Проверка: `python -m py_compile` + smoke-запуск `tools/ui_dump_server.py`
  (поднимает сервер локально, без службы) + `GET /api/status|config|profiles`.
  Полный тестер НЕ запускать (перезапускает живую службу).

### 2.2 frontend/js/app.js — 4394 LOC, 462 функции

| Объект | Строки | Размер (строк) |
|---|---|---|
| `TesterPage` | 2802-4136 | **1341** |
| `MainPage` | 568-1386 | 819 |
| `ListsPage` | 1897-2369 | 473 |
| `CdnStab` | 2370-2694 | 325 |
| `GamesPage` | 1508-1830 | 323 |
| `App` (роутер + апдейт + bootstrap) | 250-567 | 318 |
| `DiagnosticsPage` | 1387-1507 | 121 |
| `Status` (чип + поллинг) | 142-246 | 105 |
| `AsnPage` | 2695-2801 | 107 |
| `Activity`, `Popover`, `Modal`, `Confirm`, `AppInfo` | 4143-4394 | ~280 |

Внутри `TesterPage` фактически 4 страницы: прогон теста (3199-3392, 3617-3640),
таблица стратегий (2830-3053), **probe-анализ процесса** (3757-4135, ~380 строк —
это отдельная вкладка `probe`!), форма сбора отчёта (3640-3720).

**Предложение:** разрезать на ES-модули (или 5-6 файлов, собираемых конкатенацией):
`utils.js` (`frontendLog:52`, `apiGet/apiPost:89-104`, `escapeHtml/formatTime/rateClass/showToast`),
`status.js` (Status+App), `pages/main.js`, `pages/tester.js` (прогон+таблица),
`pages/probe.js` (probe+collect), `pages/lists.js` (+contested), `pages/cdn_games_asn_diag.js`,
`ui.js` (Popover/Modal/Confirm/Activity). Границы: страницы общаются только через
`App`-роутер, `Status`, `apiGet/apiPost` и DOM-события — уже так и есть.

**Риски:** 1) `server.py:1725-1736` делает cache-buster заменой подстроки
`"js/app.js"` в index.html — **при разбивке на несколько файлов этот механизм
тихо перестанет бить кэш** (нужно перенести версионирование на все `*.js`/`*.css`
или отдавать `no-store`). 2) PyInstaller: frontend — data-dir, риск сборки низкий.
3) `index.html` (1099 строк) содержит разметку всех 9 страниц — синхронные правки.
Проверка: `tools/ui_dump.mjs` (Playwright-дамп, 16 функций) + `tools/_ui_shots.py`.

### 2.3 core/tester.py — 1655 LOC, 52 функции, 6 классов

Слои внутри:
- **Пробы:** `_ping_test:491`, `_curl_attempt:509`, `_curl_test:528`, `_quic_h3_probe:582`,
  `_tcp1620_test_curl:722`, ASN-проба `_probe_once:1276` (вложена в `asn_scan`).
- **Оркестрация:** `_setup_profile:858`, `test_profile:948`, `scan_cdn_recommendations:1028`
  (census: 157 строк), `probe_blobs:1192`, `asn_scan:1227`, `_verify_with_desync:1351`,
  `_verify_with_ipset:1391`, `_test_baseline:1435`, `run_naked_baseline:1532`.
- **Скоринг:** `_net_stats:773`, `_build_result:924`, `collect_sanity_info:1560`.
- **Процесс-обвязка winws2:** `_ensure_winws2_dead:327`, `_any_winws*_running:344/359`,
  `_kill_never_hang:438`, `_wait_windivert_free:373`, `_kill_managed:382`.
- **Сеть/TTL:** `_probe_provider_ttl:802`, `_resolve_ips:287`, `_ipset_networks:265`.

**Предложение:** `core/tester_probes.py` (curl/quic/ping/tcp1620), `core/tester_proc.py`
(winws2 lifecycle + tasklist/taskkill), `core/tester_scoring.py` (`_net_stats`,
`_build_result` + списки статусов из §3.3). `Zapret2Tester` остаётся тонким
оркестратором (test_profile/scan/verify/baselines), приватные методы-обёртки
можно сохранить как делегаты, чтобы не трогать вызовы из server.py (`tester._ensure_winws2_dead`
зовётся из server.py:1411/1023/1057/1069 — «public-private» протечка, §4).

### 2.4 core/launcher.py — 696 LOC, 13 функций, из них `build_args_from_preset` 390 строк

`build_args_from_preset:115-505` — конвейер: чтение пресета → подстановка
`@lists/@lua/@blobs/@windivert` и `%GameFilter%` (212-222) → swapper TLS-блоба
(231-254) → переписывание voice-udplen блока (260-282) → merge `--lua-init=`
(287-297) → инжект user-списков с сегментацией по `--new` (308-345) → GameFilter
доборные сегменты (346-376) → voice-сегмент (377-394) → пул игровых UDP-правил
(395-447) → дублирование ipset-include блоков (448-477) → discord-alt nodrop
(478-496) → debug (497-505).

**Предложение:** `core/preset_parse.py` (txt → плоские токены + подстановки) и
`core/args_transforms.py` (каждый постпроцесс — отдельная чистая функция
`tokens -> tokens`, 10-12 штук, порядок фиксирован явным списком). `launcher.py`
оставляет только launch/write_run_bat/validate (506-696).

**Риски:** порядок трансформаций критичен и уже «прошит» комментариями
(например user-lists инжектятся ПОСЛЕ merge `--lua-init=`, а игровой пул — после
fake-blob swap). Любой распил обязан сохранить порядок; `build_lite.py:225-232`
и `build_portable.py` вызывают `build_args_from_preset` — сигнатуру не менять.
Проверка: diff выходных args на всех 11 release-пресетах до/после (скрипт можно
написать локально — вызов функции безопасен, движок не стартует).

### 2.5 core/diagnostics.py — 814 LOC, 24 функции

`run_diagnostics:657` (139 строк) — последовательность `_add(...)`; проверки —
в отдельные `_check_*` уже разбиты. `classify_block:359` (84) — самодостаточный.
**Вердикт: пилить НЕ первым** — структура приемлемая, дублирования внутри почти нет.
Мелкий шаг: вынести `_NET_CHECKS:38-43` и `_QUIC_QUIRK_HOSTS:53` в core-константы
общего назначения (см. §3.4); `format_report_text:798-814` (16 строк) можно
перенести в `diagnostics_report.py` — но это косметика, не приоритет.

### 2.6 Приоритеты распила

1. **server.py: транспорт + роут-таблицы** (понимаемость ↑↑, риск низкий).
2. **app.js: разбивка на модули** (понимаемость ↑↑, риск средний — cache-buster!).
3. **server.py: `_run_tester_action` и recommendation** (риск средний — общий state).
4. **launcher: parse/transforms** (риск средний — порядок).
5. **tester: probes/proc/scoring** (риск средний).
6. diagnostics — не трогать, кроме мелких констант.

---

## 3. Дубли и близкие дубли

### 3.1 curl-обёртки (сколько реализаций и что с ними делать)

**Product-код (3 файла, 7 независимых сайтов):**

| # | Место | Особенности |
|---|---|---|
| 1 | `core/tester.py:509` `_curl_attempt` | HEAD→GET фолбэк, `BROWSER_HEADERS`, `-m min(timeout,6)`, `--connect-timeout 2`, outer `timeout+5`, `%{http_code}` |
| 2 | `core/tester.py:722` `_tcp1620_test_curl` | POST `--data-binary @file`, `%{http_code} %{size_upload}`, `--no-sessionid --no-keepalive`, outer `timeout+5` |
| 3 | `core/tester.py:1281` ASN `_probe_once` | `--resolve sni:443:ip`, `-k`, `-m 10`, outer 15, upload-классификация |
| 4 | `core/diagnostics.py:94` `_curl_code` | минимальный, без connect-timeout, outer `timeout+3` (default 6) |
| 5 | `core/diagnostics.py:621` `_check_dns_spoof_servers` | curl к `dns.google` + `nslookup`-батарея |
| 6 | `server/server.py:2140` `_handle_games_check._probe` | `-m 8`, outer 12, только код |
| 7 | `server/server.py:2418` `_handle_contested_check` | `-m 10`, outer 15, только код |

Общее у 1-7: `subprocess.run(["curl.exe","-4","-s",...])`, `encoding="oem"`,
`CREATE_NO_WINDOW`, `-o NUL -w %{http_code}`, ручной парсинг `stdout`.
Различия: заголовки, connect-timeout, величина/формула outer-таймаута.

**Dev-tools:** `tools/quic_probe.py:63` (DoH), `upload_probe.py:47`, `tls_ver_probe.py:36`,
`pkt_discord.py:104`, `pkt_both.py:138`, `pkt_verify.py:211`, `pkt_s3.py:43`,
`run_preset.py:37`, `_measure_cold.py:126`, `_measure_wake.py:48` + 2 gitignored `_test_*`.

**Вердикт:** вынести в product **один** helper — `core/probe_http.py::curl_code(url, *,
timeout, headers=None, method="GET", data_file=None, extra_args=())  -> (code|None, stderr, elapsed_ms)`, и перевести на него сайты 4-7 (сайты 1-3 — отдельные
контракты, но внутренности `_curl_attempt` уже почти тот helper). tools НЕ трогать:
у них свои контракты (стенды, argparse, печать) и они не шипятся; унификация
tools↔product даст хрупкость без выгоды для пользователя.

### 3.2 QUIC/H3: `tester._quic_h3_probe` vs `tools/quic_probe.py`

- `core/tester.py:582-629`: forced H3 (`disable_http1/2`, `quic_cache_layer.add_domain`),
  `trust_env=False:605`, wall-deadline `H3_WALL_DEADLINE=12.0` (стр. 55), lib-timeout `(4,8)`,
  результат `(ok, detail)`; НЕТ DoH-фолбэка и НЕТ skip воркер-пинов.
- `tools/quic_probe.py:93-148`: тот же контракт, но `WALL_DEADLINE=15.0` (стр. 43),
  `(4,10)` (стр. 111), skip `WORKER_IPS={193.233.112.68,.67}` (стр. 42,98),
  DoH-патч при NameResolution (61-90,143), печать H3/NOT-H3/TIMEOUT/FAIL.

Расхождения осмысленны (инструмент точнее, тестер быстрее и не патчит DNS).
**Стоит шарить** только ядро пробы: `core/probe_h3.py::probe_h3(domain, *, deadline, connect_read_timeout, timeout_total) -> H3Result(ok, http_version, status, error, wall_ms)`.
tool оставляет DoH/пины/печать, тестер — свой deadline. **Приоритет низкий-средний:**
сейчас оба места свежие и живьём проверены (REVIEW_REPORT 13.10); любое шаринг-изменение
требует живого ре-теста на `i.ytimg.com` (без сети/без niquests — только статика).
Отдельно: `tools/quic_probe.py` — единственный, кто глушит DNS-спуф через DoH;
в тестере это **осознанно** не сделано (REVIEW_MAP §8 приложено) — не «баг», но
расхождение поведения задокументировать в коде helper'а.

### 3.3 Статусы/строки

Подсчёт строковых литералов статусов (мой регексп по кавычкам, все значения
`OK/OK_BLOCKED/BLOCKED/TIMEOUT/FAIL/ERROR/QUIC/QUIC_OK/QUIC_UNKNOWN/H3_NONE/
TCP16_20/DPI_DROP/DETECTED/SYN DROP/TCP RST/TLS RST/N/A/UNSUP/LIKELY_BLOCKED/UNSUPPORTED`):

| Файл | Всего | Разбивка (топ) |
|---|---|---|
| `core/tester.py` | **77** | OK 23, ERROR 15, TIMEOUT 9, BLOCKED 8, SYN DROP 6, TCP16_20 5, TCP RST/TLS RST 2+2, QUIC 2, H3_NONE 1, DETECTED 1, FAIL 3 |
| `server/server.py` | **14** | OK 9, QUIC 2, QUIC_OK/QUIC_UNKNOWN/N-A по 1 |
| `frontend/js/app.js` | **33** | OK 6, QUIC 5, QUIC_OK 3, DETECTED 2, SYN DROP 2, OK_BLOCKED 2, TIMEOUT 2, BLOCKED 2, FAIL 2, H3_NONE 2, TCP16_20 1, DPI_DROP 1, TCP RST/TLS RST 1+1, QUIC_UNKNOWN 1 |
| `tools/*` | 22 | upload/tls/quic-пробы (свои UNSUP/LIKELY_BLOCKED) |

Ключевые «реестры» статусов, живущие отдельно:
- ok/fail-множества: `tester.py:927-928` (`_build_result`), `tester.py:784-787` (`_net_stats`),
  `tester.py:1485-1486` (`_test_baseline` — **копия** `_build_result`).
- «не пробито»: `server.py:810-815` (исключения OK/QUIC/quirk/control).
- финальные ключи хостов: `server.py:906-917` (QUIC→QUIC_OK/QUIC_UNKNOWN).
- JS: `app.js:2950` (OK/OK_BLOCKED), `2986-2996` (классы строк), `3008-3013` (yt-ячейка),
  `3365-3373` (`statusOf` — локальная функция внутри `_fillTable`), `3498-3510` (QUIC_OK/QUIC_UNKNOWN).
- **`OK_BLOCKED` встречается только в JS** (`app.js:2950`, `3368`) — ни один Python-код
  его не выдаёт (проверено поиском по всем .py) → мёртвая ветка (гипотеза: наследие
  ранних сборок). Удалить или подтвердить контракт.

**Предложение:** `core/status.py`: класс-константы (OK="OK"…, не Enum со str-значениями,
чтобы не менять провод), множества `FAIL_STATUSES`, `NEUTRAL_STATUSES`, и единственная
функция `net_category(status, domain)`. В JS — словарь `STATUS_META = {OK:{cls:'hrow-ok',...}, ...}`
и убрать `statusOf`/локальные проверки. Тесты: перебор всех статусов из `core/status.py`
в node-скрипте против словаря (можно сделать чистым node, без сервера).

### 3.4 control/rated/quirk-семантика

- Источник истины: `core/tester.py:37-76` (`RATED_HOSTS`, `QUIC_QUIRK_DOMAINS`, `CONTROL_HOSTS/DOMAINS`, `_is_control_alias`).
- `server.py:470-475` (`_make_result_cb`): `rated` — через `_is_control_alias`, а
  `control` — **инлайн-копия** той же логики (`startswith("www.") and r.domain[4:] in CONTROL_DOMAINS`).
- `server.py:810-815` (`_build_recommendation`): третья инлайн-копия для «blocked».
- `server.py:941`: `quirk_skip` — ссылка на QUIC_QUIRK_DOMAINS (правильно, «единый источник» после фикса P2-3).
- `app.js:15-18` `QUIRK_HOSTS` — ручная копия `QUIC_QUIRK_DOMAINS`; `app.js:2958`
  `isRated` — фолбэк-копия rated-семантики, если payload не содержит `rated`.
- `core/diagnostics.py:53` `_QUIC_QUIRK_HOSTS = set(QUIC_QUIRK_DOMAINS) | {"www.google.com"}`
  — уже «единый источник», но `www.google.com` добавляется вторым списком; при
  изменении `CONTROL_HOSTS` легко забыть про diagnostics.

**Предложение:** заменить инлайн-копии в server.py на `_is_control_alias` + добавить
в `core/tester.py` функции `is_control(domain)`; JS-списки отдавать в `/api/app-info`
(один источник) вместо хардкода. Приоритет низкий (однажды уже расходилось — P2-3 в
REVIEW_REPORT 13.10).

### 3.5 hosts/списки: парсеры и пути

- `hosts.txt` **нигде не парсится кодом**: только копируется сборками
  (`build_lite.py:264`, `build_portable.py:121`, `build.py:62`), байт-стабилен по
  `.gitattributes` (`hosts.txt -text`). Дублирования нет; это data-артефакт (пины),
  не список обхода.
- **Дубли-парсеры list-файлов (5+ реализаций одного формата):**

| Место | Кодировка | Комментарии | Lower |
|---|---|---|---|
| `core/list_health.py:45 read_entries` | utf-8-sig | срез `#`, пустые | да |
| `server/server.py:559 _read_lines` | utf-8-sig + `_clean_list_text` (BOM+ZWSP) | `#` только в `_read_networks:573` | нет |
| `server/server.py:1855-1870 _handle_bundled_domains` | utf-8 (без -sig, errors=replace) | да | да |
| `server/server.py:2358-2364 _include_user_domains` | utf-8 (без -sig) | **нет** — `# comment` попадёт как домен | да |
| `core/tester.py:1632-1646 collect_sanity_info` | utf-8-sig | `#` и `//` | да |
| `core/launcher.py:168-189` «has_entry» (ipset-include/exclude) | utf-8-sig | да | нет |

- `ipset-all.txt.gz` — отдельный ридер `tester._ipset_networks:265` (gzip) — это
  другой формат, дублем не считается.
- `games.py` — JSON-слой (`load_games:132`, `enabled_domains:230`), свой; дублей нет.
- `updater.is_user_file:69` — классификатор путей (не парсер), корректно централизован.
- `write_manifest:546` — свой обход репо, пересекается с `is_user_file` (по делу).

**Предложение:** оставить `list_health.read_entries` единственным ридером (+параметры
`strip_comments`, `clean_bom`), заменить `_read_lines`/`_handle_bundled_domains`/
`_include_user_domains`/sanity-парсер на него. `_include_user_domains` дополнительно
рискует «съесть» комментарий — это мелкий, но реальный баг-риск (гипотеза о
проявлении: домен `#something` уйдёт в сравнение, ложных срабатываний пока не видно).
`_clean_list_text` (ZWSP) втянуть в read_entries как опцию.

### 3.6 Таймауты: сколько независимых констант/подходов

Замеры (значения и места):
- `tester.timeout=8` (init `tester.py:246`), масштабируется RTT в `_setup_profile:906-912`
  (`max(2.0, min(original, rtt*3/1000))`); curl `-m min(int(timeout),6)` (531),
  `--connect-timeout 2` (516), outer `timeout+5` (522).
- `H3_WALL_DEADLINE=12.0` (`tester.py:55`), lib `(4,8)` (607);
  tool: `WALL_DEADLINE=15.0`, `(4,10)` (`quic_probe.py:43,111`).
- `WINDIVERT_CLEANUP_DELAY=0.5` (`tester.py:176`), `_wait_windivert_free` = ×4 (373).
- TCP1620: `-m min(6)`, outer `timeout+5` (731-735).
- ASN: `-m 10`, connect 3, outer 15, повтор через `sleep(1.2)` (1281-1288, 1266-1268).
- diagnostics: `-m 6`, outer `+3` (`94-102`); DNS-spoof `-m 8`, outer 12, nslookup 8 (621-635).
- server: games `-m 8` outer 12 (2140-2142); contested `-m 10` outer 15 (2418-2421).
- прочее: `run_sc` 15 (`utils.py:122`), validate_args 10 (`launcher.py:29`),
  tasklist 3-6, tracert 12-14, tracert collector ≤12, ping `timeout+2`,
  pktmon-wait 3.0 (`process_probe.py:196`), PS-вызовы 25 (`process_probe.py:33`),
  updater download 300 (`updater.py:171`), service `_STATUS_TTL=10` (`service_manager.py:40`),
  `_UPDATE_CHECK_TTL=6*3600` (`server.py:167`).

**Разъезжается:** одна и та же по смыслу HTTP-проба использует -m 6/8/10 и outer
`+3/+5/фикс`; трассировка 12 vs 14; времена «прогрева» (1.5с `_setup_profile:889`,
0.8с blob `1209`, 1.0с update `server.py:263`, 0.5с wait `launcher.py:598`) —
разбросаны по файлам без имени. **Предложение:** `core/timeouts.py`: FAST=3, HTTP=6,
SLOW=10, WALL_PAD=5, SETTLE_WINWS2=1.5, SETTLE_BLOB=0.8 и таблица «уровень→(curl_m,
outer_pad, connect)». Не менять значения в одном рефакторинге — сначала только
имена/ссылки, потом (отдельно) редкие юстировки.

### 3.7 Process-обвязка (sc.exe/tasklist/taskkill)

- **tasklist-обёрток — 9:**
  `utils.winws2_running:133` (посимвольно, ловит «No tasks»),
  `zapret_controller.get_running_pid:124` (CSV, кэш 1с),
  `tester._any_winws_running:344`, `tester._any_winws2_running:359`,
  `tester._process_exists:425`, `server._scan_winws_exe:738` (CSV, winws.exe),
  `diagnostics._pid_of:75` (CSV, любой образ), `conflict_scan._running_images:66` (все образы),
  `launcher._wait_winws2_alive:602` (поллинг по имени).
- **taskkill путей — 5+:** `service_manager._taskkill_winws2:60`,
  `tester._kill_never_hang:438` (taskkill→wmic→powershell), `tester._kill_managed:382`,
  `server._kill_never_hang:525` (обёртка над `_run_with_timeout_quiet`),
  `zapret_controller.stop:98`, `updater` (6 упоминаний taskkill в apply/backup).
- **sc.exe:** единая точка `utils.run_sc:116` (ок); плюс `service_manager._sc_run_bat:166`
  (bat-транспорт), `service_manager._win32_advapi:209` (SCM API), `conflict_scan` (sc query),
  `server._zapret1_installed:779`. Это осознанные три транспорта — не дубли.
- Реестр: `utils` (15), `service_manager` (4), `tcp_timestamps` (4) — три прямых
  ридера winreg; `service_manager._read_stored_binpath:112` и `utils.windivert_service_state:162`
  дублируют открытие `SYSTEM\CurrentControlSet\Services\<name>` (гипотеза: можно шарить
  один `read_service_value(name, value)`).

**Предложение:** `core/proc.py`: `image_pids(exe_name) -> list[int]` (CSV-парсер один раз),
`image_running(name)`, `kill_image(name, timeout)`, `kill_pid(pid)`. Перевести на него
utils/zapret_controller/tester/server/diagnostics (conflict_scan и launcher — по желанию).
Приоритет средний: 9 мест — это не только LOC, но и разные edge-case'ы локалей
(«No tasks» vs пустой stdout) — расхождения ловятся именно здесь.

---

## 4. Инкапсуляция и OOP-практика

### 4.1 Глобальное состояние

- server.py: 11 модульных глобалов (`_root_dir…_server` 47-58), `_tester_state:121`,
  `_diag_state:56` (сырой dict), `_updater_state:170` (сырой dict), кэши
  `_update_check_cache:165`, `_zapret1_installed_cache:758`, `_process_probe:124`.
  `TesterState` — класс с lock (хорошо), но доступ к нему из 56 хендлеров напрямую
  без владельца; `_diag_state/_updater_state` — dict'ы с взаимно-договорными ключами.
- app.js: синглтоны `Status/App/TesterPage.state/PROFILES:20/_gameContext` — нормальный
  vanilla-JS паттерн, но `TesterPage.state` смешивает состояние теста, probe и формы.
- core: `service_manager` кэши (`_status_cache_*:41-44`) — ок; `tester._has_niquests:244`
  — кэш на классе (потокобезопасность: запись без лока — уже отмечено в REVIEW_MAP,
  оставлено как принятое).
- Приватные методы как публичный API: `tester._ensure_winws2_dead()` вызывается из
  server.py (1411, 1023, 1057, 1069) и `tester._run_domain_tests` из `_recheck_contested:1024,1062`;
  `tester.is_running` — публичный (норм). При распиле tester — сделать shim-методы.

**Предложение:** `_updater_state` и `_diag_state` → dataclass (`UpdaterState`, `DiagState`)
с локом внутри; в server-роутерах не читать глобалы напрямую (только через app_state).
Приоритет средний (прямая связь с §2.1).

### 4.2 Функции-простыни

`_run_tester_action` 399 (`server.py:1168-1567`), `build_args_from_preset` 390
(`launcher.py:115-505` — но это конвейер, он «прост» внутри, хотя и длинный),
`scan_cdn_recommendations` 157 (`tester.py:1028`), `_build_recommendation` 150,
`run_diagnostics` 139, `renderProbe` 122 (`app.js:3994`), `_check_net` 113
(`diagnostics.py:246`), `collect_sanity_info` 91, `_probe_once` 75.
`_run_tester_action` — единственный true-God: 5 независимых веток действий +
сборка custom-стратегии (1359-1458, ~100 строк inline) + smoke-запуск winws2
(1384-1419) — этот кусок логичнее живет в `core/strategy_builder` или отдельном
`server/custom_build.py`.

### 4.3 Магические числа/строки (значимые)

`12.0` (H3 deadline), `3.0` (QUIC quirk timeout `tester.py:535`), `28*1024`
(ASN ok-порог `1297`), `700` (размер блоба `server.py:989`), `64*1024` (TCP1620),
`1.5` (WinDivert settle `tester.py:889`), `0.8` (blob settle `1209`),
порты голоса `"19294-19344,50000-50100"` (launcher 271, 382, 385, 390 — 4 копии),
`1024-65535` (launcher 349,352,371), `"zapret2"` (service name, 1 место — ок),
пути `/api/...` (двусторонние строки), `"default"/"custom"/"auto"` (профили в
server/tester/launcher — не константы), `"quic_google"/"google_tls"/"alt_tls"`
(имена блобов в launcher 278,361,368,376,409,417,441 и assets).
**Предложение:** ports голоса и gamefilter-диапазоны — в `core/launcher.py` константы
(DISCORD_VOICE_PORTS, HIGH_PORTS); имена блобов — в `core/blobs.py` (или constants в
launcher); статусы — §3.3. Профильные имена «default/custom» — в `core/config.py`
уже есть `DEFAULT_PROFILE`, но `"custom"` используется строкой в 5+ местах
(server 1279-1286, strategy_builder, updater USER_PRESET_IGNORE) — добавить `CUSTOM_PROFILE`.

### 4.4 `except Exception` — 112 (census); значимые 12 из 41 в server.py

| # | Место | Оценка |
|---|---|---|
| 1 | `server.py:314` (`_run_update_worker`) | широкий, но это граница воркера с UI-ошибкой — допустимо, есть лог |
| 2 | `server.py:1199` (`pause_recovery`) | оправдан (best-effort), есть `_ui_debug` |
| 3 | `server.py:1417-1419` (custom smoke) | **широкий маскирует баги**: любое исключение → «smoke не удался»; сузить до (OSError, subprocess.SubprocessError) |
| 4 | `server.py:2145` (`games _probe`) | ожидаемо (curl), но молча → `code="000"`; есть смысл log |
| 5 | `server.py:2435/2448/2463` (list_health вызовы) | приемлемо (конвертят в error-JSON) |
| 6 | `server.py:2529/2568/2581` (`current_strategy` присвоение) | безобидно, но 3 копии try/except вокруг одного присвоения — свернуть |
| 7 | `server.py:706` (`_restore_protection_after_naked`) | best-effort, возвращает текст — ок |
| 8 | `service_manager.py:230/255` (ctypes-обвязка) | оправдано (архитектурно разные пути к SCM) |
| 9 | `diagnostics.py:507,545` (DoH urlopen) | ожидаемо; фолбэк на "skip" |
| 10 | `tester.py:1024` (`_ensure_winws2_dead` при abort) | оправдано (в finally-подобном пути) |
| 11 | `main.py:462-469` (`on_closing`) | оправдано (shutdown) |
| 12 | `main.py:82-86` (MOTW) | оправдано (диагностика не роняет старт) |

Остальные 30 в server.py — тонкие обёртки вокруг `_send_json`/dict-полей
(«глотают, чтобы не 500»). Массово сужать не нужно; правило: широкий `except`
допустим только там, где есть либо лог с контекстом, либо пользовательское
сообщение; три места (3,4,6) стоит поправить при распиле.

### 4.5 Где просится dataclass/enum/типизация

- Уже хорошо: `TestResult/ProfileTestResult/CdnScanVerdict/CdnScanResult` (tester),
  `AppConfig` (config), `ZapretStatus` (controller), `ConflictReport` (conflict_scan),
  `Check` (diagnostics), `AnalyzerEvent` (full_analyzer).
- Просится: `UpdaterState`/`DiagState` (server), `H3Result` (см. §3.2), статус-enum
  (не-literal), тип роут-таблицы `dict[str, Callable[[ZapretHandler, dict], None]]`,
  TS/JSDoc для контрактов payload (`rated/control/cdn_provider/quirk_skip/quic`-статусы).
- Возвраты `tuple[bool, str]` (много API) — терпимо (это `(ok, message)` конвенция),
  менять не обязательно.

---

## 5. Anti-список: что не трогать

1. **`lua/*` (кроме `zapret-custom.lua`)** — вендорный/апстрим-код
   (bol-van/zapret2). Проверка против локальных исходников v1.0.2:
   `zapret-obfs.lua` и `zapret-pcap.lua` — **побайтово совпадают** с upstream;
   `zapret-lib.lua` (+21/-15), `zapret-tests.lua` (+14/-9), `zapret-antidpi.lua` (1),
   `zapret-auto.lua` (1) — локальные отличия (похоже, из более нового дропа:
   в рантайме winws2 v1.0.5, а локальные исходники v1.0.2 — **гипотеза**);
   `zapret-custom.lua` в upstream отсутствует — **наш**. Не рефакторить, не
   «чистить»; любые правки только синхронизацией с соответствующим upstream tag.
2. **`tools/*` — standalone dev-инструменты** (`quic_probe/upload_probe/tls_ver_probe/
   pkt_*/voice_*/ipset_*`): свой CLI, своя печать, живьём проверены. Дублирование
   curl там — осознанная изоляция; не тащить их на product-хелперы.
3. **Осознанные трейд-оффы (не баги):** последовательный прогон профилей
   (внутри — ThreadPool по доменам), перезапуск службы для применения списков,
   байтовые/`sc`-bat и Win32-API пути установки службы (`service_manager._sc_run_bat`,
   `_win32_create_service`), daemon-хвост H3-пробы и `H3_WALL_DEADLINE=12`,
   `_tcp1620` «полный upload без ответа = OK», `upload_probe` LIKELY_BLOCKED —
   разные инструменты, разные контракты (REVIEW_MAP §8).
4. **`hosts.txt`** — data-артефакт пинов (копируется сборками вручную; в рантайме
   не читается). Не переносить в код, не парсить.
5. **`Windows build/*.zip`, `release.json(.sig)`, `blobs/*`, `bin/*`, `windivert/*`** —
   релизные/бинарные артефакты и сторонний движок (winws2/WinDivert/cygwin).
6. **Gitignored локальные копии/харнессы:** `portable/` (полная сборка, включает
   `portable/app/core|server` — **вторая копия кода, не аудировать, не «править»**),
   `lite/`, `_test_*.py`, `/_*.py` (локальные smoke-харнессы), `presets/test-|exp-|cand-`.
7. **`AI_DOCS/*`** — доки (можно читать контекст; не аудировать структуру — по заданию).
8. **Уже исправленное (не переоткрывать):** REVIEW_REPORT 2026-10-13 — P1-1 (spec
   fail-loud без niquests), P2-1 (`trust_env=False` — проверил, стоит в
   `tester.py:605` и `quic_probe.py:108`), P2-2/P3-1 (H3_NONE нейтрален, QUIC_UNKNOWN
   чип), P2-3 (rated c www-алиасами), P2-4 (tls_ver rc=35).
9. **Свежая инфраструктура:** `.gitattributes` (LF-политика + `hosts.txt -text`) —
   не «чинить» CRLF инструментами; правки батников — только CRLF/ASCII.

---

## 6. Топ-10: вектор полировки

Severity: S1 — мешает пониманию/сопровождению сильно; S2 — заметно; S3 — косметика/риск.
Риск регрессии: R1 низкий, R2 средний, R3 высокий.

**(а) Понимаемость**

1. **S1 / R1. server.py: транспортные ~1430 строк + 56 хендлеров в одном классе.**
   Шаг: вынести `ZapretHandler`-транспорт и таблицы роутов в `server/http_app.py`,
   хендлеры — по доменам (`api_config.py`…). Проверка: py_compile + smoke `/api/status`.
   Риск: низкий (PyInstaller следует импортам; build_portable копирует каталог).
2. **S1 / R2. app.js 4394 строк.** Шаг: распил на 6-7 файлов (§2.2). Главный риск —
   cache-buster `server.py:1725-1736` (замена подстроки "js/app.js"): обновить
   механизм до распила или в том же коммите. Проверка: ui_dump.mjs.

**(б) Дробление файлов**

3. **S1 / R2. `_run_tester_action` 399 строк** (`server.py:1168`): вынести ветки
   (`test_profiles/cdn_scan/current/naked/full_analysis`) в функции; custom-сборка
   (1359-1458) и smoke (1384-1419) — отдельный `server/custom_build.py`.
   Риск: общий `_tester_state`/lock — передавать state явно.
4. **S2 / R2. `build_args_from_preset` 390 строк / 10 трансформаций** (`launcher.py:115-505`):
   `preset_parse.py` + `args_transforms.py` со стабильным порядком. Проверка: diff args
   по 11 release-пресетам (чистая функция, движок не участвует).
5. **S2 / R2. `core/tester.py`:** пробы ↔ оркестрация ↔ скоринг ↔ proc (§2.3).
   Риск: server.py зовёт приватные методы тестера — сохранить шимы.

**(в) Дубли**

6. **S2 / R1. 7 независимых curl-обёрток в product-коде** (§3.1): один
   `core/probe_http.py`; перевести 4-7 сайты (server/diagnostics), 1-3 — на общий низ.
7. **S2 / R2. 9 tasklist-обёрток / 5 taskkill-путей** (§3.7): `core/proc.py`.
   Риск: локализованные edge-case'ы — переносить с сохранением текстов парсинга.
8. **S2 / R1. 5 парсеров list-формата с расхождениями (BOM/комментарии)** (§3.5):
   всё на `list_health.read_entries`; `_include_user_domains` сейчас не отсекает `#`.
9. **S3 / R2. QUIC-проба tester vs tool** (§3.2): общий `probe_h3` только если будет
   живой ре-тест; deadline 12↔15, (4,8)↔(4,10), DoH/пины оставить в tool.
   Плюс единая таблица таймаутов (`core/timeouts.py`, §3.6) — только имена, без смены значений.

**(г) Инкапсуляция**

10. **S2 / R1. Статусы и rated/control-семантика** (§3.3/§3.4): `core/status.py` +
    JS-словарь; удалить мёртвый `OK_BLOCKED` (`app.js:2950,3368` — бэкенд его не
    выдаёт), заменить инлайн-копии `_is_control_alias` (`server.py:473-475`, `814-815`)
    на хелпер. Риск низкий: значения строк на проводе не менять.
11. **S3 / R1 (бонус).** `_updater_state/_diag_state` → dataclass; сузить 3 широких
    `except` (§4.4: server 1417, 2145, 2529×3).

**Рекомендованный порядок исполнения:** 8 → 6 → 1 → 3 → 2 → 4 → 5 → 7 → 10 → 9.
(Дубли-парсеры и curl дают быстрый безопасный выигрыш; server/app.js — основная
ценность по понимаемости; launcher/tester — по остаточному бюджету.)

---

## 7. Приложение: как проверять без регрессий

Разрешённые и достаточные проверки (без службы и сети-ломающих операций):

1. `python -m py_compile <изменённые файлы>` — синтаксис.
2. Граф импортов: обход DFS (как в §1.2) — «0 циклов» обязательное условие.
3. `python tools/ui_dump_server.py` — локальный UI-стенд (импортирует
   `server.server init/create_server`, службу не трогает; запускать на свободном порту).
4. Быстрые API-smoke: `GET /api/status`, `/api/config`, `/api/profiles` на стенде.
5. Точечные unit-вызовы чистых функций: `build_args_from_preset` (diff args),
   `list_health.read_entries/check_health`, `_build_recommendation` (синтетические
   `ProfileTestResult`), `status`-словари JS (node).
6. `tools/security/test_updates_security.py` — апдейтер-контур (самодостаточный).
7. Живые QUIC-ре-тесты — только если тронут §3.2, на `i.ytimg.com`, с venv из
   REVIEW_MAP; тестерный полный прогон НЕ запускать (перезапускает живую службу).

Инварианты, которые нельзя нарушать при любом рефакторинге:
- Публичные сигнатуры `core.launcher.build_args_from_preset`, `core.updater.write_manifest`,
  `validate_args` — их зовут сборочные скрипты (`build_lite.py:225-232,269`).
- Порядок трансформаций args в launcher (комментарии-инварианты в коде).
- Значения строковых статусов на HTTP-проводе (`OK/BLOCKED/TIMEOUT/.../H3_NONE/QUIC`)
  и ключей `rated/control/quirk_skip` — фронт и бэкенд меняются одним коммитом.
- `no-store` и cache-buster статики (`server.py:1628,1725-1736`) — при распиле фронта
  обновить механизм.
- `_STATE`-локи: `service_manager._op_lock` (RLock), `list_health._LIST_LOCK`,
  `_tester_state.lock`, `_diag_lock` — не разрывать инварианты «одна мутация — один лок».

---

### Цифры-якоря (для сверки)

- LOC: 34 088 (без AI_DOCS); top: app.js 4394, server.py 3030, tester.py 1655,
  app.css 1857, diagnostics.py 814, process_probe.py 712, launcher.py 696,
  service_manager.py 687, updater.py 590, games.py 541, main.py 491, list_health.py 342.
- server.py: 124 функции (40 top-level + 56 `_handle_*` + транспорт/служебные), 3 класса.
- app.js: 462 функции, 14 объектов; TesterPage 1341, MainPage 819.
- `except Exception`: 112 (server 41, service_manager 9, diagnostics 8, updater 7, main 7, tester 5).
- `subprocess.run`: 68 (census). tasklist-обёртки: 9; taskkill-пути: 5+; curl-сайты: 7 product + ~11 tools.
- Статус-литералы: 77 (tester) + 14 (server) + 33 (app.js) + 22 (tools).
- Импорт-граф: 0 циклов; core ↛ server/frontend; server → core ×17; main → server ×2.


---

## 8. Прогресс исполнения (обновлять по мере закрытия)

- ✅ **#8 (дубли-парсеры листов)** — 14.10: `list_health.read_entries` —
  единственный парсер (срез `#`, lower, BOM/ZWSP-чистка); переведены
  `server._read_lines/_read_networks/_handle_bundled_domains/
  _include_user_domains` (фикс: комментарии больше не попадают в «домены»),
  sanity-парсер тестера и `has_entry` лаунчера. Юнит-тест + golden 9/9.
- ✅ **#6 (curl → `core/probe_http.py`)** — 14.10: `CurlResult/curl_code`,
  diagnostics + server переведены (DoH-тело через body_mode; contested
  больше не падает на таймауте).
- ✅ **#7 (proc-обвязка)** — 14.10: `core/proc.py`
  (`image_pids/image_running/running_images/kill_pid/kill_image`, CSV,
  локаль-независимо, не бросает); переведены utils/zapret_controller/
  tester/server/diagnostics/conflict_scan/launcher/service_manager
  (11 мест; бонус: необработанный таймаут taskkill в службе закрыт).
- ✅ **#4 (конвейер аргументов)** — 14.10: `core/preset_parse.py` (чтение+подстановки)
  + `core/args_transforms.py` (10 чистых шагов, `PIPELINE` фиксирует порядок);
  launcher 792→468 строк, `build_args_from_preset` — тонкий оркестратор
  (сигнатура стабильна). Страховка: `tools/args_golden.py` (snapshot/compare,
  22 кейса — все пресеты × тоглы; байт-идентичность подтверждена).
- ✅ **#10 (статусы)** — 14.10: `core/status.py` (HostStatus StrEnum: 15 wire-значений,
  FAIL_STATUSES); тестер: 2 копии fail-tuple → общий набор, `_is_control_alias` →
  публичный `is_control`; server: убраны 2 инлайн-копии www-алиаса; JS: удалены
  мёртвые ветки OK_BLOCKED и DPI_DROP (Python их не выдаёт); новый `tools/status_contract.py`
  замораживает wire-множество и ловит JS-дрейф (класс OK_BLOCKED).
- 🟡 **#1 (server, В РАБОТЕ)** — Inc A2 (14.10): таблицы _GET_ROUTES (22) /
  _POST_ROUTES (40) + _dispatch вместо if/elif-цепочек. Inc B (14.10):
  server/app_state.py — единый AppContext/STATE (скаляры+кэши через STATE,
  TesterState перенесён, алиасы объектов; main.py → get_tester()).
  Смоук-стенд `tools/api_smoke.py` (12 проверок) — OK.
  Inc C-пилот (14.10): домен «служба» вынесен в `server/api_service.py` (6
  хендлеров `(ctx)->dict`), router понимает и методы, и api-функции
  (dict/ApiError); app_state добавил фабрики+`checkers_busy`; T22+api_smoke OK.
  Осталось: вынести остальные ~50 хендлеров (probe/games/
  zapret1/update/contested/lists/diag/tester/cdn/одиночки).
- ⏳ осталось: #1-продолжение (AppContext + выносы) -> #3
  (_run_tester_action) -> #5 (tester) -> #9 (QUIC/timeouts) -> #2 (app.js
  ПОСЛЕДНИМ; склейка файлов на сервере).


### Корректировка порядка и решения (советник, 14.10)

- **Порядок изменён**: #4 (конвейер аргументов) и #7 (proc) — ВПЕРЁД распилов
  server/tester (иначе один и тот же код правим дважды); **#2 (app.js) —
  ПОСЛЕДНИМ** (риск «белого экрана» при кастомном кэш-бастинге перевешивает).
  Итоговая цепочка: **[8,6] → 7 → 4 → 10 → 1 → 3 → 5 → 9 → 2**.
- **HTTP-слой (#1)**: не миксины и не голый синглтон, а **AppContext (DI)**:
  хендлеры — свободные функции `(ctx, req) -> dict | ApiError`, без
  `self._send_json`; тонкий роутер `ROUTES[(method, path)]` + один `_send_json`.
  Промежуточный шаг допустим (`req_ctx.send_json`) при доменном распиле.
- **Фронтенд (#2)**: ES-модули НЕЛЬЗЯ (глобальный скоуп/`onclick` сломаются);
  выбран путь **склейки на сервере**: мелкие файлы `ui/js/*`, единственный
  `<script src="app.<hash>.js">` (текущий кэш-бастинг не трогаем), server.py
  конкатенирует по списку. Альтернатива — `?v=`-плейсхолдеры в HTML.
- **Статусы (#10)**: `StrEnum` (`str`-наследование обязательно для json/`==`) +
  контракт-тест на точное множество значений + авто-генерация JS-констант.
