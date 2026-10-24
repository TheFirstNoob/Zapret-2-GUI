# AGENTS.md — Критические находки (АРХИВ полного снапшота)

> **АРХИВ (2026-10-24).** Это полный AGENTS до сокращения. Не использовать как
> текущую инструкцию; актуальный файл — `../AGENTS.md`, индекс — `../README.md`.
> Внутренние ссылки/версии могут быть устаревшими.

> **Последнее обновление: 2026-10-10 (Pre-Release 0.9 выпущен; октябрьские кейсы — REVIEW_VERDICT, VOICE_FLAP_FINLAND_2026-10, WARP_NOTES_2026-10, аудит hosts-пинов)**
> **Размер EXE:** 19.4 MB. Сборки актуальны (build.py / build_portable.py / build_lite.py).
> **Статус:** `default.txt` — универсальная стратегия; Discord-блоки на repeats=8.
>
> **Эта информация теряется при сжатии контекста ИИ.**
> Новый агент ДОЛЖЕН прочитать этот файл перед редактированием кода или тестированием.

---

## ⚡ СЕССИЯ-СНАПШОТ (читать первым)

### Текущее состояние (2026-10-12)
- **VERSION = "Pre-Release 0.10"** — выпущен 12.10 (тег `Pre-Release-0.10`
  = `3fd25f0`, GitHub Release опубликован, immutable; живой тест 0.9→0.10
  пройден). После тега +37 коммитов (апдейтер-полировка, hosts.txt в
  дистрибутивах, погодные пины, ipset-база 26441, faceit/valve/rf4game,
  голос-кейс → README FAQ и др.) — всё это уедет в 0.11.
  **0.11 не спешим**: свободное время — QUIC/библиотечные пробы;
  приоритеты — в бэклоге ниже.
- **Пресеты: 11 release** (default, default-alt, auto, fake-only, fakedsplit,
  fake-disorder, fake-multidisorder, hostfakesplit, multisplit-pure,
  multisplit-seqovl, tcpmd5-fake). Тестовые exp-/cand- пресеты УДАЛЕНЫ из репо
  (12.10, добавлены в .gitignore; сборки их и так исключали; новые тесты —
  только из untracked/временных файлов).
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
- **Предупреждения «место запуска» (вошло в 0.9)**: из архива (%TEMP%),
  Загрузки (MOTW), Документы (OneDrive), рабочий стол (замусоривание):
  `main.py::_check_launch_location` (MessageBox) + `core/diagnostics.py::_check_launch_spot`
  (чек «launch_spot») + `known_desktop_dir` в utils.
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
3. **Фейк = валидный ClientHello с SNI, остальное неважно.** Обязательны только
   две вещи: синтаксическая валидность (winws2 и ТСПУ должны его распарсить) и
   **наличие SNI** — блокировка HTTPS идёт по SNI (EXTERNAL_NOTES §1, 17.5.3), а
   ТСПУ классифицирует по **доминирующему SNI** (§4 ниже: доля ≥90% = пропуск).
   Отпечаток (JA3/размер/набор шифров/GREASE/padding) на **обход** не влияет:
   виндовый дамп `sochi_park` пробивает так же, как google (STRATEGY_TRIALS
   §«Блоб фейка не влияет»). Но размер блоба НЕ бесплатен по трафику: payload
   режется по `mss - extra_len` (`rawsend_dissect_segmented`), поэтому блоб >MSS
   идёт двумя сегментами, и на приветствие при repeats=8 получается ~15 КБ
   против ~2 КБ. Это меняет распределение размеров пакетов, которое ТСПУ
   анализирует (tspu-docs 23.1) — на Т2 для блобов <MSS нейтрально, для
   1889/1907 Б у нас замеров НЕТ. Второе место, где важен размер: блоб в
   `seqovl_pattern` — берётся ровно N байт от начала, а если блоб короче N,
   `pattern()` его **повторяет** (`string.rep`), т.е. короткий синтетик даст
   тройной повтор. Вариативность на сессию даёт не файл, а
   `tls_mod=rnd,dupsid`. Проверка: `python tools/tls_blob_report.py`.
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
- Мегафон-пользователь — ЗАКРЫТ (15.10): 0.10 стоит и всё сделано; причина
  «ютуб не работает» — тот же прикол с DNS/DoH ВНУТРИ браузера (как §13).
