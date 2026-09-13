# AGENTS.md — Критические находки (чтение обязательно перед любыми изменениями)

> **Последнее обновление: 2026-09-13 (Pre-Release 0.7.1; UI ведёт отдельный агент)**
> **Размер EXE:** 19.4 MB. Сборки актуальны (build.py / build_portable.py / build_lite.py).
> **Статус:** `default.txt` — универсальная стратегия; Discord-блоки на repeats=8.
>
> **Эта информация теряется при сжатии контекста ИИ.**
> Новый агент ДОЛЖЕН прочитать этот файл перед редактированием кода или тестированием.

---

## ⚡ СЕССИЯ-СНАПШОТ (читать первым)

### Текущее состояние (2026-09-13)
- **VERSION = "Pre-Release 0.7.1"** (config.py + VERSION-файл; релизы 0.7 и 0.7.1 на GitHub).
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

### ВИСИТ (не сделано)
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
- Discord-блоки: с nodrop и без — оба 200 (A/B 2026-09-12), nodrop оставлен.

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
  заработало. Авто-фикс: `fix_stale_windivert_services()` вызывается перед
  КАЖДЫМ запуском winws2 (launcher) и перед install (service_manager) —
  удаляет только службы с несуществующим ImagePath. Чеки: diagnostics
  «Служба драйвера WinDivert» (ImagePath dead / Start=Disabled) и
  «Файлы WinDivert». Тестер-аборты пишут причину в test_session.log.