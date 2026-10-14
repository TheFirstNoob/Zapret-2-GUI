# @config_file у winws2 — исследование (14.10.2026, ред. 2 — МЕХАНИЗМ РАСКРЫТ)

> **Статус: механизм раскрыт и подтверждён исходниками + эмпирикой. НЕ внедрено.**
> Цель: снять потолок длины командной строки — вместо ~5000 символов аргументов
> передавать `winws2 @file` (~50-100 символов). На службе — binPath ~80 символ.

## 1. ГЛАВНОЕ (TL;DR)

**На Windows `@file` раскрывает не zapret, а РАНТАЙМ CYGWIN — до вызова main().**

- Код: `cygwin1.dll`, `winsup/cygwin/dcrt0.cc`: `build_argv()` → `insert_file()`
  (комментарий в исходнике: «Replaces @file in the command line with the contents
  of the file. There may be multiple @file's in a single command line. A \@file is
  replaced with @file»).
- Условие раскрытия (`build_argv`, строка 339): слово начинается с `@` И это не
  первое слово (argv[0]) И перед `@` не было кавычки (`sawquote != word`).
- Файл читается ЦЕЛИКОМ (`CreateFileW`+`ReadFile`, malloc «до ~4ГБ» — комментарий
  самого Cygwin), содержимое ВСТАВЛЯЕТСЯ в командную строку (байты + пробел + остаток
  original cmdline) и **пересканируется тем же парсером** → работает рекурсия
  вложенных @file, лимит вложенности **`MAX_AT_FILE_LEVEL = 10`**.
- Следствия: @file работает в ЛЮБОЙ позиции; можно несколько @file; можно мешать с
  обычными аргументами; лимит размера на Windows — ~4ГБ (НЕ 16КБ!); запись
  `"@file"` (кавычка ПЕРЕД @) — НЕ раскрывается; `@'file'`/`@"file"` (кавычки
  вокруг пути, @ СНАРУЖИ) — раскрывается, кавычки снимаются.
- Содержимое парсится cmdline-парсером Cygwin (не wordexp!): пробелы/табы —
  разделители; `"` — кавычки всегда; `'` — кавычки когда родитель не-Cygwin
  (наш случай и служба: SCM/python — не Cygwin → winshell=true); бэкслеши
  литеральны; при winshell=true работает `globify()` → символы `*?[]` в НЕ
  закавыченных словах могут раскрываться как glob (кавычить сегмент, чтобы
  подавить); слова, начинающиеся с `@` внутри контента, ТОЖЕ рекурсивно
  раскрываются (не эмитить случайные `@path`-токены).
- **Zapret-собственный путь** (`nfqws.c:2297`: argv[1]-фастпат + `config_from_file`
  с `wordexp`, буфер 16КБ, help «must be the only argument») — это **Linux-путь**.
  На Cygwin он срабатывает ТОЛЬКО когда рантайм пропустил @ (т.e. `"@file"` или
  `$file`), и на реальном конфиге **wordexp ПАДАЕТ** («failed to split command
  line options from file» — т.е. путь нерабочий). 16КБ-буфер на Windows НЕ
  действует: проверено файлом 275885 байт.
- `$file` на Windows НЕ работает (Cygwin раскрывает только `@`; `$` уходит в
  битый wordexp-путь zapret). Использовать только `@`.

## 2. Эмпирика (ключевая; песочницы %TEMP%\opencode\argfile*, C:\Users\Public\argfile_test)