- VM-тест с облаком Защитника — СНЯТ (15.10): AV не ругается либо редко
  помечает !ml (рандом ML-эвристики, ожидаемо); ложные срабатывания уже
  снижены — держать это состояние до сборки 0.11.
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
- Возможные фичи (обсуждены): автоподбор desync-параметров, Diagnoser-реворк.
  ОТКЛОНЕНО/СНЯТО (15.10): «Починить GitHub» кнопка (Fastly-проба + hosts) —
  эффект временный (бан raw-подсети, вероятно, случайный РКН; правильное
  лечение — листы/DPI); массовая выдача hosts-пиннов концентрирует трафик
  всех юзеров на несколько Fastly-IP → их быстро банят (API вечно 0), а
  концентрация выглядит как ботоводство → риск бана ВСЕЙ сети; Minecraft
  (закрыт); blob rotation (zapret2 стабилен, ротация — идея zapret1).

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
- **18.10.2026 (ревью-раунд 5): 8.3 — только аварийный bat-фолбэк.** Основной
  запуск и служба используют ДЛИННЫЕ пути через @conf; при недоступных 8.3
  bat пишется UTF-8 без BOM + `chcp 65001`. `_warn_if_bad_path` больше не
  блокирует запуск и не показывает MessageBox («не запустится» — устарело);
  диагностика «Путь установки»: кириллица без 8.3 = **warn**, не fail.

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
- **Discord Media TCP / стрим (live 2026-10-23):** `default`/`default-alt`
  (fake+multisplit) и fake-only периодически роняют стрим; `auto` держит
  только после ротации на strategy=3 — чистый multisplit (`pos=1`,
  `seqovl=681`, `repeats=7`). Вывод: для media fake не помогает; рабочий
  вариант — `auto`, оставлен как есть. `default`/`default-alt` не менялись.
  `circular` ротирует не по таймеру: 60 с — окно счётчика неудач,
  `--lua-gc=60` — GC Lua; после успеха `nstrategy` не сбрасывается.

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
- **18.10.2026 (parity lite↔GUI)**: lite приведён к безопасному сосуществованию:
  start-*.bat отказывается, если winws2 уже запущен (GUI/lite/служба);
  stop.bat и service-remove гасят ТОЛЬКО службу zapret2 и winws2 ИЗ СВОЕЙ
  папки (name-wide taskkill убран); service-install/remove не трогают службу,
  установленную другой папкой (sc qc + findstr по %~dp0); lite-служба теперь
  ставит sc failure (restart×3/60с) как GUI; test.ps1 получает наборы хостов
  из core/tester_defs.py при сборке (анти-дрейф) и падает при чужом winws2.
  GUI-тестер в свою очередь детектит чужой winws2 (другая копия/lite) и
  возвращает engine_broken с понятной ошибкой, а не меряет вслепую.
  README lite: добавлены ограничения (тогглы GUI не настраиваются, общая
  служба, ручное обновление, test.bat — упрощённый).
- **18.10.2026 (lite-сервис)**: добавлены `fix-driver.bat` — аналог GUI
  «Выгрузить драйвер»: останавливает обход, проверяет ImagePath службы
  WinDivert и чинит его на `%~dp0bin\WinDivert64.sys` (`sc config ... start=
  demand`), застрявший драйвер выгружает (`sc stop WinDivert`); при занятом
  драйвере честно просит перезагрузку. И `update.bat`/`update.ps1` — проверка
  VERSION (GitHub raw → jsDelivr → api.github.com, числовое сравнение) с
  уведомлением и ссылками; автообновления у lite нет (обновление вручную,
  поверх, с сохранением user-списков). Меню service.bat: пункты 5/6.

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
- **Практическая перепроверка 2026-10-15 (матрица hosts×служба, скрипты
  `%TEMP%\opencode\gh_matrix.py` / `gh_focus.py`)**: на текущей сети блока
  НЕТ — ГОЛАЯ (hosts-пины сняты, служба STOPPED): raw→185.199.108.133 = 200
  ×3 (0.06-0.25s), asset/objects = 200, api = 200, jsdelivr = 200. hosts-пин
  (151.101.66.132) жив и БЫСТРЕЕ (0.07 vs 0.25s); desync/списки github НЕ
  мешают (raw 200 ×3 при выключенных пинах со службой). jsDelivr флакует
  сериями (был период 000/9s ×3 → затем 200 ×8; первый запрос 2.1s, далее
  кэш 0.07s). api `/releases/latest` = 404 — НОРМА (pre-release не
  «latest»), не блок. `nslookup` НЕ видит hosts (спрашивает DNS напрямую) —
  эффективный резолв проверять `ping`/`getaddrinfo`. Вывод: hosts-пины
  сейчас НЕ обязательны (не вредят, дают ускорение через Fastly; зависят от
  его живости), кнопка «Починить GitHub» не нужна (см. «Возможные фичи»).
  **jsDelivr-флак — не эффект обхода**: домена нет ни в одном нашем списке
  (десинк его не касается), а таймауты случались и на ГОЛОЙ сети (служба
  STOPPED) → `list-exclude-user` тут не при чём и не поможет. Если однажды
  станет ПОСТОЯННЫЙ блок — лечение наоборот В обход (list-general, зеркало
  обновлений), и только с пруфом окна; сейчас флак самопрошёл (200 ×5).

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

## Риск-свип перед релизом (чеклист 14.10 — из внешнего архитектурного ревью)

6 сканов по коду (~30-40 минут; ищем не «баги фич», а КЛАССЫ отказов на стыках
данные × ошибка × внешняя система — именно так ловятся баги, невидимые в
happy-path прогонах):
1. **Silent-default -> destructive sink**: все `return {}` / `except: pass` /
   `get(..., "")` -> проследить, не пишет ли получатель в файл/SCM/реестр
   (кейс: битый POST -> стёртый `list-include-user.txt`).
