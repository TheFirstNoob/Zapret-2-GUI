# AGENTS.md — Критические находки (чтение обязательно перед любыми изменениями)
>
> **Последнее обновление: 2026-08-27 (Pre-Release 0.3)**
> **Размер EXE:** 18.0 MB (было 43.9 MB) — исключены numpy, PIL, pygments, setuptools через `--exclude-module`
> **Статус:** `default.txt` — универсальная стратегия, работает у всех протестированных провайдеров

> **Эта информация теряется при сжатии контекста ИИ.**
> Новый агент ДОЛЖЕН прочитать этот файл перед редактированием кода или тестированием.

---

## 1. build_args_from_preset — баг с короткими путями (2026-07-17) 🚨

### Cимптом
Все 17 пресетов показывали ОДИНАКОВЫЙ результат:
`google:200, discord:timeout, youtube:timeout` — хотя Zapret 1 (winws.exe) РАБОТАЕТ.

### Причина
Функция `build_args_from_preset` в `core/launcher.py` заменяла `@lua/` и `@blobs/` на **короткие 8.3 пути**:
```python
# БЫЛО (сломанный код):
for dir_name, dir_path in [("@lua/", short_lua), ("@blobs/", short_blobs)]:
    line = line.replace(dir_name, "@" + str(dir_path) + "\\")
```

Где `short_lua = short_path(lua_dir)` → например `C:\Users\THEFIR~1\Desktop\ZAPRET~3\ZAPRET~3\lua`.

**Проблема:** `--lua-init @C:\Users\THEFIR~1\...\zapret-lib.lua` (короткий путь + `@`) приводит к тому, что winws2:
- Загружает только 1 профиль вместо 4-7 (пишет "we have 1 user defined desync profile(s)")
- Не захватывает пакеты (windivert initialized но zero packet events)
- Все соединения падают с 000

### Исправление
```python
# СТАЛО (рабочий код):
for dir_name, dir_path in [("@lua/", lua_dir), ("@blobs/", blobs_dir)]:
    line = line.replace(dir_name, "@" + str(dir_path) + "\\")
```

