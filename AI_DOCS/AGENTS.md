# AGENTS.md — Критические находки (чтение обязательно перед любыми изменениями)
>
> **Последнее обновление: 2026-08-30 (Pre-Release 0.5)**
> **Размер EXE:** 18.4 MB
> **Статус:** `default.txt` — универсальная стратегия, работает у всех протестированных провайдеров

> **Эта информация теряется при сжатии контекста ИИ.**
> Новый агент ДОЛЖЕН прочитать этот файл перед редактированием кода или тестированием.

---

## ⚡ СЕССИЯ-СНАПШОТ (читать первым после сжатия контекста) 🚨

### Текущее состояние (2026-08-30)
- **VERSION = "Pre-Release 0.5"** (config.py + VERSION-файл + version_info 0.5.0.0).
- **Три дистрибутива** (`Windows build/`):
  - `Zapret2GUI.zip` — классический EXE (PyInstaller onefile, 18.4 MB)
  - `Zapret2GUI-portable.zip` (16.5 MB) — GUI на официальном Python embeddable
    (pythonw.exe подписан PSF) — без паковщика, меньше детектов Защитника
  - `Zapret2GUI-lite.zip` (1.7 MB) — батники без Python (start-<preset>.bat,
    service.bat меню, test.bat/ps1 тестер)
- **Сборщики:** build.py (exe), build_portable.py (portable), build_lite.py (lite).
  Все три пересобирать при изменении кода/пресетов/списков. `lite/` и
  `portable/` в .gitignore (генерируются сборщиками).
- **Пресеты: 9** (default, auto + 7 тестовых). `lists/`: list-general содержит
  cloudflare-ECH + discord-uploads + github-семейство; list-exclude синхронен
  с Zapret 1 (steam и т.п.); ipset-all.txt.gz (32126 CIDR, gzip по магии);
  ipset-exclude.txt (приватные).
- **Служба zapret2 = winws2.exe НАПРЯМУЮ** (как Zapret 1, binPath =
  "\"...\winws2.exe\" args", start=auto). БЕЗ cmd/bat обёртки (она триггерила
  Защитника). Args обновляются через sc config при каждом старте
  (reconfigure). sc create/config идёт через ВРЕМЕННЫЙ .bat (cmd парсит \" —
  argv-передача ломает: sc теряет image path или хранит экранированное).

### Критичные правила (нарушение = поломка)
1. **Никогда**: `--lua-init` отдельным аргументом с путём без пробелов —
   парсинг winws2 умирает (только `--lua-init=@path`). Лаунчер делает это сам.
2. **Никогда**: nodrop на google-блоке default (ютуб фикс = drop+repeats=6,
   см. §14-корректировку). General TCP оставлен с nodrop — НЕ менять вслепую.
3. **Запись в hosts ТОЛЬКО атомарно** (temp + MoveFileEx). FileMode::Create
   на живой hosts при аборте усекает файл до 0 байт (случай 2026-08-30).
4. **Гео-записи работников НЕ удалять без замены** на живой IP (200 при
   пробе ≠ гео ок! gemini: 62.133.62.97 умер → упал на RU → гео-детект).
5. Пресеты/списки правки — в репо (Documents\GitHub\Zapret-2-GUI), Desktop-
   копия синхронизируется коммитами.
6. **НЕ перекодировать файлы через PS 5.1** (Get-Content/Set-Content без
   -Encoding: чтение = ANSI, `>` = UTF-16, -Encoding UTF8 = +BOM) — mojibake
   всего файла (случай README 2026-08-30, коммит 9c104de-фикс). Правки
   только edit-инструментом; восстановление из git — `git checkout <rev> -- <file>`.

### Блокировки РФ (2026-08-30, плавающие)
- **githubusercontent (185.199.108.0/22) блок по IP** (Т2/РТК и др.):
  zapret бессилен (SYN-блэкхол). Решение: hosts-пиннинг на Fastly-эдж
  (raw/objects/release-assets/avatars → 151.101.66.132, запасные в
  `hosts.txt`) или WARP. Глобально GitHub жив (check-host.net).