2. **Парные операции** (stop/start, pause/resume, create/delete): обязателен
   try/finally; исключение между «выключили защиту» и «включили» = инцидент
   (кейс: portable-апдейт оставлял службу выключенной).
3. **Клоны вызовов**: одинаковые блоки (`ctrl.start` x4) диffить ПО ПАРАМЕТРАМ —
   в одном месте потерялся `discord_alt`.
4. **Read-modify-write внешних систем** (SCM/hosts/реестр): мутация только
   после УСПЕШНОГО чтения (кейс: `pause_recovery` безусловно сбрасывал
   failure-actions).
5. **Единый владелец ресурса**: любой запуск winws2 обязан знать про службу
   (CDN-ручки зовут controller напрямую -> потенциальный дубль winws2 через
   SCM-recovery; чинить через общий svc-aware restart).
6. **Data-loss ручки**: каждая запись пользовательских файлов требует явный
   payload-ключ; невалид = 400, файл не тронут.

Запускать: после крупных фич и перед релизом (пункт в RELEASE_CHECKLIST).
Открытые по итогам скана: service-ветка в CDN-ручках (+ живой VM-тест).

## @config_file у winws2 — исследование 14.10 (МЕХАНИЗМ РАСКРЫТ; НЕ внедрено)

Подробно: `AI_DOCS/ARG_FILE_RESEARCH_2026-10-14.md` (ред.2: тест-матрица, план, хвосты).
Кратко для будущих сессий:
- На Windows `@file` раскрывает РАНТАЙМ CYGWIN до main() (`cygwin1.dll`,
  `dcrt0.cc`: build_argv/insert_file): любая позиция, несколько @file, рекурсия
  ≤10 уровней, размер до ~4ГБ (16КБ-лимит zapret НЕ действует), контент парсится
  cmdline-парсером Cygwin (DQ/SQ-кавычки работают; globify при *?[]).
- Ловушка: кавычка ПЕРЕД @ (`"@file"`) отключает раскрытие -> токен проваливается
  в zapret-wordexp-путь (Linux-путь) — на Cygwin он ПАДАЕТ («failed to split»);
  `$file` на Windows не работает. Пробелы в @-пути: `@"C:\...\run conf.txt"`
  (кавычки вокруг ПУТИ, @ снаружи) — проверено rc=0.
- Контент: токены только `--opt=value` (никогда не начинать токен с `@` — иначе
  вложенное раскрытие; это был июльский баг `--lua-init @path`, фикс ae5536d);
  hostlist/ipset — обычные пути БЕЗ @; lua-init — `@`; значения с пробелами — в DQ.
- Цель: binPath службы `"winws2.exe" @service_run.conf` (~80 симв) — смена
  стратегии = перезапись + restart. ✅ PoC службы выполнен 14.10: оба варианта
  (без пробелов и `@"..."`) работают end-to-end (start/лог/stop; SCM передаёт
  аргумент вербатим). ⚠ повторные пробы с тем же wf-фильтром ловят dup-mutex.
- ✅ Этапы 1-3 внедрены 14.10: launcher/tester — запуск/валидация через
  logs/run.conf (`"exe" @"conf"`), stderr winws2 → logs/winws2_last_stderr.log,
  LANG=C.UTF-8; служба — binPath короткий `"exe" @"logs\service_run.conf"` +
  legacy-миграция (migrate_if_needed, CommandLineToArgvW; живой прогон зеркала
  3854→151 симв, golden 117/117, бэкап в mirror/logs). Этап 2 (bat/lite) —
  start-батовые conf-файлы + service-install echo-блок (песочница проверена).
  Тираж-раунд 2: CDN-ручки через ветку службы; квотирование DQ для
  пробелов/бэкслэшей/'/[]; validate fail-closed (флаги дублируются в argv);
  long-пути в контенте (short_path — только для bat). Golden-инструмент:
  `tools/check_arg_file.py [--quoting]`. Хвосты: path_status (PATH_MISMATCH) и
  1072 (порядок ревизован) закрыты; принятые решения (pause-trade-off, conf в
  logs/) — док §6.

## Рефакторинг по ARCH_AUDIT (с 14.10)

План-рекорд: `AI_DOCS/ARCH_AUDIT_2026-10-14.md` (снимок 86d1634, прогресс в §8).
Порядок (скорректирован советником 14.10): 8→6 → 7(proc) → 4(args-конвейер,
golden) → 10(StrEnum+контракт-тест) → 1(server: AppContext+DI, хендлеры
возвращают dict) → 3/5 → 9 → 2(app.js ПОСЛЕДНИМ; склейка файлов на сервере,
ES-модули нельзя). #8, #6, #7, #4, #10 закрыты 14.10 (golden-страховки:
`tools/args_golden.py`, `tools/check_arg_file.py`, `tools/status_contract.py`).
Инварианты распила — §7 аудита (сигнатуры build_args/write_manifest, порядок
трансформов, wire-строки статусов, cache-buster "js/app.js", локи). #8 закрыт
14.10 (единый парсер листов).

