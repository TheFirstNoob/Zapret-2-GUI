# Технический аудит 2026-11-14 — итоги и бэклог

> Курируемая выжимка аудита кода (7 направлений). Сырые отчёты/доказательства —
> локально в gitignored `_analysis/tech-audit/` (в репозиторий не коммитить:
> там локальные замеры/пути). Этот документ — чтобы найденное не потерялось
> при чистке доков. Баги, помеченные «исправлено», закрыты в коммитах
> 2026-11-14.

## 1. Батарея проверок (после исправлений)

- `python -m compileall -q core server tools main.py build*.py` — OK
- `python -m pytest -q tests` — 314 passed (после fix batch 2026-11-14)
- `python -m pytest -q tools/security` — 47 passed
- `python tools/api_smoke.py` — OK (включая новый кейс «битый JSON -> 400»)
- `python tools/args_golden.py compare` — OK
- `python tools/check_arg_file.py` — OK (теперь fail-closed: отказ движка = FAIL)
- `python tools/js_bundle_check.py`, `python tools/status_contract.py` — OK
- Совместимость с движком v1.0.7: 79 dry-run кейсов (11 пресетов × GameFilter,
  матрица тогглов, `--intercept=0`) — 0 ошибок; дублей list-файлов в профиле нет;
  максимальный WinDivert-фильтр 2176 B (лимит 16K).

## 2. Исправлено (P0/P1 и точечные P2)