- **AI-работники** (45.155.204.190 и др.): гео-обход chatgpt/gemini/claude,
  ФЛАКАЮТ (утро/день/ночь разное, скорость 1-12с). cdn.oaistatic НЕ
  пиннить (напрямую быстрее).
- **DoT (853) заблокирован, DoH (443) жив, plain UDP53 жив** на Т2.
- **YouTube РТК «через раз»** → отключить QUIC в браузере; DNS 9.9.9.9
  помогает видео.

### ВИСИТ (не сделано)
- ✅ **СИСТЕМНЫЙ АУДИТ UI (2026-08-31, 0.5)** — сделано в сессии:
  1) Главная: один вертикальный поток — «Обход DPI» + «Параметры запуска»
     акцентной группой (panel-accent), Zapret 1 — компактный серый фолбек
     внизу; статусы обоих запретов — в одном месте (справа в шапке панели);
     рамки панелей по состоянию (is-ok/warn/err + glow), тумблер DEBUG —
     красной подложкой;
  2) диагностика: человеческие объяснения вместо HTTP-кодов, техника — в
     поле `tech` (tooltip + текстовый отчёт); «Проверено/Внимание/Ошибки» +
     «заняло N с»; зеркальный ютуб-quirk;
  3) списки: «Включения/Исключения» с «когда и зачем», памятка поддоменов
     (example.com → всё; api.example.com → точечно), нумерация строк,
     счётчик записей в заголовке, индикатор несохранённых изменений,
     фикс `.btn[hidden]`;
  4) тестер: интро скрывается при старте, live-колонки (доступность/хосты/
     статусы по сети, без пингов), naked-финиш, custom пересобирается
     каждым тестом и всегда проверяется (стухшая — вне прогона), чистые
     пути ошибок/отмены/без-результата, testRun скрывается при финале;
  5) user-листы инжектятся во ВСЕ hostlist-профили (см. §9 — семантика
     winws2 подтверждена исходниками v1.0.2).
- Мегафон-пользователь: дискорд пробился после lua-init фикса, ютуб нет —
  нужны его debug-лог/диагностика (§27-контекст; свежий exe 0.5).
- GUI portable (webview) ни разу не открывали руками (тестировались
  сервер/контроллер headless) — с 0.5 тестируется пользователем.
- VM-тест с облаком Защитника на новых сборках — рекомендован.
- Возможные фичи (обсуждены, не начаты): «Починить GitHub» кнопка в
  диагностике (Fastly-проба + атомарный hosts), автоподбор desync-
  параметров, DNS-здоровье в диагностике (сделано!), wssize/syndata/oob
  пресеты (отсеяны на Т2, 30-46%).

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

## 9. User-листы: hostlist — ПО ПРОФИЛЯМ, а не «в конец» (2026-08-30, сверено с исходниками v1.0.2) 🚨

Семантика winws2 (локальные исходники `zapret2-v1.0.2/nfq2/desync.c`
`dp_match`/`dp_find`): профили перебираются по очереди, побеждает ПЕРВЫЙ,
у которого совпали фильтр И hostlist; несколько `--hostlist` в одном профиле
ОБЪЕДИНЯЮТСЯ (hostlist.c `AppendHostList`) — запись «последний --hostlist
переопределяет предыдущие» для v1.0.2 НЕВЕРНА.

Следствие: user-списки, дописанные в КОНЕЦ аргументов, попадали только в
последний (QUIC) профиль — TCP-блоки юзер-домены не видели вообще. Теперь
`build_args_from_preset` инжектит `--hostlist=<list-include-user.txt>` и
`--hostlist-exclude=<list-exclude-user.txt>` СРАЗУ ПОСЛЕ ПЕРВОГО hostlist-
токена КАЖДОГО профиля, у которого есть hostlist (exclude дополнительно
попадает в ipset-dup сегменты юзер-IP). Пустые юзер-файлы не меняют конфиг
вообще (проверено: байт-в-байт). Верификация: 10 пресетов × 6 комбо +
dry-run winws2 — ALL OK.

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

