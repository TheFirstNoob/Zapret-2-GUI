# AGENTS.md — Критические находки (чтение обязательно перед любыми изменениями)

> **Последнее обновление: 2026-09-13 (Pre-Release 0.8 — релиз-подготовка; UI-ветка влита)**
> **Размер EXE:** 19.4 MB. Сборки актуальны (build.py / build_portable.py / build_lite.py).
> **Статус:** `default.txt` — универсальная стратегия; Discord-блоки на repeats=8.
>
> **Эта информация теряется при сжатии контекста ИИ.**
> Новый агент ДОЛЖЕН прочитать этот файл перед редактированием кода или тестированием.

---

## ⚡ СЕССИЯ-СНАПШОТ (читать первым)

### Текущее состояние (2026-09-13)
- **VERSION = "Pre-Release 0.8"** (config.py; релизы 0.7/0.7.1 на GitHub; сборки 0.8 пересобраны 2026-09-13 — updater/settings/heal/UI/frozen-fix вошли).
- **Пресеты: 11 release** (default, default-alt, auto, fake-only, fakedsplit,
  fake-disorder, fake-multidisorder, hostfakesplit, multisplit-pure,
  multisplit-seqovl, tcpmd5-fake) + exp-/cand- стенды (скрыты из GUI и дистрибутивов).
  Discord-блоки (Media TCP + TCP tls) на **repeats=8** в default и default-alt
  (утром 7 → 000, 8 пробивает; порог плавает — 8 = запас).
- **Тестер:** 18 хостов (RATED 11 + CONTROL 7). QUIC-класс (www.youtube.com,
  youtu.be, i.ytimg.com, redirector.googlevideo.com, storage.googleapis.com)
  **ИЗ network_rate исключён** (синхронно core.tester.QUIC_QUIRK_DOMAINS и
  frontend QUIRK_HOSTS): их 000 — свойство TCP-пробы «чужим клиентом» под
  десинком, браузер ходит через QUIC → статус «≈ QUIC» (серый), не BLOCKED.
  Best tie-break по net_ok_count. Live-счётчики = rated-флаг бэкенда.
  Финиш: «Профиль завершён: сеть N/N (X%), всего проверок N». Мёртвые для
  нас пресеты (fake-only 0-12% на Т2) — НЕ мусор (правило 8), прогон не укорачивать.
- **Диагностика:** сетевые пробы параллельно (10 потоков, ~6с). Для 000:
  HTTP-80 фолбэк (жив = «интернет работает», ok); QUIC-квирк → warn
  («проверьте в браузере»); иначе classify_block (sni_block = «движок обязан
  брать»). Discord-аплоад-хост вычеркнут из чеков (клиентский QUIC-путь curl
  не измеряет). Госуслуги-инцидент: ТСПУ SYN-дропит подсеть 213.59.x в голую —
  не «стратегия ломает»; детект «ломает живое» = canary жива + RU-хост мёртв.
- **Probe (анализ приложения)** — отдельная страница: pktmon-захват НЕ
  запускается без UDP-портов процесса (иначе ALL-UDP мусор); вердикт
  «UDP: отправлено N, входящих 0 — глушится, WARP»; домены (DNS-cache) в вердикте.
- **Служба zapret2 = winws2.exe напрямую** (start=auto): SCM-recovery
  (sc failure: restart 60с ×3), binPath-верификация после sc create,
  service-bat в OEM (ascii падал на кириллице), sc через временный .bat.
- **Статика**: Cache-Control no-store + app.js?v=<mtime> и css/app.css?v=<mtime>
  (WebView2 кэш больше не топит правки фронтенда).
- **Спорные домены** — страница «Списки»: тумблер «В обход» (правит
  list-include-user.txt) + живая curl-проба (жив в голую → держи выключенным;
  глушится → включи; мёртв с десинком → WARP). amazonaws.com: только тумблером,
  НЕ правкой list-general.
- **0.8 WIP (не закоммичен агентом, сохранён в `79bcce4`)**: предупреждения
  «место запуска» — из архива (%TEMP%), Загрузки (MOTW), Документы (OneDrive),
  рабочий стол (замусоривание): `main.py::_check_launch_location` (MessageBox)
  + `core/diagnostics.py::_check_launch_spot` (чек «launch_spot») + `known_desktop_dir` в utils.
- **Сборщики:** build.py (exe), build_portable.py (portable), build_lite.py (lite).

### Правило честности измерений 🚨 (критично для тестера/диагностики)
Измерение «чужого TLS-клиента» (curl/openssl/stdlib) сквозь движок ≠ реальный
опыт: браузеры ходят через QUIC/свой TLS, google-блок (fake+multisplit) рвёт
сторонний ClientHello. Симптомы: «тестер говорит ютуб не работает» / «диагностика
красная» при рабочем пользователе. Все подобные измерения: (1) не в rate/вердикт
без пометки; (2) нейтральный статус (QUIC/warn/skip), не красный; (3) HTTP-80
фолбэк для «интернет жив»; (4) реальный опыт = браузер/клиент. UDP-путь: sent/recv
разница из pkt-захвата.

### Критичные правила (нарушение = поломка)
1. **`--lua-init` ТОЛЬКО в форме `--lua-init=@path`** — отдельным аргументом
   с путём без пробелов парсинг winws2 умирает (см. §2). Лаунчер делает сам.
2. **Имя блоба НЕ начинать с цифры** (`fake:blob=2gis_tls` → фейки МОЛЧА не
   шлются, 0 пакетов в захвате; `g2_tls` → работает). Видно только в pktmon.
3. **nodrop на google-блоке default — НЕ ставить** (ютуб-фикс = drop+repeats=6,
   §6). General TCP — с nodrop, НЕ менять вслепую.
4. **Запись в hosts ТОЛЬКО атомарно** (temp + MoveFileEx; FileMode::Create на
   живой hosts при аборте усекает до 0 байт). После замены из %TEMP% —
   перевыдать ACL: `icacls hosts /grant "*S-1-5-20:(R)"` (NetworkService),
   иначе DNS Client молча игнорирует hosts. Лучше — in-place Append (не трогает
   ACL и watcher).
5. **Гео-записи работников НЕ удалять без замены** на живой IP (200 при пробе
   ≠ гео ок: gemini на мёртвом 62.133.62.97 упал на RU → гео-детект).
6. **Кодировка — UTF-8 БЕЗ BOM** (PS 5.1 ломает: чтение ANSI, `>` UTF-16,
   -Encoding UTF8 = +BOM). Правки только Write/Edit; восстановление —
   `git checkout <rev> -- <file>`.
   - Исключения: `build_lite.py` пишет `test.ps1` с utf-8-sig (PS 5.1 читает
     кириллицу только с BOM); **.bat/.cmd** — cmd читает в кодовой странице
     консоли: кириллица только с `chcp 65001 >nul` + UTF-8 без BOM + **CRLF**
     (или чисто ASCII); LF ломает батники.
   - Пресеты/списки код читает через `utf-8-sig` (BOM-безопасно), но хранить
     без BOM. Вывод утилит с кириллицей: не гнать через PS-кмдлеты (cp866);
     при необходимости — `[Console]::OutputEncoding=[Text.Encoding]::UTF8;`.
