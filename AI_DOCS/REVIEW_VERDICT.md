# Вердикт по внешнему аудиту (4 файла Analyze*) — 2026-10-02

Результат построчной верификации внешнего аудита (Desktop\Zapret 2 GUI\
Analyze step1..3.md + Analyze AI sum.md) с живыми репро.
Цель файла: любая модель (в т.ч. без контекста сессии) не «чинит» то, что
не сломано, и знает, что реально чинить и как проверять.

## 0. Как работать с проектом (обязательный контекст)

- Истина — репозиторий `C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI`.
  Desktop-копия `Zapret 2 GUI\zapret2_gui` — зеркало: синк
  `git fetch upstream && git merge --ff-only upstream/main`.
- Порядок чтения: `AI_DOCS/AGENTS.md` → `PROJECT_MAP.md` → `PLAN_0.9.md` →
  `STRATEGY_TRIALS.md` → `EXTERNAL_NOTES.md` → `RELEASE_CHECKLIST.md` → код.
- После правок: `python -m py_compile <файлы>`;
  `node --check frontend/js/app.js`; dry-run сборки args через
  `core.launcher.validate_args` (winws2 `--dry-run`).
- Пакет безопасности: `python tools/security/test_updates_security.py` (41 тест).
- Правило проекта: прежде чем «исправлять» — прочитай раздел 1 этого файла и
  приведи репро; аудит уже ошибался (см. раздел 1).

## 1. НЕ БАГИ — «исправление» навредит (подтверждено кодом + репро)

1. `server/server.py:773-779` `same_as_naked` симметричен: голый прогон идёт
   ровно по `NAKED_BASELINE_HOSTS` (`core/tester.py:108-112,1470-1472`),
   `prof_ok` фильтруется тем же списком. НЕ добавлять фильтры CONTROL/QUIRK —
   это как раз сделает сравнение асимметричным.
2. Голый речек спорных (`server.py:955-1012`) — замысел, не баг: contested =
   только домены, провалившиеся под лучшей стратегией; этап 2 перепроверяет
   их же под профилем с альтернативными блобами.
3. `core/full_analyzer.py:110-126` — splice корректен: `validated` заменяет
   собой префикс уже отсортированного `all_screened`, каждый профиль ровно
   один раз. ZeroDivisionError при `total=0` нет (деление внутри `run_one`,
   фаза 2 использует `max(len(top3),1)`).
4. «Ложно-красный при 100%» — невозможен: при `net_rate >= 100` ветка `ok`
   (`server.py:843`) срабатывает раньше `no_bypass`.
5. `MainPage.bind` и старт не с `#main` — сценарий узкий и самолечится при
   первом переходе на главную (стартовый hash всегда main).
6. `_check_block_types` вообще и намеренно смотрит только `status=="fail"`
   (см. п. 2 очереди — там правим именно это, но без красной краски).

## 2. ПОДТВЕРЖДЁННЫЕ БАГИ (очередь; приоритет сверху)

1. **build_custom слипает первый сегмент** — `core/strategy_builder.py:196-205`
   не ставит `--new` между header (в который входит первый профиль
   «Discord Voice») и первым family-сегментом. RePro: собранный custom.txt —
   строка `--lua-desync=fake:blob=quic_google` и сразу `--comment=Discord TCP
   tls` без `--new`; профилей 7 вместо 8. Фикс: вставить `--new`;
   приёмка: custom на all-default даёт 8 профилей, voice и discord-tls
   раздельны, dry-run OK.
2. **quirk_skip без storage.googleapis.com** — `server/server.py:883-884`
   (4 хоста) vs `core/tester.py:47-50` (5) vs frontend (5). Ложное
   «заблокирован: storage.googleapis.com» + до 3 лишних переборов блобов.
   Фикс: импортировать `QUIC_QUIRK_DOMAINS` из tester (единый источник).
3. **fake_blob не отдаётся в `/api/config`** — `server.py:1679-1695` его нет,
   save принимает (`:2097`), фронт читает (`app.js:541`). Каждый запуск GUI →
   селект сброшен → ложные «неприменённые изменения» / откат блоба кнопкой
   перезапуска. Фикс: добавить поле.