| # | Sev | Что было | Фикс |
|---|---|---|---|
| A | P0 | EXE-самообновление при живом обходе: копирование `bin/winws2.exe` поверх работающего → WinError 32 → GUI не стартует на каждом запуске | `main.py`: перед обновлением данных останавливает свою службу/winws2 (path-фильтр), копирует с ретраем/`.new`, возвращает службу; маркер версии не пишется при провале, GUI больше не блокируется |
| B | P1 | `validate_args` fail-open: дубль hostlist-файла/`wf_priority` и др. отказ движка (rc!=0) считался валидным | `core/launcher.py`: rc!=0 = fail (кроме «already running»), добавлены маркеры 1.0.7; так же для `--intercept=0` |
| C | P1 | `strategy_builder`: у 6/11 пресетов сегменты названы иначе → custom молча подставлял сегмент default, но подписывал «из другого пресета» | `core/strategy_builder.py`: family-матчинг по смыслу (`Discord/Google/General ... tcp/tls`), поддержка `--name`, meta-строки вычищаются |
| D | P1 | Таймаутовая политика тестера вырождалась в 2 c (RTT<666 мс), naked-база 6 c, QUIC 3 c → перекос `network_rate` (1 хост = 12.5 п.п.) | `core/tester.py`: отдельный `probe_timeout = timeouts.HTTP` (6 c) для curl/ping/TCP16-20 во всех режимах |
| E | P1 | `blob_probe` не брал глобальный operation-lock, а `end_operation` освобождал ЧУЖОЙ lock → два mutating-воркера одновременно | `server/app_state.py`: end только для владельца; `server/api_blobs.py`: begin/end + откат running при сбое старта; `server/tester_flow.py`: ровно один end в finally |
| F | P1 | Битый JSON превращался в `{}` и мутирующие ручки применяли дефолты (`/api/dns/apply` менял DNS) | `server/server.py`: 400 на битый JSON/Content-Length; фронтенд (`00_utils.js`) больше не теряет серверный текст ошибки |
| G | P1 | «Выгрузить драйвер» всегда ложно требовала перезагрузку: stuck считался по нормальному Start=4/DeleteFlag=1 | `core/service_manager.py`: stuck только по мёртвому ImagePath или неудачной выгрузке/stop |
| H | P1 | Переезд/удаление папки → служба «orphaned» блокировала всё, спасение только `sc delete` вручную | `path_status` возвращает `orphaned` (exe не существует); install/remove/repair могут сделать takeover, start даёт понятный совет «переустановить» |
| I | P1 | Внутренний `start(None)` поднимал службу по устаревшему `service_run.conf` без проверки (риск с 1.0.7) | `core/service_manager.py`: перед sc start валидирует conf через `validate_args`, иначе отказ с понятным текстом |
| J | P1 | `release_publish` не сверял артефакты/манифест: stale `release.json` 0.10 мог уехать под тегом 0.11 в immutable-релиз | `tools/release_publish.py`: fail-closed проверка VERSION/tag/manifest/подписи/sha256/size перед публикацией; `_api` терпит 204 |
| K | P1 | `check_arg_file` ложно-зелёный: при отказе движка argv и conf одинаково «FAIL» → PASS | `tools/check_arg_file.py`: ok только при rc=0 и «verified»; ретрай на 0xC0000142 |
| L | P1 | `sign_release` подписывал неполный набор, не сверял ключ с PUBKEY, не проверял версию/движок внутри архивов | `tools/security/sign_release.py`: нужны все 3 архива, версия/tag согласованы, ключ = PUBKEY, VERSION внутри (portable — update_manifest), движок = версии в репо |
| M | P1 | DNS-применение сравнивало IPv4+IPv6 с IPv4-профилем → ложное «не применилось» + откат | `core/dns_manager.py`: сравнение только по семействам профиля |
| N | P1 | Проверка обновлений показывала баннер на draft-версию из main (0.11), когда релиза нет | `core/updates.py`: доступность считается по опубликованному `release.json`; fallback на VERSION, если манифест недоступен |
| O | P2 | Probe-файлы CDN-скана писались в живые `lists/`/`presets/` (могли уехать в релиз/диагностику) | частично: не исправлено в этом коммите — вынесено в бэклог (§3, #2) |
| P | P2 | `conflict_scan` не видел запущенные службы: `sc query ... state= active` → rc=87 | `core/conflict_scan.py`: `state= all` + разбор RUNNING |
| Q | P2 | В support-ZIP не хватало `games.json`, stderr движка и `@conf` службы | `core/collector.py`: добавлены games.json, winws2_last_stderr.log, run.conf, service_run.conf |
| R | P2 | Потеря причины «движок не стартует» (engine_broken): в UI только список профилей | `server/tester_flow.py`: в сообщение прокидывается первый текст ошибки |

## 3. Бэклог аудита (закрыт fix batch 2026-11-14, live-приёмка — §6)

> Пункты 1–7 и 9 закрыты в коммитах 2026-11-14 (см. §6); текст оставлен
> как история находки. Пункт 8 — частично (PUBKEY-тест добавлен, CI
> crash-recovery не воспроизводился).

1. **T10 P2 ✅:** закрытие GUI/краш посреди операции службы без журнала/rollback (служба может остаться удалённой); `remove()` не глушит SCM-recovery; ожидание winws2 по имени, не по пути.
2. **T11 P2 (B7) ✅:** probe-файлы CDN-скана в живых каталогах — вынесены в `runtime/probe/` (относительные пути, без `%TEMP%`/absolute); legacy-файлы чистятся, build/collector/updater не включают `runtime/` (движок принимает абсолютные hostlist/ipset), фильтры `_probe*` в build/collector/updater как страховка.
3. **T11 P2 ✅:** TCP16-20 при медленном аплинке всё ещё может обрываться до 64 КБ (нужен `max(6, size/rate)`); H3-проба: поток-сирота при дедлайне 12 c; отмена батареи не прерывает текущий прогон и теряет частичные результаты.
4. **T12 P2 ✅:** правки списков/конфига не блокируются во время теста (`checkers_busy`); `/api/status` = 186 мс и 2 tasklist каждые 4 c (~5 % ядра) — Toolhelp32+кэш; гонка restart-кнопки (1.2 c между stop/start).
5. **T10 P2/оптимизации ✅:** ProcessProbe ~40–55 запусков PowerShell за 60 c → объединить в один PS-вызов (−45–60 %); `status()` 33 мс sc.exe → Win32 0.8 мс; ожидание смерти winws2 через `WaitForSingleObject` (−1.5–2 c).
6. **T14 P2 ✅:** одно исключение в `diagnostics.py` убивает весь отчёт (per-check guard); `dns_manager.reset()` теряет 3-й+ DNS; гонка load→save в `games.py`/`api_games`; CDN-стабилизатор пишет в bundled-списки, которые апдейтер перезаписывает.
7. **T13 P1 ✅ (без первого хопа):** portable-апдейт не доставляет новые runtime-зависимости (`python/`, niquests → H3-проба пропадает у обновлённых 0.10→0.11); первый апдейт 0.10→0.11 выполняет старый код без rollback/stop-controller — риск смешанной установки. Смягчение: обновлять python/ по манифесту, либо предупреждать в нотах.
8. **T15 P2:** CI: `api_smoke` может поднять crash-recovery (службу) при журнале; сьют зелёный при пустом PUBKEY — добавлен тест `test_pubkey_is_configured`; golden не покрывает games/ipset-ветки.
9. **T9 P2 ✅:** GameFilter расширяет противоположное окно захвата (TCP-режим добавляет UDP 1024-65535 и наоборот); конфиг без валидации типов (AttributeError на `fake_blob` int); `fake_blob` no-op на `fake-disorder`; `--wf-save` молча обрезает >~160 порт-элементов (не регресс, 1.0.5–1.0.7).

## 4. Новое в zapret2 1.0.6/1.0.7 — применимость

- **Дубли одного list-файла в профиле запрещены (1.0.7).** Наши релизные конфиги чисты (проверено матрицей 79 кейсов + статический разбор); риск только у `custom`-пресета → `validate_args` теперь fail-closed и даёт текст «failed to register hostlist». Опция: preflight-валидация дублей с понятным сообщением (бэклог, низкий приоритет).
- **`--wf-priority` (1.0.7).** Принят движком 1.0.7, на 1.0.5/1.0.6 — «unknown option». По умолчанию не нужен; сосуществование с другими DPI-тулзами не решает. Кандидат: экспертный тоггл 0.11+ (не включать по умолчанию).
- **`!`-исключения в hostlist (1.0.7).** Движок принимает; наша валидация (`list_health._DOMAIN_RE`, редактор UI) строку с `!` отвергает. Кандидат-фича: поддержать `!domain` в user-списках + coverage/дедуп aware.
- **16K лимит WinDivert-фильтра.** Запас ×7.5 (сейчас ≤2176 B). Кандидат: предупреждение в диагностике для custom-пресетов, не блокировать.
- **QUIC tb-dissection / очистка `dis` при неудачном TLS-диссекте (1.0.6).** Уже в движке 1.0.7; наш `zapret-custom.lua` не вызывает `tls_dissect*` и не полагается на частичный `dis` — влияния нет.
- **`?`/`#` как конец домена в URL (1.0.6), winsize-scale clamp.** В нашем коде зависящих мест не найдено.
- **blockcheck2 / init.d / zapret-obfs cgnat.** Не наш сценарий (Windows GUI, без Linux-инструментов/obfs-сервера).

## 5. Где сырьё

`_analysis/tech-audit/00-BRIEF.md`, `00-LEAD-NOTES.md`, `01-launcher-args.md`, `02-service.md`,
`03-tester.md`, `04-server-ui.md`, `05-updater-build.md`, `06-data-diagnostics.md`,
`07-tooling-tests.md` (локально, gitignored, ~3000 строк с file:line и PoC).
## 6. Fix batch 2026-11-14 — закрытые P1/P2 и live-остатки

Все пункты §3 (кроме части п.8) реализованы и покрыты unit-тестами; живая
приёмка SCM/апдейтера/тестера на реальной сети намеренно НЕ выполнялась
(запрет живых манипуляций в ТЗ), поэтому её нельзя считать пройденной.

| Область | Что сделано | Коммит |
|---|---|---|
| T10 service | durable-журнал `logs/service_op_state.json` + recovery при старте GUI (install/remove/repair/start/stop, orphaned→удаление); remove(): refcounted pause SCM-recovery, проверка failure actions до delete, подтверждение Win32+sc (1072 = не успех), точный resume; winws2 ждём Toolhelp32 path-фильтр + `WaitForMultipleObjects` вместо tasklist-циклов | `63ee412` |
| T11 tester | TCP16-20 бюджет `max(6, min(30, 64КБ/rate*1.5+2))` по измеренной скорости (rc=28+неполная загрузка = TIMEOUT, не DETECTED); H3 wall 6 c + close/grace/orphan; отмена батареи с частичными результатами; probe-файлы → `runtime/probe/` (относительные пути, legacy-файлы чистятся, в релиз/диагностику не попадают) | `7f71e10` |
| T12 статус/локи | `/api/status`: Toolhelp32+TTL-кэш (≈0.02–9.3 мс vs tasklist 116 мс), service status QueryServiceStatusEx (1.14 мс vs sc 30.6 мс); restart stop/start сериализованы gate-локом + дедуп повторного start (2.5 c); mutating api_lists/api_config/api_games → 409 при busy | `63ee412`, `1efb165` |
| T14 данные/диагностика | per-check guard (отчёт всегда формируется, упавший чек = skip/warn); DNS backup v2 (все v4/v6, миграция v1, restore всех адресов); games lock + `mutate_games`; CDN-стабилизатор пишет в user-списки (`list-include-user`, `list-exclude-user`), не в bundled; conflict_scan TTL-кэш 12 c | `1efb165`, `7f71e10` |
| T13 updater | portable manifest runtime-секция (`python/**` sha256), staging в `python.new` + атомарное переключение батником с rollback, post-check VERSION/файлов/runtime; mixed-install fail-closed при отсутствии runtime; release-гейт публикации; **ограничение:** первый хоп 0.10→0.11 старым апдейтером python/ не доставит — в release notes «portable 0.10: переустановить из архива» | `4749c04` |
| T9 launcher | `%GameFilter%` только в окно своего протокола; нормализация типов конфига (fail-open+лог); `fake_blob` → alt_tls во всех `--lua-desync` (fake/tls_fake_disorder/fakedsplit) | `fbd9b41` |
| Follow-up | build.py/build_lite.py не кладут runtime-файлы (`zapret-auto.txt`) в архивы; UI показывает `runtime_warning` из `/update-check`; `.gitignore` → `/runtime/` | `19a4452` |

**Оптимизации (замеры синтетические/read-only):** ProcessProbe ~54→~26
PS-запусков за 60 c (−52%), тик ~3.9→~3.0 c; `/api/status` ≈0.02 мс кэш;
DNS current_status 3.42→0.83–0.86 c (×4); winws2 wait — миллисекунды вместо
до 1.9 c; H3 пропуск после дедлайна в батарее (нейтральный H3_NONE).

**Live-приёмка (остаётся):** реальные install/remove/repair/restart службы и
failure actions; живой portable-апдейт (в т.ч. 0.10→0.11); живой тестер/H3/CDN
на реальной сети; живой DNS apply/reset (IPv6, 3+ сервера); Win10, PowerShell
5.1 end-to-end, две копии GUI. **Известные остатки:** `server/recommend.py` при
отмене может пометить непроверенные домены «заблокирован» (partial-финал
помечен); `full_analyzer` может включить частичный профиль в screening;
V3nilla/RIPEstat-лицензия (решение владельца); A/B ipset staged — ждёт прогона.

**Батарея после batch:** compileall OK · `pytest tests` 314 passed · security
47 passed · api_smoke OK · args_golden OK · check_arg_file OK · js_bundle OK ·
status_contract OK.