7. **Списки: точечность над широтой** — фильтровать только реально блокируемое
   (google.com сам 200 в голую). Родительский домен — только когда заблокировано
   семейство целиком (storage.googleapis.com; amazonaws.com — ОТМЕНЁН, §9).
   Перед расширением взвесить «покрыть весь домен» vs «точечно». Комментарии
   в list-файлы не писать.
8. **Результаты тестов привязывать к провайдеру** — «не сработало на Т2» ≠
   «мусор» (oob/syndata 30–46% на Т2 — кандидаты для других сетей). Каталог —
   STRATEGY_TRIALS.md; проигравший пресет НЕ удаляем.
9. **Правки пресетов/списков — в репо** (Documents\GitHub\Zapret-2-GUI),
   Desktop-копия синхронизируется коммитами.

### Блокировки РФ (плавающие)
- **githubusercontent (185.199.108.0/22) — блок по IP** (SYN-блэкхол, zapret
  бессилен): hosts-пиннинг на Fastly-эдж (151.101.66.132, запасные в `hosts.txt`)
  или WARP. Глобально GitHub жив (check-host.net).
- **AI-работники** (45.155.204.190 и др.): гео-обход chatgpt/gemini/claude,
  ФЛАКАЮТ (утро/день/ночь, 1-12с). cdn.oaistatic НЕ пиннить.
- **DoT (853) заблокирован, DoH (443) жив, plain UDP53 жив** на Т2.
- **YouTube РТК «через раз»** → отключить QUIC в браузере; DNS 9.9.9.9.
- **YouTube «нет интернета» при открытой странице (SkyNet/Т2, 2026-09-13)**:
  браузерный DoH-резолвер отдавал недоступные кэш-серверы googlevideo.
  Фикс юзера: сменить DoH-провайдера ВНУТРИ браузера (Opera GX: настройки →
  Конфиденциальность → DoH; Chrome/Edge: secure DNS; Firefox: DoH) — Quad9 →
  Cloudflare → выключить. Актуально для всех браузеров с встроенным DoH —
  резолвер влияет на выбор кэш-сервера YouTube. Системный DNS с той же логикой.

### ВИСИТ (не сделано)
- Аудит-клининг 2026-09-13 (закрыт): дедуп `_sc`/`_winws2_running` →
  `core.utils.run_sc`/`winws2_running`; мёртвое вычищено (`ensure_admin`,
  `stop_all_instances`, `get_path`; `restore_after_engine` — сломанный no-op);
  `_check_launch_spot` подключён в диагностику; `_check_windivert_service`
  переведён на общие ридеры `core.utils.windivert_service_state`/
  `windivert_image_dead`, советы «sc delete» заменены на «Починить»
  (delete при живом драйвере даёт marked!). kill-хелперы (tester/server/
  service_manager) НЕ сливал — контекст-специфичны. `windivert/` — НЕ хвост:
  часть апстрим-поставки Zapret 2 (как lua), пока не изучена, оставляем.
- UI (2026-09-13): навигация перестроена — 3 основных пункта (Главная /
  Проверка системы / Подбор стратегии) + сворачиваемая группа «Экспертные
  инструменты» (списки/спорные/CDN/ASN/проба), авто-раскрывается на активной
  экспертной вкладке. На главной: карточка «Быстрый старт» (3 шага; флаг
  `tour_done` в конфиге — после закрытия не показывается) и строка отдачи
  `#z2Feedback` + кнопка «Проверить работу». Панели службы/тогглов лишены
  accent — один визуальный приоритет (панель обхода). Дальше при желании:
  coach-marks по шагам поверх карточки.
- Frozen-баг службы (НАЙДЕН и ИСПРАВЛЕН 2026-09-13; он же «_MEI после
  установки службы» из жалоб 0.7.1): в onefile-EXE `Path(__file__)` = временная
  `_MEI*`, поэтому `reconfigure()` при каждом «Запустить службу» перезаписывал
  binPath службы на `%TEMP%\_MEI…\bin\winws2.exe`; winws2 службы держал папку →
  при закрытии «Failed to remove temporary directory _MEI…», а служба оставалась
  с мёртвым путём (автозапуск ломался — класс кейса друга). В 0.7.1 лечили
  только следствие (очистка старых _MEI при старте + FAQ). Фикс:
  `core.utils.app_root()` (frozen → каталог exe) во всех точках службы +
  guard «winws2 вне каталога программы» в install/reconfigure. Старым
  установкам лечится переустановкой службы (0.8: updater пометит service_mismatch).
- Прозрачность (2026-09-13): first-run карточка `#noticeCard` (флаг
  `notice_done`): что делает / данные / сеть; README-раздел «Прозрачность»;
  lite README.txt дополнен честным блоком («что делает / чего не делает»);
  в consent-модалке уточнено «отчёт сохраняется локально». Задача: доверие
  (антивирусы/подозрительность к EXE), конкурентов не догоняем — делаем чисто.
- Lua-файлы (2026-09-14): используются 4 — `zapret-lib.lua` (база),
  `zapret-antidpi.lua` (desync), `zapret-auto.lua` (circular), `zapret-custom.lua`
  (сборка тестера) — пресеты ссылаются через `--lua-init`/`--lua-desync`.
  Осознанно НЕ используем (файлы остаются во всех дистрибутивах, не удалять):
  `zapret-obfs.lua` — wgobfs/ippxor, обфускация туннелей WireGuard: требует
  zapret на ОБОИХ концах + свой сервер, аудитория не наша, не выводим;
  `zapret-pcap.lua` — dev-дамп пакетов в .pcap из движка (рецепт:
  `--writable=<dir>` + `--lua-init=@lua/zapret-pcap.lua` +
  `--lua-desync=pcap:file=x.pcap`) — для глубокого разбора новых стратегий;
  debug-лог (`--debug=@debug_winws2.log`, наш тумблер) его НЕ заменяет
  (текстовые решения vs сырые пакеты), но pktmon-тулзы покрывают «что ушло
  в сеть»; `zapret-tests.lua` — самотесты lua-библиотеки, только для
  обновлений lua из апстрима.