### ⚠️ КОРРЕКТИРОВКА (2026-08-27): nodrop СНИМАТЬ МОЖНО — но нужен repeats на fake!
Найден реальный фикс youtube TCP на Т2 (SNI-блок, чёрная дыра на ClientHello):
`nodrop` на fake+multisplit оставлял оригинал с реальным SNI, идущий СЛЕДОМ за
фейком — DPI видел оба пакета и блочил. Рабочая схема (проверено 200/200/200,
7 прогонов подряд на Т2):
```
--lua-desync=fake:blob=google_tls:tcp_ts=-1000:repeats=6
--lua-desync=multisplit:pos=1:seqovl=681:seqovl_pattern=google_tls
```
- fake: БЕЗ nodrop (оригинал дропается), tcp_ts=-1000 (умирает по PAWS на
  сервере), repeats=6 (DPI видит поток фейков с google SNI и сдаётся);
- multisplit: БЕЗ nodrop и БЕЗ tcp_ts (сплит-части несут реальные данные с
  валидным TS — §14 не нарушен).
- **repeats ОБЯЗАТЕЛЕН, минимум 6**: 6 → 200 (4/4), 8 → 200, 4/2/1/0 → 000
  стабильно. Репиты — не «долбёжка», а механизм: DPI успевает увидеть
  реальный SNI в сплит-частях, если фейков мало.
- Без tcp_ts (exp-b): 000. С nodrop (0.2-эталон): 000.
  hostfakesplit (exp-c) и pos=midsld (exp-d): 000.
- Внесено в default.txt ТОЛЬКО в блок Google TCP tls (list-google). Discord и
  General TCP остались с nodrop (работают 200).
- **Тот же фикс применён к google-блокам остальных пресетов (2026-08-27):**
  fake-only (все блоки), fakedsplit (google), fake-multidisorder (google,
  fake += repeats), hostfakesplit (google), multisplit-pure/seqovl (google,
  nodrop снят). fake-disorder не тронут (механизм tls_fake_disorder иной).
  БЕЗ замеров на Т2 — пресеты под другие DPI; валидация dry-run.
- Следствие: известный «YouTube TCP-прикол» (§17) закрыт на Т2 — тестер теперь
  покажет 200, QUIC_OK-инференс станет редким.

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
8. **Диагностика: фиксы ввода в заблуждение (2026-08-27, 0.3):**
   - `service_manager.status()`: заголовок `sc query` локализован («СОСТОЯНИЕ»
     на русской Windows) → `"STATE" in line` никогда не срабатывал → служба
     всегда «остановлена». Парсим ЗНАЧЕНИЕ (`RUNNING/STOPPED` — всегда
     английское), не заголовок.
   - `_check_net`: HTTP 403 в детали объясняется («не блокировка, CDN так
     отвечает анонимным запросам»).
   - YouTube: kind `youtube`, i.ytimg.com проверяется ДО www.youtube.com;
     если youtube TCP не отвечает, но CDN доступен → «ok» с пояснением про
     QUIC-прикол, а не красный крест. Полный fail (и youtube, и CDN) → fail.
   - Зеркальный прикол (2026-08-30): i.ytimg.com по TCP режется точечно
     (DPI/DNS) при ЖИВОМ www.youtube.com — чек «YouTube CDN» помечается ok
     с пояснением «работает через QUIC», а не красным крестом (был fail
     в одну сторону; логика в _check_net, пост-проход).

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

## 23. `--lua-init` отдельным аргументом + путь БЕЗ пробелов = мёртвый парсинг 🚨 (2026-08-27)