## Хосты / AI-пины (2026-09-24) — не гонять пачками

- Воркер AntiZapret 193.233.112.68 живой на прямом маршруте (claude.ai 302,
  api.openai.com 401, gemini/copilot 200), НО флакает и троттлит при серии
  запросов; под WARP он мёртв (000). Наши прежние 45.155.204.190 /
  37.230.192.51 деградировали - 143 пина в hosts.txt переключены на
  193.233.112.68 (коммит fbf248e).

- **ГЕОБЛОК != РКН (урок 12.10)**: OpenAI/Anthropic и другие AI-сервисы НЕ забанены
  РКН — они сами блокируют РФ-IP. Маршрут к ним ТОЛЬКО через не-RU выход: воркер,
  Comss-релеи или WARP. Прямые IP (CF и пр.) бесполезны: HTTP `403` со страницей
  `blocked-icon` (= геоблок, не бот-чек; проверено 12.10 curl-ом). Воркер
  интермиттентно хандрит на chatgpt-семействе (таймауты; вероятно саморазогрето
  сериями наших запросов) — НЕ долбить параллельно: 153-поточный аудит ложно
  показал «всё мертво» (троттлинг); аудит только последовательно с паузами.
  Twitch — НЕ гео-сервис: мёртвые пины `gql.twitch.tv`/`usher.ttvnw.net` сняты
  12.10 (воркер их не отдаёт; идут через Comss-релеи; Twitch ожил).- Сторонние Smart-DNS-резервы деградировали и сняты с использования
  (2026-10-10; один из них дополнительно заблокирован РКН 09.10.26) —
  **не используем и не упоминаем** (решение 12.10: «снимаемся полностью,
  дабы не светиться»). Пины перевешены на воркер `193.233.112.68`
  (проверено 10.10: gemini/openrouter/copilot/grok — 200). Кандидат
  pumPCin (AntiZapret) `62.133.62.97` у нас не отвечает (таймаут) — при
  раздаче перепроверять.
- **Comss.one DNS - живой источник «золотых» IP (проверено 2026-10-10)**:
  серверы `83.220.169.155`, `195.133.25.16`, `212.109.195.93` (старые
  `185.71.66.225`/`.221` устарели - не отвечают; их же V3nilla держит в
  exclude.txt). Отдаёт пул `gemini-pool.comss.one` ->
  `157.22.178.170`, `157.22.177.90`, `132.243.112.221` (пул на 12.10;
  старый `95.81.102.20` ушёл). Пул проверен вживую (curl --resolve -> rc=0). DoH:
  `https://dns.comss.one/dns-query` (RFC8484; `curl --doh-url` работает).
  Кандидат в резерв/основу для системного DoH и как источник IP; DOOM-пин
  у V3nilla (`95.81.98.135 ghostrc.game.idtech.services`) - оттуда же.
  Решение 12.10: актуален и допустим как альтернативный DNS (ожидаемо
  стабильнее/быстрее); в README пока не выносим.

  **Полевые тесты 12.10 (`comss_probe.py`)**: plain53 `83.220.169.155`/
  `212.109.195.93`/`195.133.25.16` живы (~30-34мс); DoH `dns.comss.one` 144мс;
  DoT `dns.comss.one:853` жив; DoQ `quic://dns.comss.one` (рантайм не гоняли).
  **Smart-DNS: ЕДИНЫЙ пул релеев `157.22.178.170`, `157.22.177.90`,
  `132.243.112.221` (+`132.243.112.38`) отдаётся под gemini/chatgpt/grok/
  claude/openrouter/elevenlabs/genspark/sora/notion/autodesk**; youtube —
  альтернативные Google-IP; instagram — альт. Meta-IP; discord/rutracker/
  yandex — без изменений; `doubleclick.net` -> `0.0.0.0` (адблок).
  Релеи проверены `curl --resolve`: chatgpt/gemini/copilot/openrouter 200,
  notion 301, claude 403 (CF-ботозащита curl — в браузере вероятно ок).
  Caveat: релеи — их инфраструктура, SNI виден (класс доверия как у
  AntiZapret-воркера). **Векторы**: (a) кандидат в рекомендации как системный
  DNS (разлочка AI без обхода + адблок; решится отдельно); (b) fallback-пины
  для AI-доменов, если наш воркер умрёт; (c) `dns.comss.one` — «чистый»
  резолвер-кандидат в DoH-чек (бэклог №1).

  **Решение 12.10 (машина автора)**: системный DNS WiFi переведён на Comss
  (83.220.169.155, 212.109.195.93; DoH-шаблоны https://dns.comss.one/dns-query
  через 
etsh dns add encryption ... autoupgrade=yes udpfallback=yes — PS
  Set-DnsClientDohServerAddress не сработал для кастомных). Проверено системным
  резолвом: doubleclick.net -> 0.0.0.0 (адблок), www.youtube.com резолвится,
  chatgpt.com -> воркер-пин (hosts приоритетнее — не тронут). Откат:
  Set-DnsClientServerAddress -InterfaceIndex 15 -ResetServerAddresses +
  