- Ревизия параметров winws2 по мануалу v1.0.5 (2026-09-14; наш bin — РОВНО
  v1.0.5, 0b8182d): **hostlist/ipset-файлы перечитываются НА ЛЕТУ** (проверено
  живым тестом: правка файла без рестарта → `Loaded 2 hosts` + `hostlist check
  : positive` → `desync profile N matches`; удаление → обратно). Значит тексты
  «перезапустите обход» для правок СПИСКОВ излишни — корректно «применится к
  новым подключениям» (старые потоки держат закэшированный профиль). Тумблеры
  (аргументы) по-прежнему требуют рестарта. `--wf-tcp-empty` НЕ нужен: SYN+ACK/
  FIN/RST перехватываются автоматически, tcp-empty добавляет только чистые ACK
  (для ACK/window-экспериментов, у нас таких нет). UDP-автохост возможен только
  для QUIC (hostname из quic_initial; у STUN/игр/Discord-voice hostname нет →
  автолист к ним неприменим, игры обычно IP-блок = ipset). Кандидат-эксперимент:
  `--wf-udp-in=443` + `--hostlist-auto-debug`. `mtproto` в zapret2 — TCP-only
  (звонки TG = UDP, не лечатся); tg-wsproxy — другой слой (прокси), не встраиваем.
  UX-правки (0.9): тексты про списки смягчены («применится к новым подключениям»);
  лаунчер теперь ссылается на user-списки ВСЕГДА, даже пустые (иначе первая
  правка пустого файла не подхватывалась — проверено: `Loaded 0 hosts` → add →
  `positive` + `profile matches`). BOM в списках (кейс 2026-09-14): корень —
  `_handle_save_list` сохранял `\ufeff` из буфера обмена (`strip()` его не
  убирает), а `_read_lines` читал без utf-8-sig → мусор оставался первой
  строкой и не матчился движком. Фикс: `_clean_list_text` (BOM + zero-width)
  на save/read/contested-toggle + идемпотентная авто-нормализация 4 GUI-списков
  при старте; тест: файл с BOM-байтами и ZWSP → init → чисто, save с BOM → файл
  чистый, повторный save без накопления.
- Probe «Анализ приложения» (2026-09-14): сервер копит ИСТОРИЮ за окно
  (states/snapshots, первое/последнее появление) — раньше хранился только
  последний снимок, и исчезнувшие попытки/таймауты терялись, а «×n» на фронте
  был счётчиком строк (почти всегда 1). Теперь: упорный SynSent, «не
  установилось» (SynSent без Established), CloseWait, UDP per-target sent→recv
  (в т.ч. захват pktmon), вердикт собирается из истории. Осталось (0.9):
  подсказки-домены для добавления в списки + дедуп «уже в обходе».
- Здоровье списков (2026-09-14): `core/list_health.py` — универсальный слой
  (дубли внутри файлов, cross между include-файлами, конфликты include/exclude,
  лишние user-записи, покрытие домена) + API `/api/lists/health|dedupe|
  add-domain`. Старт: фоновая проверка → тост ТОЛЬКО по user-видимым метрикам
  (его файлы); пересечения bundled-файлов — наша зона и в тост не попадают
  (в репо их 9: general↔discord, general↔cdn-fix). «Списки»: панель «Здоровье
  списков» (Проверить / «Убрать дубли» с confirm). Probe: домены проблемных
  целей + кнопка «В обход» (серверный дедуп: added/already/moved/blocked).
  CDN (`_plan_cdn_action`) и «Спорные домены» переведены на list_health:
  покрытие/блок/дедуп, тумблер — added/already/moved/blocked. Пересечения
  bundled НЕ чистим осознанно: в пресетах есть сегменты с list-general БЕЗ
  list-discord — удаление дублей из general сняло бы покрытие (проверено
  скриптом по сегментам).
- Мегафон-пользователь: дискорд пробился после lua-init фикса, ютуб нет —
  нужны его debug-лог/диагностика.
- VM-тест с облаком Защитника на новых сборках — рекомендован.
- 0.8: **обновить ipset-базу до актуала** (пометка 2026-09-13). Наш
  `lists/ipset-all.txt.gz` (32126 CIDR) разошёлся с сообществом: V3nilla
  IPSets-For-Bypass-in-Russia (github.com/V3nilla/IPSets-For-Bypass-in-Russia,
  885★, обновляется, RIPE-сбор «недоступных» подсетей 2025-2026: AWS CDN/
  CloudFront/Cloudflare/BunnyCDN/OVH) — 31546 CIDR, 1403 у них есть, у нас
  нет (и 1983 у нас есть, у них нет). НЕ вливать целиком: ipset-десинк по
  «недоступным» лечит fix-класс, но ломает break-класс (DO/OVH — их же
  подсети!). Путь: дифф-обновление + CDN A/B-сверка после применения, либо
  точечно через ipset-include-user («Спорные домены»). Их AS Parser —
  референс для авто-сбора с RIPE.
- Возможные фичи (обсуждены, не начаты): «Починить GitHub» кнопка (Fastly-проба
  + атомарный hosts), автоподбор desync-параметров, Game TCP fallback (Minecraft),
  Diagnoser-реворк, blob rotation.

---