### Реальный баг winws2 (v1.0.2)
```
--lua-init @C:\...\Zapret2GUI\lua\zapret-lib.lua   ← путь БЕЗ пробелов
```
→ цикл разбора опций winws2 **умирает сразу после этой опции**: все последующие
опции (включая `--new` и профили) молча игнорируются. Остаётся 1 профиль
`no_action` → десинк не применяется НИ К ЧЕМУ → **все пресеты дают идентичные
результаты** (ровно сигнатура Мегафона: одинаковые 20/30 у всех 8).

С пробелом в пути (`Zapret 2 GUI`) — работает. С `=`-формой — работает всегда:
```
--lua-init=@C:\...\Zapret2GUI\lua\zapret-lib.lua   ← ОК с любым путём
```

### Это переворачивает объяснение §1
Старый баг §1 «короткие 8.3 пути ломают» — на самом деле был **«пути без
пробелов»**: 8.3-имена всегда без пробелов (поэтому и ломались), а «рабочий
длинный путь» из §1 содержал пробел («Zapret 2 GUI»). Признак виноват.

### Фикс (core/launcher.py)
`build_args_from_preset` мержит пару `("--lua-init", "@...")` в одну токену
`--lua-init=@...` (пост-проход по tokens). Другие опции не затронуты
(`--blob google_tls:@path` отдельной формой — работает; `--hostlist=@...` и
`--ipset=@...` и так `=`-форма).

### Вероятная причина случая Мегафона (Чебоксары)
Путь установки без пробелов → парсинг умирал → 1 профиль → «ничего не
пробивается» (и Zapret 1 не работал — отдельный вопрос, но его результаты
тоже надо перепроверить). После фикса пользователю достаточно переустановить
новый exe и перезапустить тест.

### Проверка
- dry-run с путём БЕЗ пробелов (`Documents\GitHub\Zapret-2-GUI`) → 7 профилей ✓
- dry-run с путём С пробелами → 7 профилей ✓
- sanity тестера (`profiles_loaded ≤ 1` → engine_broken) теперь ловит такие
  установки вместо тихого «идентичных результатов».

---

## 24. Тумблер «Общий IP-обход» (ipset_catchall, 2026-08-27)

Точечная стратегия по умолчанию + опциональный catch-all, как в Zapret 1.

### Архитектура (targeted)
1. **`default.txt`** — снова точечный: SNI-списки (list-google/discord/general) +
   excludes. Без ipset. Безопасный дефолт «не трогаем то, что работает».
2. **Тумблер «Общий IP-обход»** (`AppConfig.ipset_catchall`, как
   GameFilter/DiscordVoice): при включении лаунчер ЗАМЕНЯЕТ каждый блок
   `--hostlist=@lists/list-general.txt` на catch-all:
   `--ipset=<short lists>\ipset-all.txt.gz` + `--ipset-exclude=...ipset-exclude.txt`.
   include-хостлист УДАЛЯЕТСЯ — winws2 применяет ipset и hostlist как AND
   (desync.c: `IpsetCheck` → затем hostlist), иначе catch-all не работал бы.
   `--hostlist-exclude` (list-exclude + user) остаётся.
3. **`lists/ipset-exclude.txt`** — IP-исключения (приватные диапазоны из v1);
   редактируется на странице «Списки» (`/api/ipset-exclude-list`).
4. **Autohostlist** — отдельный тумблер (динамическое точечное дополнение).

### Проверено
- OFF: 7 профилей, ipset отсутствует, 2× hostlist=list-general ✓
- ON: 4 ipset-аргумента (2 блока × ipset+exclude), hostlist удалён, 7 профилей ✓
- Все 8 пресетов валидны в обоих режимах (dry-run)
- При живом winws2 dry-run даёт «1 profile» + «already running» — НЕ баг
  (см. §23-фикс: profiles_loaded=None, sanity это обрабатывает)

### Места, где ipset_catchall прокидывается
config.py (AppConfig) → launcher.build_args_from_preset → zapret_controller.start →
server (_handle_start_zapret, _restore_protection_after_naked, _prepare_service_bat,
_handle_get/save_config) → diagnostics._check_preset. UI: тумблер на Главной +
третья карточка «IP-исключения» на странице «Списки».

