# AGENTS.md — текущая памятка (читать первой)

> Обновлено 2026-10-24. Актуальная версия — **Pre-Release 0.10**
> (тег `3fd25f0`) + коммиты после релиза. Индекс документации — `AI_DOCS/README.md`.
>
> Здесь только текущие правила и факты. Закрытые/исторические документы
> удалены при чистке 2026-10-24.

## 0. Текущее состояние

- **Репозиторий-истина:** `Documents\GitHub\Zapret-2-GUI`, ветка `main`,
  remote `origin`. Зеркало с живыми user-данными:
  `Desktop\Zapret 2 GUI\zapret2_gui`. Правки кода — в репо, затем синк/сборка.
- **Версия:** `core/config.py VERSION = "Pre-Release 0.10"`. После тега
  выпущены фиксы (включая 500 при переустановке службы, Wardogs 4192-4194,
  lite parity, 8.3-политику). Это уедет в 0.11; 0.11 ещё не выпущен.
- **Пресеты:** 11 release (`default`, `default-alt`, `auto`, `fake-only`,
  `fakedsplit`, `fake-disorder`, `fake-multidisorder`, `hostfakesplit`,
  `multisplit-pure`, `multisplit-seqovl`, `tcpmd5-fake`). Тестовые
  `exp-*`/`cand-*` удалены. В рабочем дереве есть **untracked** тестовый
  `presets/flaky.txt` (не релиз, не применять без теста).
- **Движок:** `bin/winws2.exe` = zapret2 **v1.0.6** (обновлён 2026-10-24;
  stock-lua lib/antidpi/auto обновлены, `zapret-custom.lua` сохранён).
  T37/T43/T44 dry-run зелёные; служба в зеркале перезапущена.
- **Тесты:** отдельного `tests/` в репо нет. Батарея:
  `compileall`, `tools/api_smoke.py`, `tools/security/test_updates_security.py`
  (46), `tools/args_golden.py compare`, `tools/js_bundle_check.py`,
  `tools/status_contract.py`, локальные T36/T39/T40/T41. Перед сдачей — минимум
  compile + api_smoke + args_golden + security.
- **Открытые задачи:** WebView2 fallback (`PLAN_WEBVIEW2_FALLBACK.md`),
  тест `flaky`, live-прогон после рефактора, WebView2 white-screen UX.
  CDN/ASN refresh — запаркован; ipset-база остаётся наша; чувствительные
  сетевые кейсы — только в локальном `%TEMP%\opencode`, не в git.

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
- Любая установка/переустановка проверяет `install` и `start`; не сообщать
  «установлено», если обход не поднялся.

### Данные и безопасность
- `hosts` — только атомарно; лучше append. Не заменять системный hosts целиком.
- `lists/ipset-exclude.txt` — системный; пользовательский —
  `ipset-exclude-user.txt`. User-файлы не перезаписывать.
- `games.json` — user-файл: битый JSON откладывать в `.bad`, не затирать.
- Секреты/ключи не коммитить. Приватный ключ Ed25519 — вне репо.
- Не добавлять чувствительные сетевые/региональные данные в git: только
  локальный `%TEMP%\opencode`.
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
- Тестовый `flaky` (untracked): `4190-4195`, `ACTIVE_GAME_UDP`,
  `repeats=12`, `out-range -d4`; dry-run OK. Не релиз.

### Тестер, диагностика, сеть
- «Чужой TLS-клиент» (curl) под десинком ≠ опыт браузера: QUIC-класс —
  нейтральный статус, не красный.
- `SynSent` без Established = SYN/IP-блок; fake/split не лечат. Нужен другой
  маршрут/WARP/провайдер. Тестер может быть зелёным, если он не проверяет
  тот же эндпоинт.
- `auto` (`circular`) переключает стратегию после **3 сбоев**, а не по
  таймеру. 60 с — окно сброса счётчика; `--lua-gc=60` — GC Lua. После успеха
  `nstrategy` не сбрасывается. README в этом месте исправлен.
- Discord media/stream: z1 Alt1/Alt2 на проблемной сети держат стрим; z2
  `default`/`default-alt`/`auto` — не подтверждены как стабильные. Чистый
  `multisplit` (auto strategy=3) — кандидат, но длительный тест не подтвердил.
  Не записывать это как «исправлено», пока нет подтверждения.

### Обновления
- Ed25519, PUBKEY в `core/update_verify.py`, отпечаток
  `50DCECF29451`; fail-closed. Релиз подписывается офлайн-ключом.
- Апдейтер ставит только валидную подпись, сверяет sha256, применяет
  manifest, откатывает portable. Не ослаблять проверки.

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
- WebView2 — только GUI-оболочка; fallback-план — `PLAN_WEBVIEW2_FALLBACK.md`.

## 3. Документация

- `README.md` — пользовательский мануал.
- `AI_DOCS/PROJECT_MAP.md` — карта кода.
- `AI_DOCS/RELEASE_CHECKLIST.md` — выпуск.
- `AI_DOCS/STRATEGY_GUIDE.md` — методика/параметры.
- `AI_DOCS/STRATEGY_ROADMAP.md` — стратегические решения/бэклог.
- `AI_DOCS/ARG_FILE_RESEARCH_2026-10-14.md` — @conf (механизм внедрён).
- `AI_DOCS/PLAN_WEBVIEW2_FALLBACK.md` — fallback WebView2.
