# AGENTS.md — текущая памятка (читать первой)

> Обновлено 2026-11-14. Актуальная версия — **Pre-Release 0.11**
> (опубликован, тег `Pre-Release-0.11` → `f29cdb3`). Предыдущий релиз —
> 0.10 (тег `3fd25f0`, immutable).
> ВАЖНО: черновые архивы 0.11 от 27.10 устарели (движок 1.0.6, пресеты без
> `midsld`) — релиз собирать из HEAD (1.0.7 + `pos=1,midsld`). Индекс —
> `AI_DOCS/README.md`.
>
> Здесь только текущие правила и факты. Закрытые/исторические документы
> удалены при чистке 2026-10-24; их выжимка — `ENGINEERING_NOTES.md`, полные
> оригиналы — в git-истории (`0bd6626^:AI_DOCS/archive/`).

## 0. Текущее состояние

- **Репозиторий-истина:** `Zapret-2-GUI`, ветка `main`, remote `origin`.
  Отдельная live-копия синхронизируется точечно; правки кода — в репо, затем
  синк/сборка.
- **Версия:** `core/config.py VERSION = "Pre-Release 0.11"` (опубликован
  2026-11-14, тег `Pre-Release-0.11`). В 0.11 входят DNS-профили, упрощение формы «Своя игра»,
  фиксы после 0.10, движок 1.0.7, hardening, WebView2 fallback и lite parity.
  0.10 остаётся immutable. Сборка 0.11 — только из HEAD; архивы 27.10
  (1.0.6 + пресеты без `midsld`) не публиковать.
- **Пресеты:** 11 release (`default`, `default-alt`, `auto`, `fake-only`,
  `fakedsplit`, `fake-disorder`, `fake-multidisorder`, `hostfakesplit`,
  `multisplit-pure`, `multisplit-seqovl`, `tcpmd5-fake`). Тестовые
  `exp-*`/`cand-*` удалены. Тестовый `presets/flaky.txt` в рабочем дереве
  отсутствует (не релиз, не возвращать).
- **Движок:** `bin/winws2.exe` = zapret2 **v1.0.7** (обновлён 2026-11-06;
  stock-lua lib/antidpi/auto обновлены, `zapret-custom.lua` сохранён).
  T37/T43/T44 dry-run зелёные; служба в зеркале перезапущена. 0.10 шипится с
  v1.0.5 (без QUIC-dissect фиксов 1.0.5.2+); 0.11-черновик 27.10 = 1.0.6.
- **Тесты:** `tests/` (pytest, 317 passed на 2026-11-14) + батарея:
  `compileall`, `tools/api_smoke.py`, `tools/security` (47),
  `tools/args_golden.py compare`, `tools/check_arg_file.py`,
  `tools/js_bundle_check.py`, `tools/status_contract.py`.
  Перед сдачей — минимум compile + pytest + api_smoke + args_golden + security.
- **Hardening 2026-10-24:** JSON-body/типы полей, quarantine config/games,
  безопасный report-path, atomic import настроек, service ownership и
  remove-check, operation-lock tester/diag/service/update, updater deadline/
  rollback, cancel тестера/ASN, bounded games-check, probe/frontend recovery,
  единый list-lock + sync combined, rollback service conf/binPath, bounded
  ProcessProbe.stop, non-UTF-8 списки, polling и `truncated` в проверке игр,
  WebView2 preflight + browser fallback, кэш/in-flight guard `resolve_ips`,
  path-фильтр ZapretController (temp/вторая копия не убивает чужой winws2).
- **Открытые задачи:** live-приёмка 0.11 (публикация уже выполнена); live-прогон
  тестера на 1.0.7 и живая смена DNS на разных адаптерах; проверка WebView2
  fallback на чистом Win10 без Runtime, browser fallback UX/токен в URL.
  0.11: пересобрать из HEAD и добавить видео-диагностику (P0 из
  `YOUTUBE_VIDEO_STALL_2026-11.md`); «фикс YouTube» не обещать.
  YouTube-видеоспиннер у части 0.10 — внешняя волна GGC/TLS-CH (см. тот же
  документ); ждём логи affected (DevTools Protocol/Method/Size/Remote Address,
  форма A/B).