---

## 25. Lite-версия на .bat (2026-08-27) — обход детектов Защитника

Полный GUI (PyInstaller onefile) триггерит облачные эвристики Защитника:
распаковка в %TEMP%\_MEI*, админ-манифест, локальный HTTP-сервер, запуск
cmd, загрузка драйвера. Локальный движок (MpCmdRun) — чист, флаги из облака.
Подпись не помогает радикально (WinDivert MS не вайтлистит принципиально).

**Решение — `python build_lite.py`** → папка `lite/` + `Windows build/Zapret2GUI-lite.zip`
(1.7 MB): winws2 + lua/blobs/lists/presets + батники, БЕЗ Python вообще
(как v1). Проверено: start.bat → ютуб/дискорд/гугл 200/200/200.

- `start.bat` — запуск default.txt (портативно через `%~dp0` — папку можно
  переносить)
- `stop.bat` — taskkill winws2
- `service-install.bat` / `service-remove.bat` — служба (sc create, как в
  service_manager)
- `_zapret_service.bat` — генерится вместе с start.bat
- Пути в батниках — `%~dp0`-относительные: `_portable_args()` заменяет
  абсолютные префиксы (long + short) в токенах `build_args_from_preset`
- `lite/` в .gitignore (генерируемый артефакт); коммитим только build_lite.py

---

## 26. Portable-версия (2026-08-27) — GUI без паковщика (официальный Python)

Ответ на поведенческие детекты Defender (`Behavior:Win32/Persistence.A!ml`,
`DefenseEvasion.A!ml` — срабатывали на Zapret2GUI.exe при установке службы и
загрузке драйвера; winws2/WinDivert сами НЕ флагятся, проверено по истории
угроз).

`python build_portable.py` → `Windows build/Zapret2GUI-portable.zip` (16.5 MB)
+ `.sha256`:
```
portable/
├── app/      <- наше приложение как .py (main.pyw, core, server, frontend, данные)
├── python/   <- python-3.13.14-embed-amd64 (pythonw.exe подписан PSF, белая
│                репутация) + pywebview 6.2.1 (pythonnet 3.1, WebView2-бэкенд)
├── install.cmd  <- создаёт ярлыки на рабочем столе и в Пуск (pythonw main.pyw)
└── README.txt
```

### Подводные камни сборки
- `. _pth` пишется с КОРОТКОЙ версией: `PY_SHORT = "".join(PY_VER.split(".")[:2])`
  = "313" — НЕ `PY_VER.replace(".", "")` (даёт "31314", не тот файл!)
- После extract ОБЯЗАТЕЛЬНО переписать `python313._pth`:
  `python313.zip / . / Lib\site-packages / import site` — иначе site-packages
  не на пути и `python -m pip` падает «No module named pip»
- get-pip.py + `pip install pywebview` (тянет pythonnet для WebView2)
- `main.py` работает без правок (frozen-ветки не срабатывают, root = папка
  приложения) + добавлена защита от отсутствия WebView2 (MessageBox вместо
  тихого падения pythonw)
- Пользовательские правки lists/presets живут прямо в app/ — их не затирает
  ничего (нет copytree-механизма из exe-версии)

### Проверено
- HTTP 200 на "/", validate_args OK, controller.start поднял winws2,
  канарейки 200/200/200
- UAC-подъём: main.py сам себя перезапускает с правами админа
  (relaunch_as_admin) — ярлыку RunAs-флаг не нужен
- Остаются поведенческие риски (служба/драйвер) — перед релизом тест на
  чистой VM с облаком (модель-рекомендация извне)

---

## 27. Блок githubusercontent на Т2 — исследование и правила (2026-08-30) 🚨

### Симптом
raw.githubusercontent.com / objects.githubusercontent.com /
release-assets.githubusercontent.com / avatars.githubusercontent.com — 000
(timeout). github.com / api.github.com / codeload.github.com (140.82.121.x) —
работают. Появилось «за ночь».