4. **install() игнорирует результат start()** — `core/service_manager.py:450`,
   плюс `_sc(["failure"...])` (`:447`) без проверки. Сбой старта = «Служба
   установлена» при отсутствии обхода. Фикс: проверять оба результата.
5. **Относительный @blobs/ в игровом блоке** — `core/launcher.py:387-390`,
   единственное место без абсолютизации (`:208-212` для пресетов). При
   cwd=System32 служба не стартует. Замаскировано: все 22 пресета объявляют
   `quic_google` (`rg --files-without-match quic_google presets` пуст).
   Фикс: абсолютизировать путь.
6. **games.json затирается при битом JSON/BOM** — `core/games.py:109-122`
   (и читается чистым utf-8). Фикс: `.bak` + не перезаписывать при ошибке
   парсинга; чтение utf-8-sig.
7. **EXE-апдейт мёртв** — `update_bat` создаётся (`server.py:234`), но никто
   не запускает; фронт только `location.reload()` (`app.js:397-425`).
   Решение автора 2026-10-05: **дописать запуск батника**, модель подписи НЕ
   трогать (fail-closed Ed25519 — антиподмена EXE в РФ, c4fc6da/392dbd0/
   6ff23a0; self-replace задуман изначально, f2da9b0 «exe self-replace via
   update.bat» — не закончен только запуск). Откат на «скачайте вручную»
   запрещён: он убирает проверку подписи у основной сборки.
8. **Хвосты** (по одному, с тестами): heal — сверка по хешу с эталоном из
   `_MEIPASS`, размер как быстрый шорткат (было: только размер, поэтому правка
   SYSTEM-файла меняющего размер откатывалась на каждом запуске, а подмена
   байта при том же размере выживала; `key_files` — только SYSTEM, user-файлы
   не участвуют — решение автора 2026-10-05);
   `try` вокруг `process_probe._find_pids` (`:374-375`); диагностика:
   классифицировать quirk-хосты с маппингом dns/ip_block=fail,
   sni/tls=neutral (кэш `{host: info}`, единый источник списка квирков) —
   вернёт вывод про SNI и уберёт жёлтую канарейку при мёртвой сети.
9. **`lists/ipset-exclude.txt` — СИСТЕМНЫЙ список** (решение автора
   2026-10-05): авторский, пользователю не редактируется, updater считает
   его SYSTEM — верно. Ошибка в том, что UI его редактирует:
   вкладка «IP-сети — не трогать» (`index.html:745`, `app.js:1762`) ходит в
   `/api/ipset-exclude-list` → `server.py:1627` (GET) и `:1871` (POST) →
   `lists/ipset-exclude.txt` (12 строк приватных диапазонов). Пользовательский
   файл `lists/ipset-exclude-user.txt` движок уже учитывает
   (`core/launcher.py:180-189`, второй `--ipset-exclude`), и `ipInc` сделан
   по правильной схеме (`app.js:1761` → `ipset-include-user.txt`).
   Фикс: роуты + `_USER_LIST_FILES` (`server.py:340-341`, сейчас чистит BOM
   системного файла вместо пользовательского). Перенос существующего
   содержимого из системного файла в user-файл НЕ делать молча.

## 3. Подтверждённые факты аудита (спорные по серьёзности, не «баги»)

- Канарейка `www.google.com` в quirk-списке диагностики
  (`diagnostics.py:49-53,283-302`); блок рекомендаций зависит только от fail
  (`app.js:1324`), т.е. при мёртвой сети красный оставляет только discord.
- Дрейф списков: диагностика 3 хоста / тестер 5 / фронт 5.
- `_get_tier_hosts` игнорирует tier (`tester.py:778-779`): «smoke» == «full».
- Мёртвый код (не опасно): `zapret_controller.restart` без вызовов,
  `_togglesEqual` без вызовов (`app.js:973`), фантомные
  btnSettingsExport/settingsResult/gamesSaveBtn.
- Остальные пункты step1-3 (P1-P10, Z1-Z10, S1-S8, H7/H8 и пр.) построчно
  НЕ проверялись — доверять только с репро.