- **Размер exe (2026-09-22)**: pywebview статически упоминает `cryptography` →
  PyInstaller тянул ~15 МБ мусора (Rust-pyd 9.5 + libcrypto 5 + libssl 0.76 +
  bcrypt), хотя наша проверка подписи — stdlib. Исключено в build.py
  (`cryptography`, `bcrypt`): exe 18.5 → **14.9 МБ**, zip 18.3 → 14.7 МБ
  (libcrypto/libssl остаются — это Python `_ssl` для HTTPS). Остаток: дубль
  `cygwin1.dll`/`WinDivert.dll` — **причина найдена**: PyInstaller сканирует
  наши `bin\*.exe/.dll` (добавленные `--add-data`) как PE и подтягивает их
  импорты — `winws2.exe` требует `cygwin1.dll` и `WinDivert.dll`, поэтому они
  попадают **в корень архива** вдобавок к копиям в `bin\` (TOC: BINARY vs
  DATA). **СДЕЛАНО (2026-09-22)**: сборка переведена на `Zapret2GUI.spec`
  (datas/binaries + фильтры корневых дублей и `Python.Runtime.xml`):
  exe 14.9 → **13.7 МБ**, zip 14.7 → **13.5 МБ** (от исходных 18.3 — минус
  26%). Проверено листингом архива: `cygwin1.dll`/`WinDivert.dll` только в
  `bin\`. Требуется смоук-запуск exe пользователем.

## Сжатая хронология

### §1. Баг коротких путей (2026-07-17) → §2-пересмотр (2026-08-27)
**Симптом:** все пресеты давали одинаковый результат (`google:200, discord:timeout,
youtube:timeout`) при работающем Zapret 1. **Причина:** `build_args_from_preset`
заменял `@lua/`/`@blobs/` на короткие 8.3-пути → winws2 грузил 1 профиль вместо 4-7,
0 пакетов, 000.
**Пересмотр §23:** настоящий виновник — **путь БЕЗ пробелов** отдельным аргументом:
`--lua-init @C:\...` (без пробелов) убивает цикл разбора опций → 1 профиль
`no_action`. 8.3-имена всегда без пробелов (поэтому и ломались), «рабочий длинный
путь» из §1 содержал пробел («Zapret 2 GUI»). Фикс: пост-проход мержит
`("--lua-init", "@...")` в одну токену `--lua-init=@...` (работает с любым путём).
Sanity тестера (`profiles_loaded ≤ 1` → engine_broken) ловит такие установки.

### §2. Прочие баги лаунчера (2026-07-17)
- `@hostlists/` не резолвился — добавлен hostlists_dir + цикл замены.
- `--comment` строки не фильтровались — добавлено в условие пропуска.
- `debug_winws2.log` для short_path до создания — файл .touch() сначала.
- `--autohostlist=@...` несуществующий флаг → `--hostlist-auto=<путь>` (без @).
- `tasklist` на русской Windows = CP866 → UnicodeDecodeError: во всех `text=True`
  вызовах `encoding="oem", errors="replace"` (launcher, controller, tester ×9,
  service_manager ×2, server).

### §3. `--payload` — ключевой параметр (имба)
**Все стратегии НИЧЕГО не делают без `--payload`** — lua-desync не знает где
искать в потоке. Всегда указывать: `tls_client_hello` (TLS), `http_req` (HTTP),
`quic_initial` (QUIC), `discord_ip_discovery` (Discord voice).

### §4. `repeats=N` — перегрузка, не нужен везде (обновлено 2026-09-12)
- **Discord на Т2: repeats=8 минимум** (утром 7 → 000, 8 пробил; днём 7=8 —
  порог плавает, 8 = запас). Работает и с nodrop, и без: решает ОБЪЁМ
  google-фейков (ТСПУ классифицирует по доминирующему SNI, доля ≥90% = пропуск,
  механика pktmon §полигон).
- **YouTube (google-блок)**: repeats=6 без nodrop. **General TCP (github)**: repeats=8 без nodrop.
- **QUIC-блоки default**: без repeats (при регрессе — 6-11).
- Для остальных пресетов/сетей НЕ увеличивать «на всякий случай».
- Старое «nodrop → repeats=1» устарело: на Т2 повтор обязателен даже с nodrop.

### §5. Debug режим
`--debug=@debug_winws2.log` — каждый пакет, пинг +50-150ms, CPU +15-30% — только
для диагностики. `--debug=1` (консольный) — ломает захват → 000.

### §6. nodrop + repeats на Т2 (2026-09-11)
nodrop = оригинал уходит как есть + фейк отдельно. На SNI-блоках **nodrop ломает
цель** (оригинал с реальным SNI идёт следом за фейком → DPI видит оба):
- default google-блок: fake БЕЗ nodrop + tcp_ts=-1000 + repeats=6; multisplit без
  nodrop/tcp_ts. Проверено 200/200/200 ×7.
- General TCP (github-fix): fake без nodrop + repeats=8.
- Тот же фикс в остальных пресетах (google-блоки); fake-disorder не тронут
  (механизм tls_fake_disorder иной).
- **Discord-блоки: nodrop УБРАН (2026-09-21)**. Debug-лог winws2 доказал
  механику: с nodrop оригинальный ClientHello уходит в сеть целиком
  (`packet: id=N reinject unmodified`), без nodrop — `packet: id=N drop`
  (данные доставляют только сплит-части). Плюс оптимизация: repeats только на
  fake-залпе, сплит-части ×1 (**24→10 пакетов на hello**, сверено логом);
  чисто-сплитовые пресеты (multisplit-pure/seqovl) повторы сохраняют — там
  это единственный объём. Учёт пакетов и судьбу hello смотреть в debug-логе
  (`--debug=@<длинный путь>.log`, короткий 8.3-путь не писать!).

### §7. tcp_ts / PAWS — ключевая механика fake (2026-08-23)
`fake` шлёт блоб на том же seq, что оригинальный ClientHello; `tcp_ts=-1000`
уменьшает timestamp → сервер отбрасывает фейк по PAWS (старый TSVal), DPI
(без PAWS) видит фейк первым. **tcp_ts на multisplit ЗАПРЕЩЁН** — сплит-части
тоже умирают по PAWS, данные не доставляются (без nodrop — полный 000).

### §8. pos-маркеры — ZERO-BASED (2026-08-23)
`resolve_multi_pos(data, l7, "N")` без 4-го аргумента: `pos=1` → разрыв после
1-го байта (аналог nfqws `--dpi-desync-split-pos=1`). `pos=1` в пресетах работает,
менять не нужно. (4-й аргумент `true` в lua-тестах = 1-based, не путать.)

### §9. Discord upload + AWS (2026-08-23 → 2026-09-11)
- Загрузки Discord идут на `discord-attachments-uploads-prd.storage.googleapis.com`
  **только через QUIC (TCP-фолбэка нет)**; потеря домена из list-general →
  `no_action` → «не отправляются файлы». Домен в list-general + list-discord.
- Steam Cloud: три ротируемых бэкенда (GCS/S3/Azure) — родительские домены
  storage.googleapis.com / blob.core.windows.net в list-general.
- **⚠️ ОТМЕНЕНО (2026-09-11): `amazonaws.com` УБРАН из list-general** — наш
  десинк ЛОМАЕТ AWS-API (DynamoDB/S3: 000 с default, 200/307 в голую; игра
  Wardogs + NVIDIA App падали). AWS живёт в голую на Т2. Если на других сетях
  S3 режется — возвращать ТОЧЕЧНО через list-include-user.
- Проверка загрузок без Discord: `curl.exe -4 -s -m 8 -o NUL -w "%{http_code}"
  https://discord-attachments-uploads-prd.storage.googleapis.com/` — 403 = ок,
  000 = сломано.

### §10. Тогглы: архитектура
- **GameFilter**: off — ничего; tcp — `--filter-tcp 1024-65535 --filter-l7 tls`
  + lua-desync; udp — `--wf-udp-out=1024-65535 --filter-udp 1024-65535`
  + lua-desync; both — TCP+UDP.
- **Discord Voice**: `--filter-udp 19294-19344,50000-50100 --filter-l7 discord,stun
  --payload discord_ip_discovery --out-range -d10 --lua-desync=fake:blob=quic_google`.
- **Auto Hostlist**: `--autohostlist` в блоках list-general; автосоздаёт
  lists/zapret-auto.txt.
- Читаются из AppConfig при старте, из UI при установке службы; изменение = рестарт.

### §11. User-листы: hostlist ПО ПРОФИЛЯМ (2026-08-30, сверено с v1.0.2/v1.0.5) 🚨
Профили перебираются по очереди, побеждает ПЕРВЫЙ с совпавшим фильтром+hostlist;
несколько `--hostlist` в профиле ОБЪЕДИНЯЮТСЯ (hostlist.c AppendHostList; «последний
переопределяет» НЕВЕРНО). Следствие: user-списки «в конец» попадали только в
QUIC-профиль. Теперь лаунчер инжектит `--hostlist=<list-include-user.txt>` и
`--hostlist-exclude=<list-exclude-user.txt>` СРАЗУ ПОСЛЕ ПЕРВОГО hostlist-токена
КАЖДОГО профиля с hostlist (exclude — и в ipset-dup сегменты). Пустые юзер-файлы
не меняют конфиг (байт-в-байт).

### §12. ipset_catchall — «Общий IP-обход» (2026-08-27)
Опциональный тумблер: ЗАМЕНЯЕТ каждый `--hostlist=list-general` на
`--ipset=ipset-all.txt.gz` + `--ipset-exclude=ipset-exclude.txt` (include-хостлист
УДАЛЯЕТСЯ — winws2 применяет ipset и hostlist как AND). default.txt остаётся
точечным (без ipset). ipset-exclude.txt редактируется на странице «Списки».
Проверено: OFF — 7 профилей; ON — 4 ipset-аргумента, hostlist удалён.
⚠️ При живом winws2 dry-run даёт «1 profile» + «already running» — НЕ баг.