### Диагноз (проверено)
1. **Глобально GitHub жив**: check-host.net (BG/IR×2/TR) — все узлы
   коннектятся к raw за 43-205ms. Отвал локальный (Т2/РФ-транзит).
2. **IP-уровень, не SNI**: вся подсеть 185.199.108.0/22 (Fastly/GitHub):
   - `.133` (реальные IP GitHub): **полный блэкхол TCP И UDP** — все порты
     мертвы (80/443/8080/8443/22/53/21 + UDP 53 без ответа). SYN не
     завершается.
   - свободные IP диапазона (`.1`): TCP открывается, RST на TLS — но
     контента GitHub на них нет.
   - чужие Fastly-эджи (151.101.x, 199.232.x): TLS проходит, но с ОБЩИМ
     сертификатом (curl exit 60) — конфиг GitHub живёт ТОЛЬКО в .133.
3. **WARP обходит** (все хосты 200/301/404 с WARP, 000 без) — диагноз
   «блок на сети» подтверждён. WARP — рабочий обход для пользователя.

### Эксперимент с правилами zapret (все 000 — не пробиваются)
SYN-блэкхол на .133 означает: соединение не устанавливается, десинк
(TLS-слой) физически не может помочь. Матрица (2026-08-30, Т2, WARP off):
| Вариант | raw |
|---|---|
| default (github в list-general) | 000 |
| General TCP на drop+repeats=6 (как google-блок) | 000 |
| hostfakesplit SNI-спуф на google | 000 (+сломал google/youtube) |
| multisplit pos=midsld, seqovl=652 | 000 |
| fake блоб max_ru (664) | 000 |
| repeats=12 | 000 |
Порты/правила/смещения для SYN-блэкхола не существуют — «пробить»
нельзя, это не ТСПУ-фильтрация (у ТСПУ резался бы TLS, а не SYN).

### Что сделано в коде (помогает другим сетям)
- **list-general.txt**: добавлено github-семейство (15 доменов) — покрытие
  в default и всех пресетах через General-блоки (для сетей, где github
  режут по SNI, а не по IP).
- **update-check фолбэк**: raw → api.github.com contents/VERSION
  (releases/latest отдаёт 404, пока релизы pre-release). Проверено.
- **Зеркало jsDelivr** в баннере обновлений: cdn.jsdelivr.net/gh/
  TheFirstNoob/Zapret-2-GUI@main/Windows%20build/<zip> — работает на Т2
  без WARP, все 3 zip (1.7/16.5/18.2 MB) качаются полностью (лимит 20MB).
- hosts-файл от сообщества НЕ помогает: githubusercontent в нём нет,
  рабочих обходных IP не существует (64/64 проверено).

### Что НЕ трогать
`presets/test-gh*.txt` — экспериментальные, не коммитить (удалены из
рабочей папки). General TCP остался с nodrop (изменение всей схемы для
HTTP-трафика рискованно — отдельный вопрос).