## 4. Кандидаты (прочитаны кодом, репо НЕ проверены — не «чинить» без репро)

Внесено ревьюером 2026-10-05. Все — file:line + почему важно. Правило
раздела 1 действует и здесь: сначала воспроизведение, потом правка.

1. **`core/tcp_timestamps.py:81-86`, `core/conflict_scan.py:86-92`** —
   `subprocess.run(text=True)` без `encoding`. Первый вызывается уже ПОСЛЕ
   `stop()` (`core/zapret_controller.py`, `core/service_manager.py:530-532`) →
   `UnicodeDecodeError` вместо внятного сообщения, движок уже остановлен.
   Тот же класс, что §21/§2 в AGENTS (чинили дважды). Фикс: `encoding="oem",
   errors="replace"`, как в остальных `text=True`.
2. **`frontend/js/app.js:2901`** — сырой `fetch` без таймаута (в отличие от
   `apiGet`/`apiPost`), + `:3010-3017` первый сетевой сбой глушит полл, тогда
   как серверный тест продолжается: UI снимает блокировки, результат уже не
   увидит. То же для `Status.refresh` (`:128`, 4 с) против `tasklist` 6 с
   (`server.py:693-710`) на потоковом сервере → наложения и ответы не по
   порядку.
3. **`frontend/js/app.js:562`** — `loadConfig` глотает исключение: UI
   показывает дефолты при реально других настройках (и ложные «неприменённые
   изменения»).
4. **`core/process_probe.py`**, кроме `try` из §2.8: гонка `etl.exists()`
   сразу после `pktmon start` (`:192`) → захват молча отменяется; `etl2txt`
   через `run_quiet` с дефолтным 30 с (`core/utils.py:266`) → обрезанный txt →
   заниженные `recv` → ложное «UDP глушится»; парсер только IPv4 (`:221`),
   при этом флаг `ipv6` ставится по снапшотам; коллизия ключа TCP/UDP в
   `_merge_history` (`:262`) — UDP-цель на `ip:port` классифицируется как TCP.
5. **`core/list_health.py:174-203`** — `_append_entry`/`_remove_entry`:
   read-modify-write `write_text` без tmp+replace и без лока; `_checkers_busy()`
   (`server.py:325-335`) не атомарен относительно `cdn/apply-all` → два
   параллельных POST теряют правки списка. Для сравнения, атомарная запись
   есть в `core/tester.py:1327-1332`.
6. **Нет single-instance и нет лока на операциях со службой** —
   `main.py:248-251` (два экземпляра = два admin-приложения, два webview, оба
   пишут `games.json` одним tmp-именем), `server.py:2821` (threaded-сервер без
   лока вокруг install/remove/reconfigure).
7. **Мелочи:** `test_session.log` не ротируется и целиком едет в каждый отчёт
   (`core/collector.py:179`); `update_manifest.json` в portable-zip перечисляет
   22 `core/__pycache__/*.pyc`, которых в архиве нет (сборка `write_manifest` по
   staging-дереву); `frontend/css/app.css:1240-1247` — закрытые `.modal-overlay`
   скрыты только `opacity`/`pointer-events` → остаются в tab-order;
   `app.js:1818-1846` — импорт настроек из ZIP без подтверждения (единственное
   разрушительное действие без вопроса).

## 5. Артефакты верификации

- Живые репро: `build_custom` на копии default (junction без `--new`);
  `grep update_bat` (1 вхождение); `rg --files-without-match quic_google presets`.
- Прочитанный код: server.py 748-1012, 1278-1307, 1655-1695;
  strategy_builder.py (целиком); full_analyzer.py (целиком);
  launcher.py 195-344; service_manager.py 385-464, 520-550;
  tester.py 100-124, 770-790, 1455-1500; main.py 88-162;
  process_probe.py 355-469; diagnostics.py 35-64, 265-310, 350-395, 437-471;
  app.js 378-432, 459-533, 1312-1328, 2890-3029.
- Исходные отчёты аудита: `Desktop\Zapret 2 GUI\Analyze *.md`.