etsh dns delete encryption server=.... В README пока не выносим.
- **Аудит пинов hosts (2026-10-10, пробы «пин vs голый» при живом обходе)**:
  удалены мёртвые/мешающие - вся группа `103.27.157.38` (Tidal/Supercell/
  TikTok: TLS-сертификаты не совпадают, rc60; голое 200), `172.64.33.155`
  d.rutor.info (403 vs 301), `45.155.204.190` corp.google.com/withgoogle.com
  (воркер мёртв), `193.233.112.68 claude.ai` (воркер 403, голое 302).
  Оставлены осознанно: Fastly-пины GitHub (оба 301 - резерв на плавающий
  IP-блок), discord.com (оба 200, безвредно), Telegram `149.154.167.220`
  (нужен под WARP), `platform.claude.com` (голое 403 - пин обязателен),
  grok (голое 403). Воркер 193.233.112.68 в целом жив (gemini/openrouter
  200, copilot 200).
- Telegram в РФ прибит по IP: пин работает только через WARP/прокси; клиент
  ходит своими DC (hosts на него не влияет).
- claude.ai: воркер начал отдавать 403 (голое 302) - пин снят 2026-10-10;
  platform.claude.com/console.anthropic.com на воркере живы. У сервисов
  бывает флак - перепроверять одиночными пробами.
- **Окончания строк: `.gitattributes` (13.10)** — LF везде; CRLF только
  для `*.bat`/`*.cmd`/`*.ps1`; `hosts.txt` и `*.sig` байт-стабильны
  (`-text`, блоб CRLF). Системный hosts держать байт-в-байт копией
  репо-файла (бэкапы `hosts.bak_*` в `drivers\etc`). При правках
  текстовых файлов писать LF (кроме исключений) — иначе полный построчный
  дифф (кейс `server.py`, 13.10).
- Правило: проверять одиночными запросами с паузами; массовые прогоны
  (10+ запросов подряд) уводят воркеры в лимит на десятки минут.