| Тест | Что | Результат |
|---|---|---|
| M1/B/C | `[--dry-run, @conf]`, `[--dry-run, --comment=x, @conf]` | ✅ раскрытие с позиций 2 и 3, мешается с другими аргументами |
| M3/M4/E | `[@conf]` ✅ / `[$conf]` ❌ «failed to split» | @ работает, $ — нет |
| T7a | unquoted `@conf` ✅ / quoted `"@conf"` ❌ «failed to split» | кавычка перед @ отключает раскрытие (уходит в битый wordexp) |
| T7b | 30КБ `--comment`-паддинга ПЕРВЫМИ + валидный хвост | ✅ rc=0 verified → обрезки 16КБ НЕТ (читает Cygwin целиком) |
| S2/W256K | файл 18265Б / 275885Б | ✅ rc=0 verified |
| T7c | @file → @file (вложенность) | ✅ rc=0 verified (лимит 10) |
| T7f | `@8.3-короткий-путь` | ✅ rc=0 |
| T7g | `@"C:\...\arg file\sp conf.txt"` и `@'...'` (кавычки вокруг ПУТИ) | ✅ rc=0 verified — ПРОБЕЛЫ В @-ПУТИ РЕШАЮТСЯ кавычками от @ |
| T7g | `@C:\...\arg file\sp conf.txt` без кавычек | ❌ слово рвётся по пробелу |
| Q0-Q5f | hostlist (БЕЗ @!) с пробелом: unquoted ❌; SQ/DQ (токен/значение/форвард) | ✅ все кавыченные варианты rc=0 |
| L0-L5 | `--lua-init=@<путь с пробелом>`: unquoted ❌; SQ/DQ варианты | ✅ все кавыченные rc=0 |
| H0-H6 | `--chdir=<путь с пробелом>`: unquoted → «chdir: No such file or directory» (rc=1); SQ/DQ (весь токен/значение) → ✅ парсится и ПРИМЕНЯЕТСЯ (относительный lua под chdir найден) | все кавыченные варианты рабочие |
| V3/V4 | два токена на строке / CRLF | ✅ |
| C5-аномалия | `--chdir` с пробелами без кавычек = 0xC0000142 (вчера) | ❗ сегодня НЕ воспроизводится (чистый rc=1); помнить как аномалию |
| T8 | unicode-путь конфа: LIST-форма `"@...конфиг тест.txt"` ❌ (та же кавычка-ловушка); raw `@"конфиг тест.txt"` | ✅ rc=0 verified (кириллица в @-пути работает) |
| T8 | cmd/bat-контекст: `winws2.exe @"C:\...\arg file\sp conf.txt"` из .bat | ✅ rc=0 verified (Этап 2 валиден) |
| T8/T10 | `--debug=@file` ВНУТРИ конфига | ✅ rc=0, лог-файл пишется (1589-4398Б, реальные строки) |
| T9 | Служба: binPath `"winws2.exe" @C:\ProgramData\Zapret2\probe.conf` | ✅ start rc=0 RUNNING, debug-лог создан LocalSystem'ом, stop/delete чисто |
| T9/T10 | Служба: binPath `"winws2.exe" @"C:\ProgramData\Zapret2\probe conf.txt"` | ✅ cmdline процесса перехвачена WMI — SCM передаёт аргумент ВЕРБАТИМ; winws2 RUNNING (первый замер дал ложный 1053 — dup-mutex артефакт, см. §5) |
| T11 | Этап 1 (внедрён): golden argv vs conf — REPO и MIRROR(пробелы) | ✅ SAME=True (8+verified / 9+dup-mutex-квирк); validate=True; живой direct `@file` на пробельном MIRROR: alive + curl 200; sink поймал вывод падения |
| T13 | Этап 3 (внедрён): живая миграция службы зеркала на conf | ✅ binPath 3854→151 симв; golden conf==legacy args (117/117); RUNNING + curl 200; бэкап старого binPath в `mirror/logs/` |
| T14 | write_run_bat через conf (`start /min exe @"conf"`) | ✅ rc=0, debug-лог пишется, левых winws2 нет |

Побочно: лог winws2 показывает пути урезанно (`/lists/...`) — косметика;
`--comment` в контенте не мешает; `--hostlist=` принимает ТОЛЬКО обычный путь
(форма `@path` даёт «cannot access hostlist file '@...'» — `@` у hostlist не
использовать); `--lua-init=@` — правильная форма.

## 2.5 Исторический июльский баг (`--lua-init @path`) — та же ловушка

Лаунчер когда-то эмитил lua-init ДВУМЯ токенами: `--lua-init` + `@<path>`.
Второй токен НАЧИНАЕТСЯ с `@` → Cygwin раскрывал его как response-файл: в argv
попадало не содержимое аргумента, а СОДЕРЖИМОЕ zapret-lib.lua (мусорные токены):

- путь БЕЗ пробелов → Python не кавычил `@path` → Cygwin раскрывал → ЛОМАЛОСЬ;
- путь С пробелами → Python кавычил `"@path"` → Cygwin пропускал → работало;
- фикс `ae5536d` (27.08): слить в ОДИН токен `--lua-init=@<path>` — слово
  начинается с `-`, Cygwin не трогает (проверка `*word == '@'`), zapret читает
  optarg сам. Это и есть источник августовской ре-атрибуции «spaceless paths
  broke» (commit-сообщение ae5536d).