### §13. Тестер: статистика, рекомендации, naked-базлайн (2026-08-27)
- `network_rate` — счёт БЕЗ пингов (пинги врали: Мегафон 67% при реальных 31%).
- naked-базлайн `run_naked_baseline()` перед прогоном; все стратегии = голому →
  no_bypass.
- `collect_sanity_info`: dry-run тех же аргументов (0-1 профиль = engine_broken,
  WinError 740 — не поломка) + покрытие списков (домен вне @lists → no_action).
- Вердикт `_build_recommendation`: **порядок веток важен** — engine_broken →
  misses → same_as_naked → ok → partial → no_bypass. QUIC_OK-инференс: youtube
  мёртв, но i.ytimg/youtu.be жив на том же прогоне → key_host «YouTube» =
  «работает через QUIC». Только по полным результатам профиля.
- Классификатор `classify_block` (diagnostics): DNS → TCP:443 → TLS(real SNI) →
  TLS(чужой SNI). Вердикты: dns / ip_block / ok / **sni_block** (IP чистый, блок
  по SNI — desync ОБЯЗАН обходить) / tls_block. Проверено на Т2: youtube → sni_block.
  ⚠️ ThreadPoolExecutor: только `shutdown(wait=False)` — wait=True ждёт чёрные дыры.
- service_manager.status(): парсить ЗНАЧЕНИЕ (`RUNNING/STOPPED` — всегда
  английское), не локализованный заголовок «СОСТОЯНИЕ».
- Ускорение: TTL-кэш tracert (1 раз на сессию), `-h 5 -w 900` timeout 14s,
  sleep 5→1.5s, `--connect-timeout 2`, параллелизм 5→8 (CDN 15). Профиль ~12.7s.
- `_restore_protection_after_naked()` — после naked возвращает что работало
  (Zapret 2 или Zapret 1), иначе пользователь молча остаётся без обхода.

### §14. Речек спорных доменов (2026-09-04)
Старое «без retries» отменено НЕ в пользу пер-хостовых повторов: в `_curl_test`
ретраев НЕТ (000 фиксируется как есть; следующий пресет и так перетестирует).
Один общий повтор в конце прогона: `contested = RATED ∩ {не пробитые best-стратегией}
\ quirk_skip` → повторился ≥100 = «временно недоступен (ретест)», снова 000 =
«заблокирован». `blocked_domains` — по ЛУЧШЕЙ стратегии (не union). `quirk_skip`:
youtube-семейство при активном приколе не речекается. Логика только уровня
отчёта, rate/скор не меняются.

### §15. Служба Windows
- `_prepare_service_bat()` регенерирует bat из текущего пресета+тогглов ПЕРЕД
  install И start (протухший bat поднимал старую стратегию молча).
- Установка: sc create/config через ВРЕМЕННЫЙ .bat; binPath верифицируется
  после sc create (старые Win10 искажают cmdline → откат с диагнозом);
  SCM-recovery: `sc failure` restart 60с ×3.
- `status()` парсит STATE из `sc query` (не tasklist).
- «Стратегия ?» в статусе = controller не знал профиль службы — current_strategy
  заполняется при install/start.
- После taskkill winws2 первый `sc start zapret2` может дать 1053 (служба не
  успела ответить) — повторить.

### §16. Lite (2026-08-27) — обход детектов Защитника
Onefile-EXE триггерит облачные эвристики Defender (распаковка _MEI*, админ-
манифест, локальный HTTP, cmd, драйвер). Решение: `build_lite.py` → `lite/`
(winws2 + lua/blobs/lists/presets + батники, БЕЗ Python). start.bat через `%~dp0`
(портативно), `_portable_args()` заменяет абсолютные префиксы. lite/ в .gitignore.
test_lite.ps1 синхронизирован с GUI-тестером (CONTROL 16→7, RATED 11).

### §17. Portable (2026-08-27) — GUI без паковщика
`build_portable.py` → python-3.13.14-embed-amd64 + pywebview 6.2.1 (pythonnet),
`main.pyw`, install.cmd (ярлыки), README. Подводные камни:
- `PY_SHORT = "".join(PY_VER.split(".")[:2])` = "313" — НЕ replace(".", "") ("31314").
- После extract переписать `python313._pth`: `python313.zip / . / Lib\site-packages / import site`.
- UAC-самоподъём: relaunch_as_admin (ярлыку RunAs не нужен). Пользовательские
  правки в app/ не затираются (нет copytree-механизма).

### §18. Блок githubusercontent на Т2 (2026-08-30) 🚨
SYN-блэкхол всей подсети 185.199.108.0/22 (Fastly/GitHub): .133 — полный чёрный
хол TCP+UDP; WARP обходит. Десинк физически не может помочь (SYN не встаёт) —
матрица из 6 вариантов = все 000. **Решение: hosts-пиннинг на Fastly-эдж**
(конфиг GitHub общий на всех edge): 151.101.66.132 (лучший), 151.101.130.132,
151.101.194.132, 146.75.30.132, 146.75.78.132, 146.75.22.132, 151.101.2.132 →
raw/objects/release-assets/private-user-images/gist/avatars* — стабильно 200.
`hosts.txt` в корне репо — ПОЛНЫЙ готовый hosts (секции ИИ-гео, github-fix,
0.0.0.0-заглушки). IPv6-записи НЕ включаем; Discord/Telegram-пиннинг НЕ включаем
(флакают — пин на флакующий IP хуже отсутствия).
- list-general: github-семейство (15 доменов) — для сетей с SNI-резкой.
- Update-check: raw VERSION → api.github.com contents/VERSION фолбэк (releases
  отдают 404 на pre-release). Зеркало jsDelivr: cdn.jsdelivr.net/gh/TheFirstNoob/
  Zapret-2-GUI@main/Windows%20build/<zip> (лимит 20MB).
- **Урок чистки hosts**: запись на мёртвый IP ХУЖЕ отсутствия (gemini 62.133.62.97
  мёртв → 000, без записи 200). При чистке работников — СНАЧАЛА пробовать живой.
- Контекст (форум Zapret 1): Ростелеком = РДП.РУ (фильтры «кривые», плавают);
  YouTube РТК — QUIC off + DNS 9.9.9.9.

### §19. Обзор MIT-проектов + внедрённое (2026-08-30)
Осознанно НЕ берём: авто-лечение TLS-пробами 45с (AV-паттерн; autohostlist и так
решает), память по сетям (fingerprint, выгоды ~3с нет), Job Object (наш запуск
через bat, убийство по имени image покрывает).
Внедрено:
- `core/tcp_timestamps.py`: на Win11 реестр Tcp1323Opts=0x2 ВРЁТ — авторитетен
  шаблон NetTCPSetting (`Get-NetTCPSetting -SettingName Internet → Timestamps`),
  modern → legacy фолбэк. Включение: Set-NetTCPSetting, фолбэк netsh.