**Почему помогло:** полные длинные пути (`@C:\Users\TheFirstNoob\Desktop\Zapret 2 GUI\zapret2_gui\lua\`) работают корректно с winws2. Короткие 8.3 пути (`@C:\Users\THEFIR~1\...`) вызывают баг в парсинге аргументов winws2.

### Важно
- `@lists/` — заменяются на путь без `@`
- Только `@lua/` и `@blobs/` ТРЕБУЮТ сохранения `@` + полного (не короткого) пути

---

## 2. @hostlists/ — не резолвился (2026-07-17) 

### Cимптом
Пресеты с `@hostlists/list-exclude.txt` передавали эту строку как есть, без резолва в абсолютный путь.

### Исправление
Добавлен параметр `hostlists_dir`, короткий путь `short_hostlists`, и цикл для замены `@hostlists/`.

---

## 3. --comment строки не фильтровались (2026-07-17) 

### Cимптом
Строки вида `--comment=Discord config` передавались winws2 как аргументы.

### Исправление
Добавлено `line.startswith("--comment")` в условие пропуска строк.

---

## 4. debug_winws2.log не существовал при short_path (2026-07-17) 

### Cимптом
`short_path()` вызывался для файла `debug_winws2.log` до его создания.

### Исправление
Файл `.touch()` перед вызовом `short_path()`.

---

## 5. `--payload` — ключевой параметр (имба) 🚨

**Все стратегии НИЧЕГО не делают без `--payload`.**

Раньше `--payload` считался опциональным — предполагалось, что `--filter-l7=tls` сам определяет тип трафика. Это НЕ ТАК.

### Что делает `--payload`
- `--payload tls_client_hello` — говорит winws2 *какие именно байты в TCP потоке* являются ClientHello
- `--payload http_req` — для HTTP (GET/POST запрос)
- `--payload quic_initial` — для QUIC Initial пакетов
- `--payload discord_ip_discovery` — для Discord UDP voice discovery

**Без `--payload` — lua-desync не знает где искать → DPI не обманут → 000.**

---

## 6. `repeats=N` — перегрузка, не нужен везде ⚠️

### Правило
- **Для `multisplit`**: `repeats=1` или вообще без repeats — достаточно
- **Для `fake`**: `repeats=6-8` только если fake без nodrop, иначе 1
- **QUIC**: `repeats=6-11` (QUIC Initial требует больше повторов)
- **Если `nodrop` указан**: repeats=1 (оригинал не дропается, фейк уже есть)

**НЕ увеличивать repeats «на всякий случай».**

---

## 7. Debug режим — перегрузка системы 🐌

- `--debug=@debug_winws2.log` — пишет КАЖДЫЙ пакет, пинг +50-150ms, CPU +15-30%
- Включать ТОЛЬКО для диагностики, не для постоянной работы
- Файловый debug — работает. Консольный (`--debug=1`) — ломает захват → 000

---

## 8. `nodrop` и `repeats` — совместное использование

`nodrop` = не удалять оригинальный пакет. Когда `nodrop` активен:
- Оригинал уходит как есть, фейк отправляется отдельно
- `repeats=1` достаточно

Если `nodrop` НЕ указан:
- Оригинал дропается, repeats=N отправляет N копий фейка

---

## 9. Hostlist-исключения — порядок важен

User-листы подставляются в КОНЦЕ аргументов: сначала exclude, потом include.
Последний `--hostlist` переопределяет предыдущие.

---

## 10. Toggle-тогглы: архитектура

### GameFilter
```
off  — ничего не добавляется
tcp  — --filter-tcp 1024-65535 + --filter-l7 tls + lua-desync
udp  — --wf-udp-out=1024-65535 + --filter-udp 1024-65535 + lua-desync
both — TCP + UDP вместе
```

### Discord Voice
```
--filter-udp 19294-19344,50000-50100
--filter-l7 discord,stun
--payload discord_ip_discovery
--out-range -d10
--lua-desync=fake:blob=quic_google
```

### Auto Hostlist
Включает `--autohostlist` в блоках list-general (General TCP + QUIC General).
При включении автосоздаёт `lists/zapret-auto.txt`.

### Применение
- При старте — читаются из AppConfig
- При установке службы — читаются из UI фронтенда
- Для изменения нужен перезапуск

---

## 11. Режимы работы тестера

### Basic
```
1. Убить Z2 (winws2.exe), если запущен
2. Тест всех профилей (сканирование presets/)
3. Выбрать лучший по success_rate
4. Показать результат
```

### Extended
```
Phase 0: Zapret 1 — тест текущей защиты
Phase 1: Naked — тест без защиты
Phase 2: Zapret 2 — тест всех профилей
Phase 3: Full analysis — сравнение, топ-3 рекомендации
```

---

## 12. `build_args_from_preset` — актуальная архитектура

### Порядок обработки пресета
```
1. Чтение .txt → splitlines()
2. Пропуск пустых строк, # комментариев, --comment строк
3. Замена @lists/ → full_path\  (без @ в результате)
4. Замена @lua/ → @full_path\   (ДЛИННЫЕ пути, С @)
5. Замена @blobs/ → @full_path\ (ДЛИННЫЕ пути, С @)
6. Замена @windivert/ → @full_path\ (С @)
7. %GameFilter% замена
8. User-листы из list-exclude-user.txt / list-include-user.txt
9. --autohostlist инжект в блоки list-general (если включён)
10. GameFilter явные правила
11. Discord Voice правила
12. --debug=@debug_winws2.log — в самом конце
```

---

## 13. default.txt — универсальная стратегия ✅

**`default.txt` работает у ВСЕХ протестированных провайдеров:**
- Новороссийск («Новый Интернет»)
- Ижевск (Марк-ИТТ)
- Воронеж (JustLan)
- СПб (Т2 мобильный / Skynet)

Ранее считалось, что разные DPI требуют разных стратегий — это опровергнуто.
`default.txt` оказался универсальным решением.

### Структура default.txt
```
--wf-tcp-out 80,443,2053,2083,2087,2096,8443,%GameFilter%
--wf-udp-out 443,19294-19344,50000-50100,%GameFilter%
--lua-init @lua/zapret-lib.lua
--lua-init @lua/zapret-antidpi.lua
--blob google_tls:@blobs/tls_clienthello_www_google_com.bin
--blob quic_google:@blobs/quic_initial_www_google_com.bin
--lua-gc 60
[Discord Voice] [Discord Media TCP] [Discord TCP tls]
[Google TCP tls] [General TCP] [QUIC Google] [QUIC General]
```

### Известный изъян
Один маленький — будет описан позднее.

### ⚠️ Что НЕ ИЗМЕНЯТЬ

**core/launcher.py**
- `@lua/` и `@blobs/` — полные длинные пути (не short_path)
- `--comment` строки — фильтровать
- User-листы — проверять `exists() && st_size > 0` перед инжектом

**core/tester.py**
- `TEST_HOSTS` — плоский список, без tiers/категорий
- `_get_tier_hosts` — всегда возвращает `list(TEST_HOSTS)`, tier игнорируется
- `_curl_test` — один запуск, без retries
- `success_rate` — процент 0-100, никаких weighted_score/safe_penalty

**core/service_manager.py**
- `install(root_dir)` — принимает root_dir параметр (не вычисляет из __file__)
- `status()` — парсит STATE из `sc query`, а не проверяет процесс tasklist-ом

### 🔮 План на будущее (НЕ ТРОГАТЬ ПОКА)

- **Game TCP fallback** — не-TLS профиль для игр (Minecraft)
- **Diagnoser** — игровая диагностика (реворк)
- **Blob rotation** — авто-замена .bin при нестабильности

---

## 14. tcp_ts / PAWS — ключевая механика fake (2026-08-23) 🚨

### Как работает fake в default.txt
`fake` отправляет блоб на ТОМ ЖЕ seq, что и оригинальный ClientHello.
`tcp_ts=-1000` уменьшает TCP-timestamp → **сервер отбрасывает фейк по PAWS**
(старый TSVal), а DPI (без PAWS) видит фейк первым и пропускает соединение.

### tcp_ts на multisplit — ЗАПРЕЩЁН (найден реальный баг)
Если `tcp_ts=-1000` стоит на `multisplit` — сплит-части ТОЖЕ отбрасываются
сервером по PAWS → реальные данные не доставляются:
- с `nodrop` выживает только оригинал (работает, но хрупко);
- без `nodrop` соединение умирает полностью (000 на всех хостах).

**Рабочий вид (2026-08-23, проверено curl-батареей):**
```
--lua-desync=fake:blob=google_tls:tcp_ts=-1000:nodrop
--lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=google_tls:nodrop
```
fake — с tcp_ts (должен умереть по PAWS), multisplit — БЕЗ tcp_ts (должен доставить данные).

### Убирая nodrop с multisplit — соединения падают (проверено)
Доставка данных = сплит-части (валидный TS) + оригинал (nodrop).
Не экспериментировать с дропом оригинала без повторной проверки всей батареи.

---

## 15. Discord file upload — реальная причина (2026-08-23) 🚨

Discord грузит файлы на `discord-attachments-uploads-prd.storage.googleapis.com`
через **QUIC (UDP 443), TCP-фолбэка нет вообще** (0 попыток за сессию в debug-логе).

При урезании list-general.txt до 21 строки домен потерялся → `desync profile 0
(no_action)` → чистый QUIC Initial → DPI убивал → «не отправляются файлы».

**Исправление:** домен добавлен в `list-general.txt` (покрытие QUIC General)
и `list-discord.txt` (покрытие Discord TCP). Домен есть в list-general
обоих эталонов: 1.9.6 и 1.10.1.

### Проверка загрузки без Discord-клиента
```
curl.exe -4 -s -m 8 -o NUL -w "%{http_code}" https://discord-attachments-uploads-prd.storage.googleapis.com/
```
403 = соединение+TLS работают (это норма для анонимного запроса к GCS). 000 = загрузки сломаны.

---

## 16. pos-маркеры winws2 — ZERO-BASED (2026-08-23)

`resolve_multi_pos(data, l7, "N")` БЕЗ 4-го аргумента трактует N как zero-based:
`pos=1` → разрыв после 1-го байта (первый сегмент = 1 байт) — **точный аналог
nfqws `--dpi-desync-split-pos=1`**. `pos=1` в пресетах РАБОТАЕТ и менять его не нужно.
(4-й аргумент `true` в lua-тестах меняет семантику на 1-based — не путать.)

---

## 17. Прочие фиксы 2026-08-23

- `launcher.py`: инжектился несуществующий флаг `--autohostlist=@...` → winws2
  падал бы с unknown option при включённом тоггле. Заменён на `--hostlist-auto=<путь>`
  (без `@`, подтверждено --dry-run).
- `launcher.py` + `zapret_controller.py`: `tasklist` на русской Windows выводит
  CP866 → UnicodeDecodeError при `text=True`. Добавлено `encoding="oem", errors="replace"`
  (крашилось прямо в launch_winws2_bat при проверке запуска).
- YouTube по TCP (curl) на v2 не работает (000) при работающем QUIC-пути в браузере.
  В v1 ALT11 TCP работает. Открытый вопрос — НЕ блокирует пользователя, браузер идёт через QUIC.

---

## 18. Чистка остальных пресетов (2026-08-23)

Применено ко всем пресетам (кроме default — уже исправлен):

1. **`tcp_ts=-1000` убран со ВСЕХ `multisplit`-строк** (fakedsplit, fake-disorder,
   fake-multidisorder, hostfakesplit, multisplit-pure ×4, multisplit-seqovl ×4) —
   см. §14: сплит-части с tcp_ts умирают по PAWS, данные не доставляются.
2. **fake-multidisorder: `multidisorder:blob=google_tls` → `multidisorder:pos=1,midsld:nodrop`** —
   blob заставлял disorder отправлять GOOGLE-блоб вместо реальных данных + дроп
   оригинала = сервер получает мусор. multidisorder должен disorder-ить РЕАЛЬНЫЙ payload.
3. **hostfakesplit: позиционные аргументы `hostfakesplit:discord.com` не работают** —
   функция читает `desync.arg.host`. Исправлено на `hostfakesplit:host=discord.com`
   (аналогично google.com, ya.ru).
4. fake-only — исправлений не требовал (только fake, tcp_ts на fake корректен).
5. Все 8 пресетов прошли валидацию `--dry-run` через build_args_from_preset.

### Проверка пресетов после правок (шаблон)
```
python: build_args_from_preset(...) -> winws2.exe --dry-run + args -> нет 'unknown option/bad file/error'
```

---

## 19. Валидация при старте (2026-08-23)

`core/launcher.py::validate_args(exe, args)` — прогоняет аргументы через
`winws2 --dry-run` (~0.1-0.3 с, WinDivert не загружается) и сканирует вывод
на маркеры ошибок (`unknown option`, `bad file`, `cannot access/create/open`,
`lua error`, `error loading`). **Код возврата winws2 ненадёжен (0 даже при
unknown option) — проверяется именно текст.**

Подключена в двух местах:
1. `ZapretController.start()` — валидация ДО `self.stop()`: битый пресет
   отклоняется, работающая инстанция НЕ останавливается (пользователь остаётся под защитой).
2. `server.py :: _handle_service_install` — служба не ставится с невалидными аргументами.

### Границы метода (проверено)
dry-run ловит: неизвестные флаги, битые пути (--lua-init/--blob/--hostlist).
dry-run НЕ ловит: ошибки аргументов lua-функций (`blob=nosuchblob`,
`hostfakesplit:без host=`) — они всплывают только на пакете в рантайме.

`dist/Zapret2GUI.exe` пересобран 2026-08-23 со всеми фиксами (18.2 MB).

---

## 20. Beta 0.2 (2026-08-23, вторая волна)

### Исправленные баги
1. **Служба запускала протухший bat** — `_zapret_service.bat` писался только при
   установке; кнопка «Запустить службу» поднимала СТАРУЮ стратегию молча.
   Теперь `_prepare_service_bat()` регенерирует bat из текущего пресета+тогглов
   ПЕРЕД install И start (с валидацией). Параметры берутся из конфига, если
   в запросе их нет.
2. **`main.py::_warn_if_bad_path` — инвертированная логика** (MessageBox был
   мёртвым кодом, тихий выход происходил у тех, у кого 8.3 отключён).
   Новая семантика: ASCII-пути (включая пробелы) — ок; кириллица с 8.3 — ок
   (лаунчер использует короткие пути); кириллица без 8.3 — предупреждение.
3. **`_ensure_data_dir` затирал пользовательские правки** — copytree при каждом
   запуске exe перезаписывал presets/lists. Теперь данные обновляются только при
   смене VERSION (маркер `data_version.txt`). Пользовательские файлы
   (*-user.txt, свои пресеты) не удаляются никогда.
4. **CP866-кодировки**: `encoding="oem", errors="replace"` добавлен во все
   `text=True` вызовы в `tester.py` (9 мест) и `service_manager.py` (2 места).
   Ранее это крашило launch/тесты на русской Windows (см. §17).

### Новый функционал — страница «Диагностика»
`core/diagnostics.py` + `POST /api/diagnose` + страница #diagnostics в UI.
Проверяет: права, путь, процесс winws2, конфликт Zapret 1, службу, валидность
пресета (dry-run), debug-лог, связь (google-канарейка, discord.com, хост загрузок
Discord, youtube TCP). Кнопка «Скопировать отчёт» — текст для тикетов
(`format_report_text`).

### Проверка службы вживую (2026-08-23, Win11 26200)
cmd-обёртка службы прожила 2+ минуты, winws2 в Session 0, обход работает,
остановка чистая. На этой машине служба стабильна. Историческое «50 на 50»
на других машинах вероятно объяснялось протухшими bat (теперь исключено) и
разным поведением SCM по версиям Windows.

### Версия
`VERSION = "Pre-Release 0.2"`, exe пересобран.

---

## 21. Тестер: зависания и скорость (2026-08-23, третья волна)

### Причина исторических «50 на 50» зависаний — НАЙДЕНА
`server.py :: _run_with_timeout` и `_check_vpn` — `text=True` БЕЗ кодировки.
tasklist/sc на русской Windows выводят CP866; при попадании кириллицы
(«КБ», «Информация», «Состояние») декодинг падал UnicodeDecodeError-ом,
поток тестера умирал на шаге «Остановка запрет перед голым тестом» →
UI висел вечно на «Останавливаем zapret...». На машинах с ASCII-выводом —
работало. Отсюда 50/50. Исправлено: `encoding="oem", errors="replace"`
(завершает полный обход кодировок: launcher, controller, tester,
service_manager, server — все вызовы закрыты).

### Ускорение тестера (замер вживую, один профиль: ~30-45s → 12.7s)
1. **Кэш TTL-проба** (`_ttl_cache`) — tracert выполняется ОДИН раз на сессию
   тестера, а не на каждый профиль (7 пресетов = 6 tracert сэкономлено).
2. **tracert ограничен**: `-h 5 -w 900`, timeout 14s (было -h 10 -w 1500, 25s).
   ТСПУ обычно на хопе 1-4.
3. **`sleep(5)` → 1.5s** в _setup_profile — launch уже подтвердил наличие
   процесса, WinDivert открывает хендл за сотни мс.
4. **curl `--connect-timeout 2`** — быстрые отказы на connect-блокировках.
5. **Параллелизм доменов 5 → 8** (CDN остаётся 15).
Замер: все 13 curl'ов доменов — 0.6s; запуск+готовность 3.4s; tracert 5.8s
(только первый профиль); пинги 2.6s. 30/30 OK.

### Голый тест больше не оставляет без защиты
`_restore_protection_after_naked()` — после naked-теста перезапускает то, что
работало до него (Zapret 2 через controller.start с текущим пресетом, или
Zapret 1 через последний strategy-bat). Результат в поле `restored` финального
ответа + прогресс-сообщение. Раньше пользователь молча оставался без обхода.

### Фронтенд
Диагностика вызывала `/api/api/diagnose` (apiPost сам добавляет префикс `/api`)
→ 404. Исправлено на `/diagnose`. Endpoint проверен вживую: HTTP 200, ~2.5s.

---

## 22. Тестер: статистика, рекомендации, naked-базлайн (2026-08-27) 🚨

### Что изменилось

1. **`network_rate` — счёт стратегии по сетевым тестам** (curl/TLS, БЕЗ пингов).
   Пинги в `success_rate` врали: Мегафон показывал «20/30 (67%)» при реальной
   доступности 4/13 (31%) — все заблокированные остались заблокированными.
   `success_rate` (с пингами) НЕ менялся (правило §13 живо), добавлены поля:
   `net_ok_count / net_fail_count / net_total / network_rate / ping_ok_count /
   ping_total` в `ProfileTestResult` + `_serialize_result` + full_analyzer.
2. **naked-базлайн в быстром тесте** — `run_naked_baseline()`: 4 хоста
   (`NAKED_BASELINE_HOSTS`: discord.com, www.youtube.com, gateway.discord.gg,
   i.ytimg.com) без защиты перед прогоном профилей (~3-5s, winws2 убивается —
   быстрый тест и так это делает). Если все стратегии = голому тесту → вердикт
   no_bypass: «winws2 не перехватывает трафик / DPI блокирует все попытки».
3. **`collect_sanity_info(profile, blocked)`** — два лёгких диагноза (без debug-лога):
   - **dry-run тех же аргументов** → парсинг «N user defined desync profile».
     0-1 вместо 4-7 = сигнатура старого бага коротких путей (§1) → вердикт
     `engine_broken`. WinError 740 (нет прав) — НЕ считается поломкой.
   - **покрытие списков**: заблокированный домен отсутствует во всех
     `@lists/*.txt`, на которые ссылается пресет → no_action (§15) → сообщение
     «добавьте домены в списки». Проверено: discord.com в list-discord.txt,
     youtube.com/googlevideo в list-google.txt — покрытие репозитория ок.
4. **Рекомендация** `_build_recommendation` (server.py): verdict
   `ok/partial/no_bypass/engine_broken/no_data`, message, `key_hosts`
   (Discord, Discord-шлюз, YouTube, YouTube CDN — пробито/не пробито),
   `blocked_domains`, `same_as_naked`, naked_network_rate.
   **Порядок веток важен:** engine_broken → misses (списки) → same_as_naked →
   ok → partial → no_bypass.
5. **YouTube TCP-прикол учтён**: не пробиты ТОЛЬКО youtube.com/googlevideo/
   ytimg/youtu.be и доступность ≥60% → вердикт `ok` с пояснением «в браузере
   работает через QUIC» (§17). На рабочей машине (Т2, СПб) default = 84.6%
   доступность, заблокированы только www.youtube.com + redirector.googlevideo.com.
   **`QUIC_OK`-инференс (2026-08-27):** www.youtube.com по TCP не прошёл,
   НО i.ytimg.com или youtu.be доступны на ТОМ ЖЕ прогоне (best.results) →
   key_host «YouTube» помечается `QUIC_OK` («работает через QUIC»). Считается
   ТОЛЬКО по полным результатам профиля после завершения всех тестов —
   никакого асинка в вердикте. У «ничего не пробилось» (Мегафон) i.ytimg
   блокирован → YouTube остаётся ❌.
6. **UI**: карточка вердикта + блок ключевых хостов (Discord/YouTube) + кнопка
   «🚀 Запустить: <best>» (POST /api/start) + таблица «Доступность» +
   чипы заблокированных + карточка «Базовый уровень без защиты».
   `renderResultGrid` не учитывает пинги.
   **UX-навигация (2026-08-27):** страницы переименованы и упорядочены по
   сценарию пользователя: «Проверка системы» (диагностика) → «Подбор
   стратегии» (тестер) → «Списки». Интро тестера — пошаговый гайд (шаг 1:
   кнопка «🔍 Проверить систему», шаг 2: «Начать тест»). Перекрёстные
   кнопки: вердикт no_bypass/engine_broken → «Проверить систему»;
   диагностика с fail → «Подбор стратегии».
7. **Классификатор типа блокировки** (`core/diagnostics.py::classify_block`,
   2026-08-27): для заблокированного домена (1 шт., youtube в приоритете) —
   DNS → TCP:443 → TLS с реальным SNI → **TLS с чужим SNI** (google/cloudflare)
   к тому же IP. Вердикты: `dns` / `ip_block` / `ok` / **`sni_block`** (IP чистый,
   блок только по SNI — работающий desync ОБЯЗАН обходить; если не обходит —
   проблема движка/списков, а не «DPI сильнее всех») / `tls_block` (не по SNI).
   Проверено вживую на Т2: youtube.com/googlevideo → sni_block (IP 142.251.x.x
   с SNI google проходит TLS за 36-57ms), discord/i.ytimg → ok.
   ⚠️ Не использовать `with ThreadPoolExecutor` — shutdown(wait=True) ждёт
   чёрные дыры (+timeout на шаг); только shutdown(wait=False).

### Найденные и исправленные баги

- **full_analyzer.py**: `test_profile(skip_aux=...)` — такого параметра нет →
  TypeError → «Полный анализ» падал ВСЕГДА (сломано и в HEAD, и в 0.2).
  Исправлено на `skip_cdn=(tier != "full")`.
- **app.js poll**: `state.all_results` не попадал в `fr` → таблица результатов
  быстрого теста была ПУСТОЙ, пользователь видел только «Вернуться» (это и
  была жалоба «тестер ничего не говорит»). → merge в поллере перед onResult.

### Эталонные отчёты (сравнение)

| Машина | default | fake-only | hostfakesplit | Диагноз |
|--------|---------|-----------|---------------|---------|
| Т2 СПб (рабочая) | 93% | 90% | 47% | профили РАЗНЫЕ → тестер ок |
| Мегафон Чебоксары | 67% | 67% | 67% | ВСЕ идентичны → winws2 не перехватывает / DPI жёсткий (нет debug-лога и naked — неразличимо, теперь тестер это различает сам) |

`lists/` теперь включаются в ZIP-отчёт — проверять покрытие доменов у
пользователя, у которого «ничего не пробилось».

---

## DNS

Яндекс.Браузер и аналоги принудительно подменяют DNS на 77.88.8.8.
Блокируют любые сторонние DoH. Тестировать в Firefox/Chrome.

---

## Killer NIC

Killer Network Interface Controller конфликтует с WinDivert.
**Симптомы:** zapret запускается, но пакеты не обрабатываются.
**Решение:** отключить Bandwidth Control в Killer Control Center.