Вывод: **ни один токен в argv/конфиге не должен НАЧИНАТЬСЯ с `@`** (кроме
осознанного одиночного `@file`-запуска). Все наши токены — `--opt=value`.

## 3. Рабочие правила (для миграции)

1. Запуск: `winws2 @<conf>` (путь без пробелов) ИЛИ `@"<conf>"`/`@'<conf>'`
   (путь с пробелами; @ ВНЕ кавычек!). Кавычки перед @ (`"@conf"`) — НЕЛЬЗЯ.
2. Контент: полные пути 8.3-короткие (как сейчас у лаунчера) ИЛИ обычные пути с
   кавычками (DQ-стандарт) при пробелах; без кавычек токены с пробелами рвутся.
3. `hostlist/ipset` — обычные пути; `lua-init` — `@`; `chdir` — кавычить при пробелах.
4. Опции-значения с `@` (например `--lua-init=@...`) Cygwin НЕ трогает (слово
   начинается с `-`) — там всё как раньше.
5. Все токены — только формы `--opt=value` / `--opt`+`value`; НИКОГДА не
   эмитить токен, начинающийся с `@` (Cygwin раскроет его как вложенный
   response-файл / исторический баг `--lua-init @path`, см. §2.5).
6. Размер: до ~4ГБ (по коду), держать разумным; 16КБ-лимит zapret'а на Windows
   не действует (но действует на Linux — если когда-то порт — помнить).
7. `--dry-run` можно и ВНУТРИ файла, и как отдельный argv (смешение работает);
   конвенция миграции: dry-run внутри файла.
8. `$`-вариант на Windows — НЕ использовать (сломан).

## 4. Миграция (Этап 1 — ✅ ВЫПОЛНЕН 14.10; этапы 2-4 ждут)

**Этап 1 (внедрён, `core/launcher.py`; tester подключён тем же `launch_winws2`):**
- `write_run_conf` → `logs/run.conf` (токен на строку, LF, UTF-8; токены с
  пробелами — DQ; атомарно tmp+os.replace).
- `_winws2_raw_cmdline` → `"exe" @"conf"` (кавычки вокруг пути, @ снаружи).
  Лаунчер/тестер запускают `winws2 @run.conf` — лимиты длины cmd сняты;
  прямой argv-путь заменён.
- `validate_args`/`validate_lua` — временный conf в TEMP, `--dry-run`/
  `--intercept=0` ВНУТРИ файла.
- stderr-sink: stdout+stderr winws2 → `logs/winws2_last_stderr.log` (не PIPE!);
  при падении direct — head+tail в applog. (Хвост ревью — ✅.)
- env запусков: `LANG/LC_ALL=C.UTF-8`. (Хвост ревью — ✅.)
- Golden: argv-форма vs conf-форма идентичны — REPO (8 профилей + verified);
  MIRROR с пробелами (9 профилей; пойман pre-existing квирк: при службе с ТОЙ
  ЖЕ стратегией dry-run обрывается dup-mutex'ом «A copy of winws2 is already
  running with the same filter» — старое и новое поведение совпадает).
  Живой тест: служба стоп → direct @file на пробельном MIRROR → alive +
  curl 200 → kill → служба RUNNING.

**Этап 2 (bat/build_lite):** в bat только `winws2.exe @"<conf>"` (проверить
пробельный корень в lite-сборке).
**Этап 3 (служба — ✅ ВЫПОЛНЕН 14.10):** binPath = `"exe" @"<root>\logs\service_run.conf"`
(у живой службы зеркала 3854 → 151 симв); `install`/`reconfigure` пишут
`service_run.conf` и меняют короткий binPath (Win32 API; sc-bat — транспорт
`@\"conf\"`); **legacy-миграция**: `migrate_if_needed()` парсит старый binPath
(CommandLineToArgvW) → conf → ChangeServiceConfigW → verify → restart, если
служба была запущена; зовётся и из `start(args=None)`. `updater.service_args_stale`
сравнивает содержимое conf-файла. Живой прогон: golden conf==старые args
(117/117), RUNNING + curl 200; бэкап старого binPath в
`mirror/logs/binpath_legacy_backup.txt` (откат `t13_rollback.py`).
**Этап 4 (зачистка):** sc-bat fallback/`_verify_binpath`, ImagePath-чек в
`status()`, timestamps без PS + вызов из тестера, CDN service-ветка.