- **Технический аудит 2026-11-14:** исправлены P0/P1 и точечные P2 (fail-closed
  validate_args, ownership operation-lock, таймауты тестера, service
  orphaned/repair/precheck, DNS-семейства, битый JSON→400, release-гейты,
  EXE-апдейт при живом обходе). Итоги и НЕисправленный бэклог —
  AI_DOCS/TECH_AUDIT_2026-11-14.md §2–§3. Fail-closed проверки в
  launcher/service/tools не ослаблять.
  `presets/flaky.txt` в рабочем дереве отсутствует и в релиз не входит.
- **Fix batch 2026-11-14:** закрыты T9/T10/T11/T12/T13/T14 (launcher,
  service journal/recovery, tester stability/probe-файлы, status/ProcessProbe,
  diagnostics/DNS/games, portable runtime-апдейт) — см. `TECH_AUDIT` §6.
  **Live-приёмка ещё не пройдена:** реальные install/remove/restart службы,
  живой portable-апдейт, живой тестер/H3/CDN, живой DNS apply/reset, Win10.
  Portable 0.10→0.11 первым хопом: **переустановка из архива** (в release notes).
- **Релиз 0.11 — опубликован (2026-11-14):** тег `Pre-Release-0.11` → `f29cdb3`,
  три архива из HEAD (движок 1.0.7), 8 pretty-ассетов, подпись
  `50DCECF29451`; `check_for_updates()` видит 0.11. Осталась live-приёмка.
  Ограничение: jsDelivr не отдаёт full exe-архив (21.5 MB > 20 MB),
  portable/lite — отдаёт; GitHub — основной источник.
  Upstream-sync 2026-11-14: данные dpi-detector/dpi-checkers актуальны
  (байт-в-байт), добавлена атрибуция; ipset-база остаётся наша, staged-база
  (27206 CIDR) ждёт A/B в catchall; итоги/бэклог —
  `AI_DOCS/UPSTREAM_SYNC_2026-11-14.md`. Чувствительные сетевые кейсы —
  только локально, вне git.

## 1. Железные правила

### Кодировки и файлы
- Текст — **UTF-8 без BOM**. Правки через Write/Edit, не через PowerShell
  5.1 (`Get-Content` = ANSI, `>` = UTF-16, `-Encoding UTF8` = BOM).
- **.bat/.cmd:** `chcp 65001 >nul` + UTF-8 без BOM + **CRLF**, либо чистый
  ASCII. LF ломает cmd.
- Исключение: `build_lite.py` пишет `test.ps1` с `utf-8-sig` намеренно.
- `.gitattributes`: LF везде; CRLF только `*.bat`/`*.cmd`/`*.ps1`;
  `hosts.txt`/`*.sig` — байт-стабильны.

### Пути и аргументы
- Основной запуск и служба — **длинные пути через `@conf`**; 8.3 — только
  аварийный bat-фолбэк. `_warn_if_bad_path` не блокирует запуск; диагностика
  «Путь установки» — warn, не fail.
- `--lua-init` — только `--lua-init=@path` (токен с `=`). Отдельный аргумент
  с путём ломает разбор winws2.
- Имя блоба не начинать с цифры (`2gis_tls` молча не шлётся).
- `--payload` обязателен: `tls_client_hello`, `http_req`, `quic_initial`,
  `discord_ip_discovery`; для unknown UDP — `:payload=all`.
- `tcp_ts` — только на fake. На multisplit запрещён (PAWS).
- `nodrop` не ставить на SNI-блоки; Discord-блоки уже в drop-режиме.

### Служба и процессы
- `zapret2` ставится как `winws2.exe` напрямую; binPath — через Win32 API
  (`CreateServiceW/ChangeServiceConfigW/DeleteService`), чтение — из реестра
  (не `sc qc` для длинных путей).
- Перед удалением/остановкой — понять, чей процесс; `winws2` гасить
  path-фильтром, не по имени вслепую.
- `Start=4`/`DeleteFlag=1` у службы WinDivert — норма (драйвер грузится
  напрямую). Битый ImagePath лечится repair, не удалением.
- После **игровых/UDP** правок нужен **переустанов службы**; правки списков
  применяются к новым подключениям без рестарта.
- Служба, установленная из **другой папки** (вторая копия GUI/lite), не
  трогается: install/start/stop/remove/repair отказывают по mismatch binPath.
- Любая установка/переустановка проверяет `install` и `start`; не сообщать
  «установлено», если обход не поднялся.

### Данные и безопасность
- `hosts` — только атомарно; лучше append. Не заменять системный hosts целиком.
- `lists/ipset-exclude.txt` — системный; пользовательский —
  `ipset-exclude-user.txt`. User-файлы не перезаписывать.