### 🎯 РЕШЕНИЕ НАЙДЕНО сообществом (2026-08-30, вечер) — hosts-пиннинг на Fastly
Fastly отдаёт контент GitHub с ЛЮБОГО edge-IP (конфиг общий), DPI фильтрует
только выделенный 185.199.108.0/22. Рабочие IP (проверено на Т2, WARP off):
```
151.101.66.132   (лучший, 0.2s)   151.101.130.132  151.101.194.132
146.75.30.132    146.75.78.132    146.75.22.132    151.101.2.132
```
Пиннинг в hosts: raw/objects/release-assets/private-user-images/gist/
avatars* → выбранный IP. **Проверено: raw 200 стабильно** (в отличие от
работников — см. ниже). **`hosts.txt`** в корне репо — ПОЛНЫЙ готовый
hosts (432 строки): секции анти-блок работников (ИИ-гео), github-fix,
0.0.0.0-заглушки. Вычищен от мёртвых записей (2026-08-30): 77 строк 000
удалены (по-доменный пробинг curl --resolve, параллельно 16).
Скрипты-генераторы в репо НЕ храним (решение: отдавать сам файл hosts —
чище и позволяет обновлять его). Ранее написанный github-hosts-fix.ps1
удалён, hosts-github-fix.txt заменён на hosts.txt.
Дополнено (из hosts сообщества Zapret 1): media/camo/cloud.githubusercontent.com
и avatars6-8 — тоже пиннятся на Fastly (проверены: отвечают). IPv6-записи
(2606:50c0::154, фикс #17088) НЕ включаем: у сетей с IPv6 GitHub и так
работает по AAAA; на Т2 IPv6 нет. Discord-пиннинг (162.159.x) НЕ включаем:
на Т2 Discord и так 200, а 162.159.136.232 флакал (timeout) — пин на
флакующий IP хуже отсутствия. Telegram-записи на 149.154.167.220 удалены
(мёртв на Т2; у других сетей может работать — их hosts свой).
⚠️ Запись в hosts АТОМАРНО (temp + MoveFileEx): FileMode::Create на
живой файл ОПАСЕН — при аборте hosts усекается до 0 байт (случай
2026-08-30). Урок чистки: запись на мёртвый IP ХУЖЕ отсутствия записи —
напр. gemini на 62.133.62.97 (мёртв) давал 000, без записи — 200.

### ⚠️ Урок: работники ИИ «моргают» — чистка ≠ удаление гео-записей
Gemini/aistudio/notebooklm пиннились на 62.133.62.97 (спец-работник Google
AI, эгресс LA). 2026-08-30 IP умер → записи удалены при чистке → gemini
упал на прямой RU-эгресс → «регион не поддерживается» (страница грузится
200, но гео-детект!). **200 при пробе НЕ значит «гео ок»**.
Решение: перепин на живой общий работник 45.155.204.190 (проверен: gemini
200, aistudio 302, notebooklm 301) — секция «Google AI geo» в hosts.txt.
Правило: при чистке «мёртвых» записей работников — СНАЧАЛА пробовать
другой живой работник, удалять гео-записи нельзя (иначе ломается гео-обход).

### AI-работники в hosts — ФЛАКАЮТ
45.155.204.190 (и др.) — «работник» для ChatGPT/Gemini/Claude (гео-обход,
не РКН). Один и тот же IP отвечает по-разному в пределах минут: через
--resolve 200, через hosts 403/000. Это известное поведение («утром
работает, ночью отвал») — IP периодически обновляет сообщество.
Базовый hosts восстановлен из `Latest hosts.txt` (474→509 строк с
секциями по IP) + github-fix. Бэкап: hosts.bak (осторожно: старый bak
может быть 14-байтным мусором от прерванной записи).

### Контекст блокировок (форум Zapret 1, 2026-08-30)
- Ростелеком = РДП.РУ (разработчик фильтров для РКН) — блокировки
  «кривые», плавающие во времени (утро/день/ночь отличаются).
- GitHub-блок решается hosts-пиннингом (выше) или WARP; jsDelivr — зеркало.
- YouTube на РТК «через раз» → отключение QUIC в браузере помогает
  (chrome://flags → Experimental QUIC protocol → Disabled).
- DNS 9.9.9.9 / 149.112.112.112 заметно улучшает загрузку видео на РТК.

---

## 28. Обзор идей из открытых MIT-проектов на GitHub + внедрённое (2026-08-30) 🚨

Запрет 2 MIT — идеи и подходы из других открытых GUI-проектов для zapret
изучаем открыто и внедряем своими руками (код не копируется: наш стек
Python+webview, чужой — C#/WPF). Сильные общие паттерны в экосистеме:
цикл «кандидат → РЕАЛЬНАЯ проба winws2 → скор → артефакт» (автоподбор
стратегии: одноразовый движок-пробник, готовность по строке лога
«capture is started», параллельные TLS1.2/1.3/GET пробы, взвешенный скор),
генератор персональной стратегии (пул TLS-бандлов, скор Discord/YouTube
отдельно + проверка собранного комбо целиком), честный baseline (доступность
БЕЗ обхода), память по сетям, трансформация аргументов при старте
(токены + QUIC-off/game-filter/scope). Слабости чужих подходов: монолит
160+ MB, хардкод доменного ноу-хау, встраивание чужого кода (прокси/MASQUE)
внутрь exe — в наш MIT-репо не тащим.

### Осознанно НЕ берём (обоснование)
- **Авто-лечение** (TLS-проба каждые 45с): у нас autohostlist уже решает
  блоки, а постоянные TLS-стуки — подозрительный паттерн для AV и игровых
  провайдеров. Блоки РФ — редкие события, лечатся по требованию.
- **Память по сетям (fingerprint)**: хранение + идентификация (ARP/IPv6/
  смена DHCP/шлюза) + ложные совпадения — ради экономии ~3 секунд выбора
  пресета. Тестер и так даёт вердикт за секунды. Выгоды нет.
- **Job Object**: наш запуск через bat (winws2 — внук cmd) делает его
  хрупким; убийства по имени image уже покрывают восстановление.

### Внедрено (проверено на Т2, 2026-08-30)
- **`core/tcp_timestamps.py`**: состояние timestamps. ВАЖНО: на Win11
  реестр Tcp1323Opts=0x2 ВРЁТ (legacy) — авторитетен шаблон NetTCPSetting
  (`Get-NetTCPSetting -SettingName Internet → Timestamps`), на нашей машине
  timestamps уже Enabled → tcp_ts=... работает. Проверка: modern → legacy
  фолбэк. Включение: Set-NetTCPSetting, фолбэк netsh. Хуки: controller.start
  (замечание в сообщении «Запущен»), service_manager.start.
- **`core/conflict_scan.py`**: сканер окружения. Жёсткий конфликт = чужие
  DPI-тулзы (winws.exe=Zapret1, byedpi, goodbyedpi, spider, fpwin, intosy);
  warning = VPN-клиенты/службы (state= active! не all — иначе ложные срабаты
  на остановленных) + туннельные адаптеры. Хук: diagnostics.py чек «env»
  (fail/warn/ok) + чек «tcp_ts».
- **`validate_lua`** (launcher): второй проход `--intercept=0` — реально
  компилит lua-init (--dry-run Lua НЕ грузит, опечатка в zapret-custom.lua
  проходила). Встроен в validate_args (все 3 вызова). Проверено на всех 9
  пресетах.
- **DNS-здоровье в диагностике** (чек «dns_health»): системный резолвер +
  DoT 853 (TCP-коннект) + DoH 443 (dns-json). Блоки плавают — чек честно
  показывает текущее состояние (на Т2 DoT то жив, то мёртв).
- **auto.txt (9-й пресет)**: circular по сегментам default (fails=3,
  retrans=2). Дуэль на Т2: default 92.3% / auto 92.3% / auto со сломанной
  strategy=1 84.6% → механизм переключения РАБОТАЕТ (рекавери со слабой
  стратегии), но на Т2 не даёт выигрыша. Фолбэк для сетей, где default не
  бьёт (тестер пользователя решает). Эксперименты test-auto*.txt удалены.
- НЕ внедряли пока (кандидаты на следующую итерацию): автоподбор кандидатов
  с реальной пробой, генератор стратегий, трансформация аргументов при
  старте (у нас токены/тогглы уже в лаунчере, но scope-трансформаций нет).

---

## DNS

Яндекс.Браузер и аналоги принудительно подменяют DNS на 77.88.8.8.
Блокируют любые сторонние DoH. Тестировать в Firefox/Chrome.

---

## Killer NIC

Killer Network Interface Controller конфликтует с WinDivert.
**Симптомы:** zapret запускается, но пакеты не обрабатываются.
**Решение:** отключить Bandwidth Control в Killer Control Center.