- **Голосовые сервера Discord НЕ пинить через hosts — правило (2026-09-28)**:
  без свежего теста «номер активен + верный IP» любой пин только УБИВАЕТ
  голос; унаследованные пины из эпохи Zapret 1 — особенно (номера ротируются,
  пин на ушедший диапазон = чёрная дыра). Рабочие эндпоинты
  (`c-ams15-<hash>.discord.media`, `finland14016.discord.media`) резолвятся в
  Cloudflare-набор `162.159.x`. **Discord поднимает DNS только для АКТИВНЫХ
  голосовых номеров** (неактивные — no answer), а номера ротируются. Блок
  `finland10000…10199` → `104.25.158.178` (200 строк) был актуален в эпоху
  Zapret 1 и стал миной: когда клиенту выпадал номер из диапазона, пин уводил
  голос на чужой IP (кейс: «финка то работает, то нет», Роттердам ок;
  после удаления финка `finland14016` — 26 мс, 0% потерь). Удалено из
  hosts.txt и системного hosts.

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
- **self-heal** (`main._heal_missing_data`): для SYSTEM-файлов из `key_files`
  (bin/*, lua/*, lists/list-general.txt, presets/default.txt) эталон — копия
  в `_MEIPASS`. Файл пропал / обрезан (AV/OneDrive) / отличается от эталона —
  восстанавливается на каждом запуске (размер — быстрый шорткат, при совпавшем
  размере сверяется sha256; раньше только размер, из-за чего правка того же
  размера выживала). **user-файлы** (`lists/*-user.txt`, `lists/games/`,
  `presets/custom.txt`, не-релизные `presets/*.txt`, `games.json`,
  `zapret2_config.json`, `logs/`) heal не трогает НИКОГДА — и не должен
  попадать в `key_files` при расширении списка. Работает только в onefile
  (`_ensure_data_dir` для не-frozen до heal не доходит): portable/lite и
  dev-копия не затрагиваются.
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
- [закрыто в 0.9] Пересборка exe (onefile) и portable после рефактора
  (`COPY_DIRS` включает core/server; сборки выпущены).
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
- QUIC-пробы (2026-10-12, niquests+qh3, `tools/quic_probe.py`): впервые
  измерен QUIC-путь под живым обходом — google/cloudflare/googlevideo
  делают H2->H3-апгрейд и отвечают по HTTP/3 (204/200, быстрее H2); наш
  QUIC-фейк H3 НЕ ломает. `www.youtube.com` в тестах падает не из-за QUIC,
  а из-за спуфленного системного DNS (NameResolutionError); с DoH-резолвом
  youtube/i.ytimg отвечают 200/204. Шиппинг QUIC-пробы в тестер — отдельное
  решение (нативный qh3 => вес сборки/Defender).
- **Бэклог (следующий релиз 0.11, сроки свободные; автор: +5-6 МБ к сборке —
  приемлемо):** приоритет №1 —
  **DoH DNS-спуф-чек + резолв в тестере/диагностике** (дёшево, чистый curl) —
  ✅ ВЫПОЛНЕНО 15.10 (детали — ARCH_AUDIT §8): тестер при ошибке резолва
  (curl rc=6) повторяет пробу по IP из DoH (--resolve; пометка в детали);
  диагностика — чек «Системный DNS (спуф)»; H3-проба без DoH (сознательно).
  Замер под обходом 2026-10-12 показал, что «квирки» не однородны:
  `i.ytimg.com` (в list-google, т.е. ПОД desync) и `google` отдают 204/204
  голым curl; `storage.googleapis` 400; `www.youtube.com` падает у ВСЕХ
  клиентов НА DNS (спуф системного резолвера, «Could not resolve host»);
  `redirector.googlevideo.com` (curl 000, niquests 204) и `youtu.be` (000) —
  флап пула IP. Нейтральная пометка квирков в тестере частично маскирует
  реальные проблемы. Далее: (2) QUIC-проба (niquests+qh3) — вторичная
  точность (QUIC-фейк H3 не ломает, H2->H3 апгрейд живой); решить по
  метрике. (3) опционально — UDP-сниффер вместо pktmon (у pktmon есть
  эффект добавления дропов, см. VOICE_FLAP док): кандидат **pydivert** —
  жив (4.0), «seamless multi-handle» с winws2 официально поддержан
  (kernel priority chaining), wheels с WinDivert внутри; учесть лицензию
  LGPL-3.0/GPL-2.0. **Решение 15.10: в сборку 0.11 НЕ берём** — python +
  WinDivert-sniff = классический !ml-паттерн для AV (а ложные срабатывания
  снижаются, не добавляем), плюс два клиента WinDivert-драйвера рядом с
  движком (интерференция версий), вес; pktmon работает, его дропы — лишь
  методическая погрешность. Максимум — отдельный dev-инструмент вне EXE,
  с живым тестом. **Собран 15.10: `tools/pydivert_sniff.py`** — пассивный
  SNIFF-захват (пакеты не изымаются), счётчики OUT/IN по IP:port, домены из
  DNS-ответов (53) + TLS SNI (TCP:443) + DNS-кэша; живой смок прошёл (поймал
  SNI raw.githubusercontent.com -> Fastly-пин и DNS example.com; служба/движок
  не затронуты; `.sys` из wheel'а pydivert байт-в-байт == наш bin).
  Альтернатива qh3 для QUIC-пробы — **aioquic** (BSD-3,
  ~2k★, чистый Python, но зависит от cryptography — вес примерно тот же).
  BlockCheck (ValdikSS) — АРХИВИРОВАН 28.07.2024 («not working»), не тащим.
  Gakido — существует, но 0.2.0/sdist-only, h3=aioquic-обёртка, mkdocs в
  рантайм-зависимостях — не наш вариант. Его native TLS (Go+uTLS,
  byte-accurate JA4) — колёса только Linux/macOS; на Windows сборка с Go.
  Тот же класс на Windows уже покрыт curl_cffi (проверен); эталон проверки
  отпечатков — tls.peet.ws / tls.browserleaks.com.

  Решения 12.10: ipset-БАЗА уже обновлена (`1ab7750`, 26441 CIDR) — фича
  автообновления остаётся опциональной; апдейт winws2 — ждём 1.0.6 (1.0.5.2
  без разницы для нас); блобы (вкл. Flowseal ACTIVE_*, MIT) живы — A/B по
  желанию; 0.11 не торопим — QUIC/новые библиотеки гоняем не спеша. Тумблер
  «UDP-длина» на главной ОСТАЁТСЯ (нам на блоченных финах ломает, другим
  сетям может помогать).
  **Точность тестера — инструменты готовы (12.10, `tools/`, проверено вживую)**:
  `quic_probe.py` — forced-H3 (`disable_http1/2` + preemptive `quic_cache_layer`),
  успех только при `http_version==30`, skip воркер-пинов, внешний wall-clock,
  DoH-фолбэк. `upload_probe.py` — POST-N байт, учёт `size_upload/size_download/
  time_total`, вердикт `LIKELY_BLOCKED` («ТСПУ-яма»: ушло/ответа 0/время на
  пределе; идея из теста Flowseal). `tls_ver_probe.py` — pinned-TLS
  (1.2-only/1.3-only). Пруф: `i.ytimg.com` — H3 204 при мёртвом TCP у curl;
  воркер-пины -> SKIP; ya.ru/CF/yt — ок. Интеграция в тестер — по контрактам
  ревью: strategy-test = свежие соединения, bulk = multiplexed; H2 — только
  диагностика; DNS-таксономия OK/mismatch/suspicious/failed; niquests
  env-proxy off; внешний дедлайн обязателен.
  **Интеграция выполнена (12.10)**: реальная H3-проба внедрена в
  `core/tester.py::_quic_h3_probe` — квирк-хосты при 000 получают настоящий
  вердикт (`QUIC` с «H3 подтверждён» или `BLOCKED`); без niquests — прежняя
  эвристика (graceful, кэш-флаг `_has_niquests`). Проверено обоими путями
  (i.ytimg: «H3 подтверждён (H3 404)» с либой; «нет niquests» без). Upload уже
  покрыт tcp1620 (64КБ); tls_ver — диагностика, UI позже. UI: словарь статусов
  не менялся (таблица работает как раньше), деталь — в `TestResult.error`.
  Ревью 12.10 (внешнее) подтверждено по фактам: (1) build-обвязки не было —
  ИСПРАВЛЕНО: `requirements.txt`/`build_portable.py` ставят `niquests[http3]`,
  `Zapret2GUI.spec` — collect_all стека (niquests/urllib3_future/urllib3/qh3/
  wassima/jh2), `h11` УБРАН из EXCLUDES (нужен niquests); проверить сборки на
  чистой машине при следующем релизе. (2) Ошибка H3 больше НЕ BLOCKED: статус
  `H3_NONE` (нейтрален, не в ok/fail-статистике; до этого BLOCKED попадал в
  fail_count — регрессия, откачено). (3) Поток-сторож не убивает QUIC-запрос
  (daemon-хвост) — ограничен внутренними таймаутами (4,8); жёсткая отмена =
  отдельный процесс, избыточно. (4) README обновлён (3 состояния QUIC).
  (5) Extra-имя — `http3` (не `h3`), исправлено в tools/сборках.
  Внешний ревью-отчёт 13.10 (`AI_DOCS/REVIEW_REPORT_2026-10-13.md`, база
  `179d00c`) обработан: все P1/P2/P3 верифицированы и подтверждены. Фиксы:
  spec падает без niquests-стека (был тихий пропуск -> exe без QUIC), docs:
  `pip install -r requirements.txt`; `trust_env=False` в H3-пробе (env-прокси
  ломали); UI: `H3_NONE` -> нейтральный маркер (был красный ✗ в финале), чип
  `QUIC_UNKNOWN` вместо ложного `QUIC_OK` (+ время с пробой); server: `rated`
  учитывает www-алиасы control; `tls_ver_probe`: rc=35 без unsupported-маркеров
  = FAIL; мелочи wording. «Не-находки» ревьюера приняты.
- `speech.platform.bing.com` (edge-tts, 2026-10-12): симптом на чужой сети —
  TCP:443 открыт, WSS-апгрейд флапает 403/ок. **В списки НЕЛЬЗЯ**: проба
  добавления в list-general ПРОВАЛЕНА — наш desync ЛОМАЕТ домен (curl 3/3
  таймаута после подхвата листа; break-class, как погодные API), откатано.
  DNS чист (система = DoH = AFD `150.171.27.10`/`150.171.28.10`) — hosts-пин
  не обязателен. **Подтверждено заголовками 403** (снял агент с той машины):
  `X-MSEdge-Ref` (Ref B: FRA… — живой эдж MS Front Door, Франкфурт), HSTS,
  `Access-Control-Allow-Origin: *`, `X-Cache: CONFIG_NOCACHE`, тело пустое —
  это анти-бот/WAF самой Майкрософт, НЕ подмена/MITM и не тракт. Фикс:
  смена выхода (WARP на время озвучки) или ретраи с backoff (в их шлюзе уже
  4 попытки — гасят блипы).
- Погодные API (2026-10-11): рабочие пути — `weatherapi.com` (пин
  `138.199.37.231` для www+api), `api.openweathermap.org` (пин
  `176.9.63.49`), wttr.in ТОЛЬКО API (`/Moscow?format=3`; сайт троттлится),
  PirateWeather как есть. `api.open-meteo.com` — блок по IP без альтернатив
  (только WARP), сайт openweathermap.org — тоже. **В списки НЕЛЬЗЯ**: desync
  их ломает (wttr/OWM/weatherapi падали таймаутами) — break-class; рабочий
  инструмент — hosts-пин. Пины лежат в `hosts.txt` с комментарием.
- CurseForge/Minecraft (2026-10-12): у человека со старым «Запрет 1» не
  качались сборки. Наш замер: **у нас всё живо** — DNS чист (sys=DoH),
  `maven.minecraftforge.net` 200, `edge.forgecdn.net` 200, fabric meta/maven
  200, Forge-инсталлер 5.97 МБ качается 1.7 МБ/с (mediafilez/media 403/404
  = CloudFront без корня, не блок). В наши списки НЕ добавлять (не
  блокируется). Вывод: ломает ИХ старый обход/списки — лечится обновлением
  до 0.10 (или исключением `curseforge.com`/`forgecdn.net`/
  `minecraftforge.net`/`fabricmc.net`/`overwolf.com` из их обхода;
  IP-catch-all выключить — он десинкает CDN и рвёт большие загрузки).
- Референс «Запрет 1» (разбор пресета 2026-10-12, winws.exe-бандл):
  магии под 50000+ НЕТ — порты только в `--wf-udp` (как у нас) + сегмент
  `--filter-udp 19294-19344,50000-50100 --filter-l7=discord,stun` с fake
  РЕАЛЬНЫМ записанным Discord-UDP (`ACTIVE_DISCORD_UDP.bin`), repeats=6.
  Отличия их архитектуры от нашей: (1) **ipset-all сегменты ВСЕГДА**
  (TCP 80/443/8443 + UDP 443, fake+multisplit) — потому их десинк может
  рвать живые CDN (Cloudflare API + CloudFront-загрузки — вероятная причина
  кейса CurseForge-манифеста); у нас ipset — только opt-in catchall;
  (2) фейки реальными записанными payload'ами (`ACTIVE_*`); (3) repeats=10-11
  на UDP (QUIC/игры) против наших 1; (4) `max_ru`/`stun2` блобы для
  general/fake-http/unknown; (5) `--ip-id=zero`; (6) any-protocol +
  cutoff=n4 для игр. Кандидаты на наши A/B (`tools/ab_candidate.py`): (2)/(3)/(4).
  (4) Голос/стрим Discord на 50000+ (GCP): **эксперимент 12.10 проведён —
  отрицательно** (метрика: keepalive-пинги `voice_flap_watch`; провод: pktmon;
  подробно — VOICE_FLAP док, §«5000+ эксперимент»). Кандидаты (в истории git;
  тест-пресеты удалены при чистке 12.10): cand-voice-active/any/all/pass/
  udplen/badsum.
  НИ ОДИН не меняет клиентский лосс (фейки на проводе = есть, результат 0) —
  блок на обратном пути IP-уровня. Ключ механики: Lua `fake` по умолчанию
  трогает только known-пейлоады; «fake всего» = `:payload=all` (исходники:
  `nfq2/` + `lua/zapret-antidpi.lua:449`). Финал 12.10: свежий поток (Ctrl+R)
  мёртв с рождения (новый GCP-эндпоинт); под passthrough (`cand-voice-pass.txt`
  — 5000х вне перехвата) RTC вообще не коннектится -> блок внешний; fake-all
  давал 1/12 против 3/12 у default (фейки слегка вредят); канал на CF-эндпоинте
  (`104.29.153.151:19305`) работает. Вопрос закрыт: клиентских средств нет;
  практика — CF-регион/WARP/переезд сервера. Догон арсенала (13:43-14:02):
  `udplen`/`badsum`-фейки — гасят поток сами (0/12, восстановление при
  снятии); `pktmod` — только порча своих пакетов (пропущен осознанно). Финал:
  свежий старт под passthrough — RTC мёртв сразу; поведение блока штатное.
  Решение 12.10: другой голосовой регион (CF); WARP-сплит/WG-точечность — костыль,
  ЗАКРЫТО; отмечено в README (FAQ про голос). WARP consumer include-режима не
  имеет (exclude-only) — проверено по GUI/CLI.
  Для UDP арсенал исчерпан (подробно — VOICE док).

- Flowseal актуалии (сверка 2026-10-12, репо 34.6k★, последний push 01.10):
  ALT11-серия практически не изменилась (всё та же жёсткая fake+multisplit +
  always-ipset) — их ALT-пресеты способны рвать CDN (кейс CurseForge-друга).
  **Их новый дефолт `general.bat` — мягкий: TCP ВЕЗДЕ multisplit БЕЗ fake**
  (включая ipset-сегменты), fake только на UDP; блобы `4pda_to`; games UDP
  repeats=12. В `list-exclude.txt` есть `minecraft.net`/`multimc.org`/`steam*`,
  но НЕТ `curseforge/forgecdn/fabricmc/overwolf`; user-исключения они
  уважают (list-exclude-user.txt). «Смена источника» (01.10) = переезд
  источника их lists/hosts/ipset (`.service/`: hosts, ipset-service.txt 539КБ).

### §24. WebView2: fallback на браузер (план, 2026-10-24)
- **Кейс:** Win10 22H2 без WebView2 Runtime → pywebview молча ушёл в
  MSHTML/IE, окно белое. Установка Evergreen WebView2 помогла.
- **Текущий код:** ловит ImportError и исключение `webview.start()`, но
  preflight Runtime/.NET нет; README «встроен в Win10/11» неточен.
- **План:** `AI_DOCS/PLAN_WEBVIEW2_FALLBACK.md`.
  1. preflight WebView2 + .NET 4.6.2 + понятный MessageBox со ссылкой;
  2. затем browser fallback: локальный сервер + Edge/Chrome `--app`
     (или вкладка современного браузера), т.к. фронт уже чисто HTTP
     (pywebview.api не используется);
  3. обязательные хвосты: lifecycle/ heartbeat, single instance, токен
     не в истории/синке, не запускать elevated-браузер, тесты Win10/11.
- **Не делать:** бандлить Fixed Version Runtime без отдельного решения;
  переписывать UI на Qt/CEF; включать fallback по умолчанию, пока не
  пройдены тесты.