- `games.json` — user-файл: битый JSON откладывать в `.bad`, не затирать.
- Секреты/ключи не коммитить. Приватный ключ Ed25519 — вне репо.
- Не добавлять чувствительные сетевые/региональные данные в git: только
  локально, вне репозитория. Сырые расследования (raw-JSON, pcap, IP/провайдер)
  держать в gitignored `_analysis/`; в репо — только обезличенные выжимки.
- Коммит-сообщения без `@`; сообщения — по одной проблеме.

### Игры
- Встроенный Wardogs: **UDP 4192-4194**, pool AWS
  `54.115/54.228/54.216/3.218.0.0/16`; домены — авторизация/лобби.
- `enabled=false` у игры или `udp[].on=false` исключает её правило.
  Выключение всей игры убирает и **домены**; выключение только UDP-правила
  домены оставляет.
- Правила группируются по `(cutoff,repeats,wide)`; первый матч с `--ipset`
  может перекрыть wide-правило; дубли диапазонов не фатальны. Для нового
  сервера вне pool — широкое правило или его CIDR.
- `GameFilter=udp/both` имеет приоритет и заменяет game UDP rules (решение
  пользователя); при нём правила с портами ниже 1024 не применяются.
- Тестовый `flaky`: `4190-4195`, `ACTIVE_GAME_UDP`, `repeats=12`,
  `out-range -d4`; в рабочем дереве отсутствует. Не релиз, не возвращать.

### Тестер, диагностика, сеть
- «Чужой TLS-клиент» (curl) под десинком ≠ опыт браузера: QUIC-класс —
  нейтральный статус, не красный.
- `SynSent` без Established = SYN/IP-блок; fake/split не лечат. Нужен другой
  маршрут/WARP/провайдер. Тестер может быть зелёным, если он не проверяет
  тот же эндпоинт.
- `auto` (`circular`) переключает стратегию после **3 сбоев**, а не по
  таймеру. 60 с — окно сброса счётчика; `--lua-gc=60` — GC Lua. После успеха
  `nstrategy` не сбрасывается. README в этом месте исправлен.
- Discord media/stream: историческое сравнение с Zapret 1 больше не поддерживается; z2
  `default`/`default-alt`/`auto` — не подтверждены как стабильные. Чистый
  `multisplit` (auto strategy=3) — кандидат, но длительный тест не подтвердил.
  Не записывать это как «исправлено», пока нет подтверждения.
- **GGC/TLS-CH-класс (2026-11):** к локальным GGC-узлам googlevideo TCP/80/ICMP
  живы, но TLS-хендшейк блокируется для видео-SNI (проходит только whitelist-
  SNI); fake/split такой маршрут НЕ лечат — это route-class, как SYN-блок.
  Видео живо только по QUIC/h3 (его держит наш QUIC-fake); TCP-fallback к GGC
  мёртв. Не советовать «отключить QUIC»: на GGC-сетях это единственный живой
  видеопуть. Детали — `YOUTUBE_VIDEO_STALL_2026-11.md`.
- **Плеер YouTube 2026 — SABR-only:** per-format URL в player-response нет,
  медиа — POST `serverAbrStreamingUrl`; старые per-format пробы не показательны.
- **Тестер не оценивает видео:** youtube-хосты исключены из `network_rate`,
  `videoplayback`/SABR не проверяются; «зелёный тестер» ≠ видео работает.
- **`multisplit:pos=1` — no-op** в движке 1.0.5: реальный split требует ≥2
  позиций (`pos=1,midsld`, c7aecde/HEAD); учитывать при A/B.

### Обновления
- Ed25519, PUBKEY в `core/update_verify.py`, отпечаток
  `50DCECF29451`; fail-closed. Релиз подписывается офлайн-ключом.
- Апдейтер ставит только валидную подпись, сверяет sha256, применяет
  manifest, откатывает portable. Не ослаблять проверки.
- Релизные гейты (2026-11-14): sign_release.py требует все 3 архива,
  совпадение версии/тега/ключа PUBKEY/версии движка внутри архивов;
  release_publish.py сверяет VERSION/tag/манифест/подпись/sha256/size до
  публикации. Ослаблять нельзя — stale-манифест уезжал в immutable-релиз.

## 2. Архитектура