- `core/conflict_scan.py`: жёсткий конфликт = чужие DPI-тулзы (winws.exe=Zapret1,
  byedpi, goodbyedpi, spider, fpwin, intosy); warning = VPN-клиенты/службы
  (state= active! не all — иначе ложные срабаты) + туннельные адаптеры.
- `validate_lua` (launcher): второй проход `--intercept=0` реально компилит
  lua-init (--dry-run Lua НЕ грузит). Встроен в validate_args.
- DNS-здоровье в диагностике (чек dns_health): системный резолвер + DoT 853 +
  DoH 443 (на Т2 DoT то жив, то мёртв).
- auto.txt: circular по сегментам default (fails=3, retrans=2) — механизм
  переключения работает, на Т2 выигрыша нет (92.3% = default).
- **validate_args** (launcher): прогон `winws2 --dry-run` + скан текста
  (`unknown option`, `bad file`, `cannot access/create/open`, `lua error`,
  `error loading`) — код возврата ненадёжен (0 даже при unknown option).
  Границы: dry-run ловит флаги/пути, НЕ ловит ошибки аргументов lua-функций
  (blob=nosuchblob) — они на пакете в рантайме. Подключена: controller.start
  (валидация ДО stop — пользователь остаётся под защитой) и _handle_service_install.

### §20. Чистка пресетов (2026-08-23)
- `tcp_ts=-1000` убран со ВСЕХ multisplit-строк (PAWS, §7).
- fake-multidisorder: `blob=google_tls` → `pos=1,midsld:nodrop` (блоб заставлял
  disorder слать GOOGLE-блоб вместо реальных данных).
- hostfakesplit: позиционные аргументы не работают — только `host=...`.
- Проверка после правок: build_args_from_preset → winws2 --dry-run → нет
  unknown option/bad file/error.

### §21. Тестер 0.3: зависания (2026-08-23)
«50/50» зависаний = UnicodeDecodeError на CP866-выводе tasklist/sc (см. §2) —
поток тестера умирал на «Останавливаем zapret...» → UI висел вечно.
`_ensure_data_dir` затирал пользовательские правки: данные обновляются только
при смене VERSION (маркер data_version.txt); *-user.txt и свои пресеты не
удаляются никогда. `_warn_if_bad_path`: ASCII/кириллица с 8.3 — ок; кириллица
без 8.3 — предупреждение.

### §22. Диагностика 0.3: фиксы ввода в заблуждение
- HTTP 403 объясняется («не блокировка, CDN так отвечает анонимным»).
- YouTube: i.ytimg.com проверяется ДО www.youtube.com; youtube мёртв + CDN жив →
  ok с пояснением про QUIC (и зеркальный случай 08-30: i.ytimg режется при
  живом youtube — тоже ok). Полный fail → fail.
- Диагностика вызывала `/api/api/diagnose` (apiPost сам добавляет /api) → 404;
  исправлено на `/diagnose`.
- Баги: full_analyzer `test_profile(skip_aux=...)` — нет такого параметра →
  TypeError (сломано и в HEAD, и в 0.2) → `skip_cdn=(tier != "full")`;
  app.js poll не сливал state.all_results в fr → пустая таблица быстрого теста.

### §23. Ссылки по другим темам
- Яндекс.Браузер принудительно подменяет DNS на 77.88.8.8 и блокирует сторонние
  DoH — тестировать в Firefox/Chrome.
- Killer NIC конфликтует с WinDivert (zapret запускается, пакеты не
  обрабатываются) → отключить Bandwidth Control.