## 5. Что осталось проверить (точки продолжения)

1. ✅ **PoC службы ВЫПОЛНЕН (14.10)**: обе формы binPath рабочие —
   `"winws2.exe" @C:\ProgramData\Zapret2\probe.conf` (служба zapret2probe:
   start rc=0, лог 4398Б, stop/delete чисто) и `@"...probe conf.txt"` (пробел;
   cmdline перехвачена WMI — SCM передаёт аргумент вербатим). Боевая `zapret2` не
   тронута. ⚠ АРТЕФАКТ: последовательные пробы с ОДИНАКОВЫМ wf-фильтром ловят
   dup-mutex («A copy of winws2 is already running with the same filter») → ложный
   1053; при повторных тестах менять фильтр либо ждать полного останова.
2. Аномалия 0xC0000142 (вчерашний краш unquoted-chdir) — не воспроизводится;
   при случае поймать ещё раз.
3. Юникод/не-ASCII — ✅ проверено (T8: кириллица в @-пути через `@"..."` ок).
4. (Если когда-нибудь Linux-порт) — контент под wordexp-семантику отличий.

## 6. Хвосты ревью 14.10 (первые два — ✅ сделаны в Этапе 1)

- ✅ **Перехват stderr winws2 в файл** — ВНЕДРЕНО: stdout+stderr →
  `logs/winws2_last_stderr.log` (не PIPE!); при падении direct — head+tail в applog
  (ранний getopt-вывод пишется в НАЧАЛО файла — читаем оба конца).
- ✅ **`LANG=C.UTF-8`/`LC_ALL=C.UTF-8`** — ВНЕДРЕНО в env всех запусков winws2.
- **TCP timestamps**: убрать PowerShell из горячего пути (netsh по коду возврата;
  чтение — локализация!); вызывать и из тестера (heisenbug «тест работает после
  обычного запуска»).
- **Служба (остаток)**: sc-bat fallback оставлен осознанно (транспорт для кривых
  SCM, теперь `@\"conf\"`); `_verify_binpath` переписан под @conf; НЕ сделаны:
  ImagePath-чек в `status()` (PATH_MISMATCH) и порядок 1072 (закрыть HANDLE +
  убить winws до delete) — отдельная задача.
- **CDN-ручки**: service-ветка (U1 из внешнего ARCH_REVIEW) — ждёт VM-теста.

## 7. Артефакты и ссылки

- Код-источники: `%TEMP%\opencode\cyg_dcrt0.cc` (Cygwin dcrt0.cc master — insert_file
  стр. 87-146, build_argv 294-366, MAX_AT_FILE_LEVEL 40); `up_nfqws_v105.c` /
  `up_nfqws_master.c` (upstream **идентичны** и идентичны zip-сорцам);
  `zapret2-v1.0.5\` (распакованный релиз; наш bin/winws2.exe = релизный бинарь,
  sha256 A2535593...).
- Тест-скрипты: `argfile_test5.py`, `argfile_test6.py`, `argfile_test7.py`,
  `argfile_test7g.py`, `argfile_test8.py`, `argfile_test9_service.py`,
  `argfile_test10.py`, `t11b_stage1.py`, `t12_mirror_dry.py`, `cygwin_probe.py`;
  отчёты `argfile_results5/6/7/7g.txt`, `cygwin_probe_results.txt`,
  `t8_unicode_dbg_cmd.txt`, `t9_service_poc.txt`, `t10_a2b_probe2diag.txt`,
  `t11b_stage1.txt`, `t12_mirror_dry.txt`; песочницы `%TEMP%\opencode\argfile\`,
  `C:\Users\Public\argfile_test\` (+ `arg file\`).
- Внешнее ревью (НЕ коммитим, решение 14.10): зеркало
  `AI_DOCS\ARCH_REVIEW_2026-10-14.md` — 3 «срочных» (2 починены в `053af51`,
  CDN-service-ветка — нет).
- Починено в `053af51`: guard `content` в save-list, try/finally в portable-апдейте,
  `discord_alt` в CDN apply-all, `pause_recovery`; AGENTS §Риск-свип + релиз-чеклист.