```
main.py (UAC, pywebview/WebView2, single-instance)
  -> server/server.py (loopback HTTP, token, /api/*)
     -> core/launcher.py (presets -> args, @conf, validate_args)
     -> core/tester.py / tester_probes.py
     -> core/service_manager.py, zapret_controller.py
     -> core/games.py, diagnostics.py, process_probe.py, updater.py
  -> frontend/ (HTML/CSS/JS SPA)
```

- Пресеты — текстовые, `%GameFilter%`/`@`/тогглы подставляет launcher.
- API: `server/api_*.py`, транспорт `server/server.py`; новые ручки — по
  текущим контрактам.
- Сборки: `build.py` (EXE), `build_portable.py`, `build_lite.py`
  (`lite/` генерируется, в git не хранить).
- WebView2 — только GUI-оболочка; preflight + browser fallback в `main.py`,
  остаточные проверки — `PLAN_WEBVIEW2_FALLBACK.md`.
- Параметры движка, источники данных и история экспериментов —
  `ENGINEERING_NOTES.md` (raw archive — в git-истории `0bd6626^`).

## 3. Документация

- `README.md` — пользовательский мануал.
- `AI_DOCS/PROJECT_MAP.md` — карта кода.
- `AI_DOCS/ENGINEERING_NOTES.md` — параметры, источники, история решений.
- `AI_DOCS/RELEASE_CHECKLIST.md` — выпуск.
- `AI_DOCS/STRATEGY_GUIDE.md` — методика/параметры.
- `AI_DOCS/STRATEGY_ROADMAP.md` — стратегические решения/бэклог.
- `AI_DOCS/ARG_FILE_RESEARCH_2026-10-14.md` — @conf (механизм внедрён).
- `AI_DOCS/PLAN_WEBVIEW2_FALLBACK.md` — fallback WebView2.
- `AI_DOCS/YOUTUBE_VIDEO_STALL_2026-11.md` — видео-спиннер 2026-11: GGC/TLS-CH,
  SABR-only, QUIC, что не переоткрывать и что делать в 0.11.
- `AI_DOCS/TECH_AUDIT_2026-11-14.md` — итоги тех-аудита: исправленные баги,
  бэклог P1/P2, оптимизации, применимость фич zapret2 1.0.6/1.0.7.
- `AI_DOCS/IPSETS_V3NILLA.md` — правила обновления ipset-базы (восстановлен
  из git-истории 2026-11-14), свежий coverage-diff и staged-база.
- `AI_DOCS/UPSTREAM_SYNC_2026-11-14.md` — dpi-detector/dpi-checkers/Flowseal:
  что актуально, что исправлено в ASN Checker, A/B-план ipset, лицензии.
- `AI_DOCS/RELEASE_READINESS_0.11.md` — вердикт готовности 0.11, блокеры,
  обязательная последовательность и live-чек-лист.
- `CHANGELOG.md` (корень) — пользовательский список изменений 0.11.
- `AI_DOCS/TEAM_PLAYBOOK.md` — правила использования durable-агентов: сначала
  продолжать существующего владельца домена, не спавнить fresh; контекст-кэш
  `_analysis/team/CONTEXT-PACK.md`, реестр `_analysis/team/ROSTER.md`.
- При чистке доков важные параметры/источники/решения переносить в
  `ENGINEERING_NOTES.md`; raw-оригиналы остаются в git-истории, но секреты/
  регион/IP туда заново не добавлять.

## 4. Команда и durable-агенты (обязательно для Lead)

- **Сначала `list_agents` + `_analysis/team/ROSTER.md`.** Если домен уже имеет
  владельца — продолжить его `send_message` (агент сохраняет контекст даже
  `inactive`). Fresh-спавн — только для новой предметной области; иначе это
  повторное чтение проекта, лишние токены и расхождения.
- Каждый тиммейт читает `AI_DOCS/TEAM_PLAYBOOK.md` + локальный
  `_analysis/team/CONTEXT-PACK.md`, затем ТОЛЬКО свои файлы (grep/read с
  offset/limit), а не весь проект/доки.
- `subagent_fork` — когда задача опирается на историю Lead; `spawn_teammate`
  fresh — новая область + ссылка на плейбук/кэш в промпте.
- Один домен = один владелец; параллельные агенты — только по disjoint
  `write_scopes` из shared task; коммитит только Lead.
- После каждого батча Lead обновляет CONTEXT-PACK/ROSTER и «кэш» открытых
  задач, чтобы следующий агент не перечитывал проект.