- **Мёртвая служба драйвера «WinDivert» (2026-09-13, ПОДТВЕРЖДЕНО)**: служба
  ставится ОДИН РАЗ и навсегда хранит ImagePath (путь к .sys). Другая zapret-
  версия/переезд/удаление папки → ImagePath мёртв → winws2 видит «служба уже
  есть» (версия совпадает) → StartService по мёртвому пути → вечный
  «windivert: error opening filter: file not found» ДАЖЕ при живых .sys/.dll
  рядом (7 профилей и списки загружаются нормально — параметры не виноваты).
  **Диагноз подтверждён**: `sc delete WinDivert` у пользователя → сразу
  заработало. Авто-фикс (repair-first, 2026-09-13): битый ImagePath главной
  службы перезаписывается `sc config binPath= \??\<наш>\bin\WinDivert64.sys`
  + `start= demand` (БЕЗ удаления); Start=Disabled включается; удаление —
  только если иначе нельзя и winws2 НЕ запущен. Вызовы: launcher (перед
  ручным запуском), service install (ПОСЛЕ остановки winws2) и service
  start. Чеки: diagnostics
  «Служба драйвера WinDivert» (ImagePath dead / Start=Disabled) и
  «Файлы WinDivert». Тестер-аборты пишут причину в test_session.log.
  **ЛОВУШКА «marked for delete» (кейс друга #2, 2026-09-13)**: `sc delete
  WinDivert` при ЖИВОМ winws2 (открытые хендлы драйвера) НЕ удаляет службу
  сразу — помечает её до перезагрузки; в этом состоянии новый запуск
  драйвера/программы может падать/выбивать («программу выбило даже с ручным
  запуском»). Правило: сначала остановить обход (winws2), потом sc delete,
  затем перезагрузка для завершения удаления. Автозапуск службы zapret2
  при сбое драйвера: winws2 стартует → WinDivertOpen fail → падает → SCM
  recovery 3×60с → остаётся STOPPED (GUI: «Запустить службу»). Диагностика
  покажет причину (ImagePath/Start/файлы).
- **Миграция с Zapret 1 (Flowseal 1.9.x, service.bat)**: служба называется
  `zapret` (binPath `"\<папка>\bin\winws.exe" <args>`, start= auto, DisplayName
  "zapret"); его «Remove Services» делает `net stop zapret` + `sc delete
  zapret` + `taskkill winws.exe` и вдобавок чистит драйвер-службы `WinDivert`
  И `WinDivert14` — оттуда мёртвые хвосты у мигрантов. Наш install при
  конфликте предлагает подтверждение «Остановить и удалить Zapret 1»
  (zapret1_cleanup — тот же набор действий), затем продолжает установку.
  Кнопка «Починить» на главной вызывает driver-heal (repair/enable/удаление
  по обстоятельствам).
  **Нюанс состояния (2026-09-22)**: `Start=4` и `DeleteFlag=1` у службы
  WinDivert — **НОРМА**: WinDivert сам ставит драйвер disabled, грузит его
  напрямую (`sc query` = RUNNING) и помечает службу на удаление, чтобы запись
  не висела в системе. Проверено: службу удалили начисто → перезапуск обхода →
  WinDivert создал её снова ровно в таком виде (а при выгрузке драйвера
  удаление завершается). Диагностика/heal не должны считать это проблемой —
  реален только мёртвый ImagePath. Попутно починен парсер ImagePath: префикс
  `\??\` (одинарный слеш — раньше ждали двойной) и пути с пробелами (`475c6f2`);
  отдельный тест: пробелы/кавычки/аргументы.
- **Безопасность обновлений (0.9, 2026-09-21)**: апдейтер ставит только
  обновления с валидной подписью. `core/update_verify.py` — Ed25519 (RFC 8032,
  чистый Python, без зависимостей), вшитый PUBKEY (пусто = fail-closed, ничего
  не применяется). Релиз подписывается офлайн-ключом:
  `tools/security/gen_update_key.py` (ключ вне репо, см. .gitignore) +
  `tools/security/sign_release.py` → release.json + release.json.sig
  (прикрепить к релизу + закоммитить теми же байтами для jsDelivr).
  Worker: манифест+подпись → verify → validate_release (schema, тег,
  анти-даунгрейд, артефакт, формат sha256; для exe — exe_sha256) → скачивание
  с обязательной сверкой sha256 (fail-closed, без подтверждённого хеша сеть
  не трогается) → распаковка в updates/_extract, сверка файлов по
  update_manifest.json ДО записи в установку (zip-slip guard; неизвестные
  манифесту файлы пропускаются — исторически bat/readme в него не попадали).
  Хеш из того же источника, что и файл, защитой не считается. Тесты:
  `tools/security/test_updates_security.py` (векторы RFC + worker-интеграция +
  кросс-проверка с cryptography, dev-only). Чеклист выпуска:
  AI_DOCS/RELEASE_CHECKLIST.md (версии в манифестах сборок — из core.config).
  Закалка аккаунта: 2FA + Immutable Releases.
- **Холодный прогон Discord (2026-09-21)**: диагноз найден — nodrop-утечка
  полного ClientHello (доказано debug-логом, см. §6). База переведена в drop
  + повторы только на fake-залпе; добавлен ALT-режим (nodrop): тумблер в
  экспертных + галочка в тестере. Ждём плохое окно для финальной проверки.
  Служба юзера намеренно оставлена на СТАРЫХ аргументах (nodrop) — ловим
  холодный старт; после поимки/решения переустановить службу из GUI.
  Побочные кандидаты: QUIC-покрытие Discord в list-general отсутствует
  (у ALT11 есть 24 домена), voice repeats=6 как у ALT11.
- **Wardogs на SkyNet (2026-09-21, ВИСИТ)**: авторизация/лобби ок
  (list-include-user: live.wardogs.bulkhead.pragmaengine.com, firstlook.gg,
  api.epicgames.dev; EC2 eu-west-1 54.228.212.233/54.216.209.199 —
  Established). **Не проходит игровая UDP-сессия**: серверы
  54.115.115.111:4192 и 54.115.9.78:4192 (AWS eu-central-1) —
  sent≈1800 vs recv≈120-160, клиент откидывает в меню («компиляция карты»
  не начинается). Проверено ручным winws2 (default-alt): `ipset_catchall=ON`
  — без эффекта (catch-all покрывает TCP 80/443 + QUIC 443, не 4192);
  `GameFilter=udp` (fake quic ×10 на 1024-65535) — без эффекта. TCP DynamoDB
  35.71.x SynSent — транзиентные (SYN-ACK приходят). **Подтверждено
  (2026-09-21): WARP в режиме «только UDP» пробивает игру** → блок строго на
  UDP-уровне, TCP ни при чём. Кандидаты для отдельного UDP-профиля (на потом):
  `udplen` (increment/pattern — механика из Discord Voice «UDP-длина»), иные
  блобы/паттерны fake, порт-специфичный сегмент на 4192; тестировать точечно.
  Сырой pktmon-захват: `%TEMP%\zapret2_probe\game_udp.txt` (UTF-16; парсер
  probe починен в 683e740). **udplen проверен прямым прогоном** (DNS 53 +
  debug-лог): +5 с `pattern=0xDEADBEEF` и `pattern=quic_google` работает
  (`udplen: 29 => 34`, поток не ломается), −5 обрезает запрос. Варианты под
  игру: `tools/_game_udp.py udplen_hex|udplen_quic|udplen_fake|udplen_up2`
  (порт 4192; служба останавливается на время прогона, вернуть: sc start).
  **✅ РЕШЕНО (2026-09-22)**: рабочий рецепт — `fake ×10 + drop` на UDP-к
  диапазонам (`--filter-udp=1024-65535 --ipset=<54.115/54.228/54.216/3.218.0.0/16>`
  `--out-range -d4 --lua-desync=fake:blob=quic_google:repeats=10:payload=all`
  `--lua-desync=drop`), вариант `tools/_game_udp.py fake_drop`. Два корня:
  (1) **lua fake/udplen по умолчанию трогают только known-payload** — на
  unknown-UDP нужен аргумент функции `:payload=all` (все прошлые UDP-тесты
  были холостыми!); (2) drop оригинала (механизм nfqws: DPI видит только
  QUIC-фейки, игра ретранслирует). Блок только на этапе коннекта: после
  установления сессии выключение обхода не выкидывает. БАГ ПРОДУКТА:
  GameFilter=udp в лаунчере был холостым (нет `payload=all`) — исправлено.
  safe-delete) и рапортует о Zapret 1 (`POST /api/service/repair`).

## Хосты / AI-пины (2026-09-24) — не гонять пачками

- Воркер AntiZapret 193.233.112.68 живой на прямом маршруте (claude.ai 302,
  api.openai.com 401, gemini/copilot 200), НО флакает и троттлит при серии
  запросов; под WARP он мёртв (000). Наши прежние 45.155.204.190 /
  37.230.192.51 деградировали - 143 пина в hosts.txt переключены на
  193.233.112.68 (коммит fbf248e).
- **Smart-DNS пул 87.228.47.x** (ответы DNS 111.88.96.54/.55, «Xbox DNS»)
  - самый стабильный и без WARP: openrouter.ai, gemini.google.com,
  copilot.microsoft.com, grok.com, api.openai.com (+auth0/videos/cdn).
  Системный DNS на Xbox-адреса НЕ переводим (видит всё + подменяет ответы);
  используем его только как источник IP.
- Telegram в РФ прибит по IP: пин работает только через WARP/прокси; клиент
  ходит своими DC (hosts на него не влияет).
- chatgpt.com не отвечает ни через один воркер; claude.ai - то 302, то 000.
  Это НЕ наш косяк - флак на стороне сервисов/воркеров.
- Правило: проверять одиночными запросами с паузами; массовые прогоны
  (10+ запросов подряд) уводят воркеры в лимит на десятки минут.

## Служба, запуск, логи и игры: рефактор 0.8.x (2026-09-25)

### Диагноз «binPath пуст» / «у кого-то не ставится»
- SCM **хранит** binPath любой длины (проверено 4752+ симв. — служба
  создаётся и запускается), но штатное чтение `sc qc` / CIM /
  QueryServiceConfig **падает** на пути >~4 КБ: `sc qc` → 1734 «array bounds
  invalid», CIM PathName → пусто. Старая верификация видела «пусто» и
  объявляла binPath кривым → **удаляла рабочую службу** («Установка отменена
  (кривой binPath): binPath пуст»). Игры добавляли ~150 симв. и переводили
  3888→4066 через порог чтения — отсюда «с галками ломается, без галок ок».
- Фикс: `_read_stored_binpath()` читает **ImagePath из реестра** (winreg):
  длина/локаль не важны, точное сравнение. `sc qc` руками на длинной службе
  по-прежнему даёт 1734 — это косметика, инструменты им не пользуются.

### Служба: Win32 API вместо sc+bat
- create/config/delete: ctypes `CreateServiceW` / `ChangeServiceConfigW` /
  `DeleteService` — binPath сохраняется дословно, без cmd/кавычек/кодировок/
  temp-файла (старый sc-через-bat — фолбэк, причина фолбэка в логе).
- `remove()`: ждёт фактической смерти winws2 (tasklist) и повторяет delete —
  лечит «marked for deletion» (1072) и «удаляется со второго раза».
- `reconfigure()`: после записи сверяет реестр (sc config мог «успешно»
  ничего не записать) и `start()` не молчит при ошибке.

### Логи: logs/zapret2.log + раскладка
- `core/applog.py` → `<папка программы>/logs/zapret2.log` (дата+секция,
  ротация >5 МБ, попадает в отчёт-архив). Секции: `service`, `launch`,
  `games`, `layout`, `test`.
- Стартовый лог раскладки (`main._log_layout`): `frozen/sys.executable/
  __file__/_MEIPASS/cwd/root` + размеры 11 критичных ресурсов + маркер
  `data_version.txt`. onefile-модель: `_MEIPASS` → копия рядом с exe по
  маркеру версии.
- **self-heal** (`main._heal_missing_data`): если критичный файл пропал или
  обрезан (AV/OneDrive после копии) — докопируется из `_MEIPASS` на каждом
  запуске (раньше маркер версии навсегда блокировал повторную копию).
- Префлайт-парсер `@`-путей понимает `@file`, `--opt=@file`, `name:@file`,
  `--opt=file` (ложный missing на `=@` был багом таблицы — починен).

### Запуск без службы: Popen (основной) + bat (фолбэк)
- `launch_winws2()`: префлайт (exe есть, пустых аргументов нет, @-пути
  существуют — с номерами аргументов) → `Popen([exe, *args])`; при
  неудаче/падении — bat `start /min` (старый путь = фолбэк и контрольный
  эксперимент). SeLoadDriverPrivilege включается в текущем токене до запуска —
  CreateProcess его наследует. Переведены `zapret_controller`, `tester`,
  smoke «Личной стратегии». bat-путь без службы имеет лимит cmd 8191 —
  поэтому он больше не основной.

### Игры: пулы UDP + combined include
- UDP: один `--new`-сегмент на группу правил с одинаковыми repeats/cutoff;
  порты — списком в `--filter-udp`, CIDR всех правил группы — в общий
  `lists/games/_pool_d<cutoff>r<repeats>.txt` (дедуп). Было ~150 симв./игру,
  стало ~5 симв./игру + фикс. на пул (3 игры/2 группы → 2 сегмента).
- GameFilter=udp/both: игровые UDP-правила и дописывание портов в
  `--wf-udp-out` **пропускаются** (диапазон 1024-65535 и так покрывает порт);
  в лог — строка `[games] ... пропущены`.
- Домены: `games.sync_include_list()` пишет `lists/list-include-all.txt` =
  union(user + games, дедуп), в args — ОДИН `--hostlist` вместо двух.
  Файлы-владельцы не смешиваются (`list-include-user.txt` юзерский,
  `list-games.txt` генерируемый). Union пересобирается на каждом
  build args (install/start/reconfigure/тестер); внешние правки user-файла
  без re-apply не подхватятся.
- Проверено: реальный конфиг — 1 сегмент на 4192, пул 4 CIDR, include =
  3 домена; мульти-игры — 2 группы/2 сегмента; GameFilter=udp — ноль игровых
  аргументов; `validate_args` (dry-run) — OK. Служба юзера переключится на
  новые аргументы при следующем apply/reinstall из GUI.

### Решение по рефактору аргументов (не делаем полный)
- Пресеты — текстовые (пользовательские + exp/cand для тестера): типизация
  потребует либо дублирования в коде, либо компилятора пресетов — оба
  варианта переписывают критичный узел без пользовательской выгоды.
- Авторитетная валидация — `winws2 --dry-run` + `--intercept=0` (движок);
  префлайт — добавочный слой (файлы/пустые аргументы).
- Если понадобится: «ресурсный реестр» из генератора (`build_args_from_preset`
  знает впрыснутые файлы) — ~50 строк без смены поведения. Триггеры
  пересмотра: GUI-редактор отдельных аргументов; генерация пресетов из кода;
  частый дрейф «тумблеры ↔ пресет».

### Осталось
- Пересборка exe (onefile) и portable после рефактора (`COPY_DIRS` уже
  включает core/server — `applog.py` подхватится; нужен прогон сборки).
- Lite: `service-install.bat` по-прежнему sc+`\"`-бат (в lite нет Python);
  при необходимости — PowerShell `New-Service`.
- `write_cidr_file()` (per-game ipset) оставлен для совместимости; лаунчер
  использует пулы.

### Троттлинг по SNI — не РКН, не флак (2026-09-25)
- Симптом: сайт отдаёт 200, но тело обрывается; браузер крутит спиннер.
- Кейс paimon.moe: HTML (53 КБ, identity) стабильно обрывался на ~20-24 КБ
  на ЛЮБОМ CF-эдже и на любом пути; gzip/br-версия (11.8 КБ) приходила
  целиком и мгновенно. Контроль: speed.cloudflare.com 100 КБ — 0.33с,
  www.cloudflare.com 1.3 МБ identity — 0.6с (2.2 МБ/с) → путь и Cloudflare
  ни при чём. Вывод: адресный троттл по SNI («первые ~20 КБ быстро, дальше
  стоп/копейки»). В реестре РКН домена нет.
- Метод диагностики: 1) identity vs `--compressed` + `--resolve` по разным
  эджам; 2) контроль того же CDN с ДРУГИМ SNI (speed.cloudflare.com);
  3) реестр. Малый сжатый ответ проходит, большой разжатый — нет, контроль
  чист → SNI-троттл.
- Фикс: домен в **списки** (desync/fake ломает классификацию SNI). hosts-пин
  НЕ нужен и не помогает (троттл не по IP). Живой winws2 перечитывает
  hostlist по mtime — правка списка применяется без перезапуска обхода.
- Внесено: `paimon.moe`, `api.paimon.moe` → `lists/list-general.txt`
  (репо + зеркало). Проверено после правки: 53 637 Б за 0.21с (было
  ~23.5 КБ и обрыв на 30с).
- Бонус-кроссчек: `api.deepinfra.com` лечится так же — 125 228 Б за 1.2с
  вместо 16 185 Б/стоп (прошлый вывод «только WARP» неверен; достаточно
  добавить в список). В релизный список не добавлен — это API, не сайт;
  при нужде юзер добавляет через GUI.
