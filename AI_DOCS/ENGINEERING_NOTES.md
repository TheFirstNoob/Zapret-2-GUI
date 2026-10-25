# Engineering notes — параметры, источники и история решений

> Собрано 2026-10-24 после чистки `0bd6626`, из удалённых
> `AI_DOCS/archive/*` и текущего кода. Это **справочник для будущих сессий**:
> где брать данные, какие параметры крутить, что уже проверено и что
> переоткрывать не нужно.
>
> Текущий код — авторитет. Даты у historical-фактов сохранены. Полные
> оригиналы удалённых документов остались в git-истории:
> `git -C <repo> show 0bd6626^:AI_DOCS/archive/<file>.md`.
>
> Внимание: в старых документах есть региональные/провайдерские/публичные
> IP и пользовательские кейсы. В git их заново не добавлять; чувствительные
> детали — только локально (`%TEMP%\opencode`).

## 1. Источники и как обновлять

| Что | Источник | Как использовать |
|---|---|---|
| Движок winws2 | `github.com/bol-van/zapret2`; win-bundle `github.com/bol-van/zapret-win-bundle` | `bin/winws2.exe` **1.0.6**; обновлять движок и stock-lua вместе, `zapret-custom.lua` сохранять |
| WinDivert | `github.com/basil00/WinDivert` | `windivert/` + `bin/WinDivert*.dll/sys`; не чинить удалением при живом драйвере |
| Lua | `lua/zapret-lib.lua`, `zapret-antidpi.lua`, `zapret-auto.lua` — vendor; `zapret-custom.lua` — наш | vendor не рефакторить; обновлять только синхронизацией с upstream tag |
| IPset-база | V3nilla `github.com/V3nilla/IPSets-For-Bypass-in-Russia`; jsDelivr `https://cdn.jsdelivr.net/gh/V3nilla/IPSets-For-Bypass-in-Russia@main/` | наша база `lists/ipset-all.txt.gz` (26441 CIDR на 2026-10-24); **не вливать целиком**, только coverage-diff + CDN A/B |
| Реестр РФ | `github.com/bol-van/rulist`: `reestr_hostname.txt`, `reestr_smart4`, `reestr_ipban4`; raw base `https://raw.githubusercontent.com/bol-van/rulist/main/` | один GET + фильтр по семействам; не массово в ipset |
| ASN/DPI-пробы | `github.com/Runnin4ik/dpi-detector` (v4.2.4); `https://cdn.jsdelivr.net/gh/Runnin4ik/dpi-detector@main/tcp16.json`, `whitelist_sni.txt`, `domains.txt` | только диагностика; список IP протухает, обновлять через jsDelivr |
| Теория ТСПУ | `github.com/DanielLavrushin/tspu-docs` | локальный клон; SNI/деградация/двухстадийность |
| Механики обхода | `github.com/DanielLavrushin/b4` | RST/FIN/ACK, TTL, SNI-first; не переносить 1-в-1 |
| Референс Zapret 1 | `github.com/Flowseal/zapret-discord-youtube` | сравнение паттернов; чужие пресеты не вливать слепо |
| Обновления | `VERSION` в корне + raw GitHub / jsDelivr; Ed25519 release.json | не ослаблять fail-closed; зеркало jsDelivr — fallback |
| WebView2 | Evergreen WebView2 Runtime | preflight + browser fallback уже в `main.py` |
| WebView2 Runtime | `https://go.microsoft.com/fwlink/p/?LinkId=2124703` | ссылка в сообщении об ошибке |

Правила данных:
- `lists/list-general.txt` и остальные bundled-списки — курируемые, не
  автогенерируемые. User-файлы — `lists/*-user.txt`.
- `list-include-all.txt`, `list-games.txt`, `lists/games/_pool_*.txt` —
  генерируемые; вручную не редактировать.
- V3nilla/RKN — только источник кандидатов; широкий ipset лечит fix-класс,
  но ломает break-класс CDN (DO/Hetzner/OVH/Vultr/BuyVM). Решение по
  умолчанию: catchall выключен.
- ASN-скан — снимок, не приговор. Не сканить подряд и не делать вывод по
  одному прогону.
- ASN v2: скан сам глушит защиту и восстанавливает её service-aware;
  concurrency 4, `curl -S`, exit 28 различается по stderr (CONNECT/SYN DROP
  vs общий timeout), «не отвечает» подтверждается повтором. `example.com` —
  лучший белый SNI-зонд; чёрный SNI — контроль. Список `tcp16.json` протухает.
  Исторический ориентир: `example.com` 104/110, `hcaptcha.com` 84/110;
  одиночный прогон — снимок, не приговор; ASN-скан не влияет на стратегии.
  dpi-detector запускать обычным python: `python dpi_detector.py -t 34 --batch
  -o report.txt -c 30` (TUI/rich; не pythonw).
- Файлы данных: `lists/cdn-asn-probes.json` (110 ASN-проб),
  `lists/whitelist-sni.txt` (белые SNI), `lists/list-cdn-test.txt` (CDN-батарея),
  `lists/list-general.txt` / `list-google.txt` / `list-discord.txt` /
  `list-cdn-fix.txt` (курируемые), `lists/list-exclude*.txt` (исключения).

### Что известно о ТСПУ (tspu-docs)

- HTTPS блокируется по SNI; URL/путь внутри TLS не видны. HTTP — редирект
  на заглушку.
- `send RST off` — обычный режим: при блоке RST не приходит, соединение
  молча висит до таймаута (симптом `000`, не «сервер лёг»).
- Деградация вероятностная (capacity 0-100): отсюда «плавающие» 000 и
  чувствительность к объёму/повторам.
- DPI анализирует сессию/статистику, а не один пакет; повторяющиеся fake
  меняют доминирующий профиль. Повторы — тактический выигрыш, не гарантия.
- Двухстадийность: фильтр распознаёт → логи/списки обновляются → часть
  сессий может жить до обновления. Поэтому один замер = снимок.

### b4 (референс механик)

- SNI-first ClientHello — желательное правило; на проверенной сети не
  критично, но `make_blob.py` генерирует SNI-first.
- RST/FIN/ACK с испорченной TCP-суммой на проверенной сети не сработали
  (RST-off); оставить кандидатом для сетей, где RST реально шлётся.
- `dynamicTTL` соответствует нашей идее `ip_autottl=delta,min-max`;
  RST-protection в winws2/lua нет.

## 2. Параметры winws2 / Lua

### Запуск и аргументы

- Основной запуск и служба: `winws2 @"logs/run.conf"` /
  `@"logs/service_run.conf"` (длинные пути, cmd-лимит не мешает).
- Внутри conf/argv каждый токен — `--opt=value`; **никогда не начинать
  токен с `@`** (Cygwin раскроет как вложенный response-file). Исключение —
  осознанный `@conf` всего запуска.
- `--hostlist`, `--ipset`, `--hostlist-exclude`, `--ipset-exclude` — обычные
  пути; `--lua-init=@path` — `@` только в значении.
- `--hostlist-auto=<path>` — автолист (без `@`); `--autohostlist=@...` —
  неверная форма/старый флаг.
- `--new` разделяет профили. В профиле несколько `--hostlist` объединяются;
  побеждает первый профиль, у которого совпали фильтр и hostlist.
- `$file` на Windows не работает; Cygwin раскрывает только `@`, а `$`
  уходит в Linux-парсер и падает.
- `--wf-tcp-out` / `--wf-udp-out` — окно перехвата. `--filter-tcp` /
  `--filter-udp` + `--filter-l7` выбирают поток внутри окна.
- `--out-range=-dN` — data-пакеты до N; `-d10` — типовой для игр/voice.
- `--debug=@file` — дорогой, но рабочий; `--debug=1` ломает захват.
- `--wf-tcp-empty` не нужен: SYN+ACK/FIN/RST ловятся автоматически; нужен
  только для чистых ACK/window-экспериментов.
- `--wf-udp-in=443` + hostlist-auto — только эксперимент для входящего QUIC,
  по умолчанию не включать.

### `--payload`

Без payload lua-desync не знает, что искать:

| Поток | payload |
|---|---|
| TLS ClientHello | `tls_client_hello` |
| HTTP | `http_req` |
| QUIC | `quic_initial` |
| Discord voice discovery | `discord_ip_discovery` |
| unknown UDP / игры | `:payload=all` |

Lua `fake` по умолчанию трогает только known-payload. Для игрового
unknown-UDP **обязателен `:payload=all`**, иначе правило холостое.

### Повторы, fake и split

- `repeats` — объём/доля фейков, не «красота» пакета. DPI классифицирует
  сессию по доминирующему SNI; исторический порог на проверенной сети:
  Discord ≥7-8, YouTube 6, General TCP 8, QUIC обычно без повторов.
- Не увеличивать repeats «на всякий случай»: растёт трафик и риск аномалии.
- `nodrop` отправляет оригинал; на SNI-блоках оригинал идёт за фейком и
  ломает цель. Discord-блоки переведены в drop-режим.
- `fake` обычно использует `tcp_ts=-1000`: сервер отбрасывает фейк по PAWS,
  DPI видит его раньше настоящего hello.
- `tcp_ts` на `multisplit` запрещён: сплит-части умирают по PAWS.
- `pos` в Lua — **zero-based**: `pos=1` = разрыв после первого байта.
- `seqovl`/`seqovl_pattern` заполняют окно; `seqovl_pattern` берёт N байт
  от начала блоба, короткий блоб повторяется. Слишком большой блоб (>MSS)
  даёт лишний сегмент и падение доли фейков.
- `tls_mod=rnd,dupsid` — случайный вид + session id из реального hello;
  встроено в `default-alt` для Discord.
- `ip_id=zero`, `tcp_md5`, `rndsni`, `oob`, `repeater` — кандидаты;
  на проверенной сети повторяемость и объём важнее экзотики.
- Имя блоба **не начинать с цифры** (`2gis_tls` молча не отправляется;
  `g2_tls` работает).
- Блоб должен быть валидным ClientHello с SNI; JA3/шифры/GREASE на обход
  почти не влияют. SNI-first — желательное правило для других сетей; на
  проверенной сети не критично.
- `udplen`/`badsum`/`pktmod` на голосовых UDP-потоках исторически ломали
  обмен; применять только точечно и с откатом.

### Lua-файлы и аргументы

- Используются: `zapret-lib.lua`, `zapret-antidpi.lua`, `zapret-auto.lua`,
  `zapret-custom.lua`. Пресеты ссылаются через `--lua-init`.
- `zapret-obfs.lua` (wgobfs/ippxor) требует zapret на обоих концах и свой
  сервер — не наш сценарий.
- `zapret-pcap.lua` — dev-дамп: `--writable=<dir>` +
  `--lua-init=@lua/zapret-pcap.lua` + `--lua-desync=pcap:file=x.pcap`;
  полезен для разбора новых стратегий, в GUI не включать.
- `zapret-tests.lua` — самотесты lua при обновлении апстрима.
- `--blob name:@path` объявляет блоб; `blob=name` в lua ссылается на него;
  голый `--blob name` без спецификации — ошибка.
- Аргументы конфигурации: `--lua-gc`, `--comment` (в conf допустим),
  `--chdir` (кавычить путь с пробелами). Проверка — `validate_args` +
  `validate_lua` (`--intercept=0`).

### Тогглы

- **GameFilter**:
  - `off` — ничего;
  - `tcp` — `--filter-tcp=1024-65535 --filter-l7=tls` + fake, repeats 6;
  - `udp` — `--wf-udp-out=1024-65535`, `--filter-udp=1024-65535`,
    fake `quic_google` repeats 10, `payload=all`;
  - `both` — TCP+UDP.
  - Решение пользователя: `udp/both` имеет приоритет и **заменяет** game UDP
    rules; правила с портами <1024 при этом не применяются.
- **Discord Voice**: UDP `19294-19344,50000-50100`, `filter-l7=discord,stun`,
  `payload=discord_ip_discovery`, `out-range -d10`, fake/blobs; режим
  `udplen` — запасной (`increment=5:pattern=0xDEADBEEF`).
  Голосовой media часто `l7=unknown` — обычный voice-профиль его не матчит.
- **Auto hostlist**: `--hostlist-auto=<path>` в General/QUIC; файл
  `lists/zapret-auto.txt`. Работает только там, где есть hostname (QUIC);
  для UDP/игр/voice обычно неприменим.
- **ipset_catchall**: заменяет `--hostlist=list-general` на
  `--ipset=ipset-all.txt.gz` + `--ipset-exclude=ipset-exclude.txt`;
  include-hostlist удаляется (winws2 AND-ит ipset и hostlist). Dry-run при
  живом winws2 может дать «1 profile/already running» — это не поломка.
- **fake_blob**: меняет блоб fake, но не должен ломать payload/repeats.
- Изменение аргументов/тогглов требует restart/reinstall; правки списков
  применяются к новым подключениям без перезапуска (hot-reload по mtime).

## 3. Пресеты

11 release:

| Пресет | Назначение |
|---|---|
| `default` | база, 7 блоков: Discord Voice/Media/TLS, Google TLS, General TCP, QUIC Google/General |
| `default-alt` | default + Discord fake с `tls_mod=rnd,dupsid` |
| `auto` | default + `circular` (ротация после 3 сбоев; 60 с — окно счётчика, `--lua-gc=60` — GC) |
| `fake-only` | только fake Google TLS, диагностика/сети с простым DPI |
| `fakedsplit` | fake + fakedsplit |
| `fake-disorder` | fake + disorder (custom lua) |
| `fake-multidisorder` | fake + multidisorder |
| `hostfakesplit` | hostname fake + split |
| `multisplit-pure` | чистый multisplit |
| `multisplit-seqovl` | multisplit + seqovl |
| `tcpmd5-fake` | fake + tcp_md5; кандидат для сетей с фингерпринтом |

- `presets/flaky.txt` — untracked тестовый пресет (4190-4195, ACTIVE_GAME_UDP,
  repeats=12, `-d4`), не релиз.
- `blobs/ACTIVE_DISCORD_UDP.bin`, `ACTIVE_GAME_UDP.bin`, `stun2.bin` —
  записанные payload'ы для `payload=all` (voice/игры); `quic_google` —
  штатный QUIC-блоб. Новые TLS-блобы — `tools/make_blob.py`, размер и
  SNI-first проверять `tools/tls_blob_report.py`.
- Release-пресеты не содержат комментариев; тестовые `exp-*`/`cand-*` в
  релиз не входят.
- Сборка/проверка аргументов: `tools/args_golden.py compare`,
  `tools/check_arg_file.py`, `core.launcher.validate_args` (dry-run +
  `--intercept=0` для Lua).

Исторические ориентиры (одна проверенная сеть; не переносить на другие):

| Вариант | Результат/вывод |
|---|---|
| `default` | 84-100% в разных окнах; база, не гарантия |
| `auto` | 92.3%, фолбэк; на чистом окне выигрыша нет |
| `fake-only` | 90% / 67% на двух разных сетях |
| `hostfakesplit` | 47%, для проверенной сети слаб |
| `tcpmd5-fake` | 100% в чистом окне; кандидат для фингерпринта |
| multidisorder | 69.2%, хуже default на SNI-блоках |
| oob/syndata | 30-46%, не релиз, кандидаты для других сетей |

Проигравшие кандидаты не удалять: они могут выиграть на другой сети/прошивке.

## 4. Пути, данные и служба

| Путь | Роль |
|---|---|
| `zapret2_config.json` | user-конфиг; битый JSON откладывается в `.bad` |
| `games.json` | user-игры/домены/UDP; битый JSON — quarantine, не затирать |
| `VERSION` | версия для update-check |
| `data_version.txt` | маркер копирования onefile-данных |
| `lists/*-user.txt` | user-списки; не перезаписывать |
| `presets/custom.txt` | user-пресет |
| `logs/run.conf` | аргументы ручного/тестерного запуска |
| `logs/service_run.conf` | аргументы службы; binPath ссылается через `@` |
| `logs/zapret2.log` | операционный лог, секции service/launch/games/layout/test |
| `logs/winws2_last_stderr.log` | stdout/stderr движка |
| `logs/binpath_legacy_backup.txt` | старый binPath при миграции службы |

- Служба: имя `zapret2`; создание/изменение/удаление — Win32 API
  (`CreateServiceW`/`ChangeServiceConfigW`/`DeleteService`), чтение
  ImagePath — из реестра (не `sc qc` на длинных путях). Старые Win10/SCM
  могут искажать binPath; обязательна verify/rollback.
- `Start=4` и `DeleteFlag=1` у службы WinDivert — норма (драйвер грузится
  напрямую). Реален только мёртвый ImagePath; лечить repair, не удалением.
- Если winws2 убит, первый `sc start` может дать 1053 — повторять.
- Остановка/удаление: сначала остановить обход, затем ждать выхода winws2,
  затем delete с ретраями (marked-for-deletion/1072).
- `winws2` искать/убивать по своему пути, не по имени: `ZapretController`
  фильтрует PID по binPath; service_manager — path-фильтр. Иначе вторая
  копия/тест убьёт чужой сервис.
- Служба из другой папки не трогается (ownership mismatch); ошибки
  установки откатывают старый `service_run.conf`/binPath.
- Onefile self-heal: системные `key_files` сверяются по sha256 с `_MEIPASS`;
  user-файлы не трогаются никогда. `app_root()` для frozen — каталог exe,
  не `__file__`: старый баг писал в binPath `%TEMP%\_MEI...`, после
  перезапуска служба оставалась с мёртвым путём.
- Отпечаток update-PUBKEY: `50DCECF29451`; приватный ключ — офлайн, вне
  репо. Обновление: подпись → validate_release → sha256 → apply/rollback.
- Конфиг `AppConfig`: `root_dir`, `last_profile`, `zapret1_dir`,
  `zapret1_last_strategy`, `game_filter_mode`, `discord_voice`,
  `discord_voice_mode`, `winws2_debug`, `autohostlist`, `ipset_catchall`,
  `discord_alt`, `fake_blob`, `tour_done`, `notice_done`. Сохранять только
  присланные ключи, валидировать типы, не мутировать shared cache до
  успешной записи.
- Встроенные игры: Wardogs (UDP 4192-4194; домены авторизации/лобби),
  Valorant (домены; UDP-правило пока нет), Fortnite (домены; UDP-правило
  пока нет), WARP stabilizer (по умолчанию off; fake на старте UDP-коннектов
  WARP). Custom-игры — лимиты 20 игр/50 доменов/10 портов/64 CIDR на игру.

### Тестер и диагностика (historical)

- `network_rate` считается без пингов и QUIC-класса; результаты привязаны к
  профилю, а не к «красивости» отдельного пакета.
- Перед прогоном — naked-базлайн; `collect_sanity_info` (dry-run + coverage);
  `engine_broken` при 0-1 профиле. `WinError 740` — не поломка.
- Порядок вердикта важен: `engine_broken` → misses → same_as_naked → ok →
  partial → no_bypass. `same_as_naked` симметричен — не добавлять фильтры.
- QUIC quirks — нейтральный статус, не fail; `H3_NONE` не красный.
- `rated`/`control` разделены; control/ALIAS не должны завышать network_rate.
- Recheck спорных: только домены, провалившиеся под лучшей стратегией;
  это задумано, не «повторный прогон всего».
- SYN/IP-блок: fake/split не лечат. Сначала canary/входящие/pktmon, потом
  вывод; «живой сервис упал на стороне» тоже возможно.
- После naked-теста защита должна восстановиться (service-aware), иначе
  пользователь остаётся без обхода.

## 5. Проверенные выводы и закрытые направления

Historical; перед новым выводом проверять текущий код и сеть.

- **SNI/повторы**: рабочий Discord-блок = fake + multisplit с repeats ≥7-8;
  доля google-фейков ≥90% перед реальным hello. Повторы разных/одинаковых
  фейков важны объёмом, не уникальностью. Блоб и позиция SNI на проверенной
  сети вторичны; огромные блобы снижают долю.
- **AWS**: `amazonaws.com` в list-general ломал DynamoDB/S3; удалён. S3 жив
  в голую на проверенной сети. Возвращать только точечно.
- **Discord uploads**: идут на GCS-домен, TCP-fallback нет; домен должен быть
  в списке. **Discord media/stream**: fake может ломать; чистый multisplit
  (auto strategy=3) — кандидат, но z2 default/auto не подтверждены как
  стабильные; z1 Alt1/Alt2 держат на проблемной сети.
- **Voice 50000+**: входящие окнами режет внешний путь; fake/udplen/badsum
  клиентски не лечат. Рабочее — другой регион/CF-эндпоинт, WARP, переезд
  сервера. Не пинить голосовые hosts: номера ротируются. Мониторинг:
  Discord-лог `%APPDATA%\discord\logs\discord-webrtc*` (включить подробный
  лог в клиенте), старые `voice_flap_*` — в git-истории; pktmon при
  замерах может сам добавлять дропы, поэтому короткие окна/статические
  фильтры.
- **Game UDP**: рабочий рецепт Wardogs — fake `quic_google` ×10 + drop,
  `payload=all`, cutoff 4; блок обычно только на старте коннекта. WARP
  подтверждал UDP-блок. Valorant/Fortnite UDP-правила ещё не подобраны.
  Диагностика: GUI «Анализ приложения» или старый `game_probe`; UDP-серверы
  видны только через захват (pktmon/`pydivert_sniff.py`).
- **ipset catchall**: чинит stateful-DPI (AWS/Akamai/CF/Oracle), но ломает
  DO/Hetzner/OVH/Vultr/BuyVM; поэтому opt-in. CDN A/B обязателен.
- **WARP**: MASQUE/H3, UDP-порты 443/500/1701/4443/4500/8095/8443; падение
  WARP — часто оконная деградация UDP-пути, не общий канал. `GameFilter=udp`
  шлёт fake в туннель; не включать без понимания. Встроенная игра WARP
  stabilizer проверена без вреда, по умолчанию off. Мониторинг:
  `warp-cli status/stats`, логи `%ProgramData%\Cloudflare\`
  (`cfwarp_service_connection_stats.txt` / `cfwarp_service_log.txt`);
  признак — sent растёт, recvd стоит, pto_count растёт.
- **DNS/DoH**: YouTube «нет интернета» при живых других сайтах — часто
  браузерный DoH отдал мёртвый кэш-сервер; менять DoH внутри браузера.
  DoT 853 может быть закрыт, DoH 443 жив. `nslookup` не видит hosts —
  проверять системный resolver.
- **SNI-троттлинг**: 200 + обрыв тела на большом ответе, малый сжатый ответ
  проходит, контроль CDN с другим SNI чист → троттл по SNI; добавлять домен
  в списки, hosts-пин не поможет.
- **Реестр РКН**: игры почти не представлены; нельзя массово вливать
  Fastly/CDN-записи. Telegram MTProto через сторонний WS-прокси — SKIP;
  веб-клиент прокси не поддерживает; IP-пины не лечат.
- **AI/геоблок**: OpenAI/Anthropic и др. не РКН, а гео-блок; нужен не-RU
  выход (WARP/релей), прямые пины бесполезны. Не гонять пачками.
- **GitHub**: исторически был IP-блок Fastly-подсети; hosts-пин —
  временное лечение, desync бессилен. Массовые пины не раздавать.
- **Закрыто/не переоткрывать без нового факта**: Amazonaws в списке;
  широкий ipset; голосовые hosts-пины; Telegram-прокси; «Починить GitHub»
  кнопка; Minecraft-пиннинг; блоб-ротация; Fixed WebView2 в основном архиве.

## 6. Инструменты: что осталось, что удалено

Сейчас в `tools/`:
`ab_candidate.py` (A/B с восстановлением службы/WARP), `pkt_verify.py`
(полигон параметров), `pkt_discord.py`, `pkt_s3.py`, `pkt_both.py`,
`quic_probe.py` (forced H3), `upload_probe.py` (ТСПУ-яма), `tls_ver_probe.py`,
`tls_blob_report.py`, `pydivert_sniff.py`, `make_blob.py`, `args_golden.py`,
`check_arg_file.py`, `status_contract.py`, `api_smoke.py`,
`js_bundle_check.py`, `release_publish.py`, `security/*`.

Быстрые команды:

```powershell
python tools\ab_candidate.py <preset>        # A/B, сам вернёт службу/WARP
python tools\pkt_verify.py --url https://www.youtube.com/ --label default
python tools\quic_probe.py --repeat 3 host   # нужен niquests[http3]
python tools\upload_probe.py --ladder URL
python tools\tls_ver_probe.py --repeat 3 host
python tools\tls_blob_report.py              # отпечатки фейков
python tools\pydivert_sniff.py --proc <name> --seconds 60  # dev/pydivert
python tools\args_golden.py compare
python tools\check_arg_file.py --quoting
```

Удалены при чистке, но остаются в git-истории (`0bd6626^`):

| Инструмент | Назначение |
|---|---|
| `_game_udp.py` | варианты UDP-обхода игры (udplen/fake/ipset; останавливает службу) |
| `game_probe.ps1/.bat` | фоновой лог TCP/UDP/DNS процесса игры |
| `ipset_diff_v3nilla.py` | честный coverage-diff адресами |
| `ipset_candidates.py` | отбор кандидатов из `theirs_only` |
| `ipset_merge_staged.py` | staged-слияние без замены релиза |
| `_rkn_relevant.py` | фильтр реестра по нашим семействам |
| `_rulist_diff.py` | diff реестра и ipset с риском для CDN |
| `voice_flap_monitor.py`, `voice_flap_watch.py`, `discord_webrtc_report.py` | мониторинг/сводка Discord RTC |
| `voice_cand.py` | запуск кандидата voice (опасно: останавливает службу) |
| `_measure_cold.py`, `_measure_wake.py` | старые замеры старта |
| `net_reset.ps1/.bat` | сброс сети/прокси/firewall — опасный, только осознанно |

Восстановить один файл для чтения/копии:
```powershell
git -C C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI `
  show 0bd6626^:tools/_game_udp.py
```
Запускать старые скрипты только после просмотра: в них могут быть hardcoded
пути, `taskkill` по имени и остановка службы. Для ipset-пайплайна:
`ipset_diff_v3nilla.py --refresh` → `ipset_candidates.py` →
`ipset_merge_staged.py`; для реестра — `_rkn_relevant.py [--resolve]` /
`_rulist_diff.py`.

## 7. Архив: что где лежало

| Файл | Что содержит |
|---|---|
| `archive/AGENTS.md` | старый полный снапшот правил/хронологии; много уже в AGENTS |
| `archive/ARCH_AUDIT_2026-10-14.md` | архитектурный аудит, anti-list, порядок рефактора |
| `archive/ASN_SCAN_NOTES.md` | методология ASN-скана, dpi-detector, SNI-пробы |
| `archive/EXTERNAL_NOTES.md` | tspu-docs/b4, механики ТСПУ и RST/TTL |
| `archive/HANDOFF_2026-10-05.md` | старые коммиты, проверки, not-bugs, рабочие пути |
| `archive/IPSETS_V3NILLA.md` | источник ipset, диффы, правила staged-слияния |
| `archive/ISP_NOTES.md` | старые ISP-наблюдения и каталог пресетов (есть чувствительное) |
| `archive/PLAN_0.9.md` | закрытые задачи 0.9, реестр РКН, Telegram, решения |
| `archive/REVIEW_MAP.md` | карта для ревьюера, горячие зоны |
| `archive/REVIEW_REPORT_2026-10-13.md` | внешний отчёт P1-P3, niquests-сборка |
| `archive/REVIEW_VERDICT.md` | «не баги», подтверждённые баги, кандидаты |
| `archive/STRATEGY_TRIALS.md` | батареи, пороги repeats, блобы, CDN/ipset, WARP |
| `archive/TESTER_AUDIT.md` | старый аудит тестера 0.1 (историческое) |
| `archive/VOICE_FLAP_FINLAND_2026-10.md` | полное расследование голоса/стрима |
| `archive/WARP_NOTES_2026-10.md` | паттерн WARP, мониторинг, пересечения |

Команда чтения:
```powershell
git -C C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI `
  show 0bd6626^:AI_DOCS/archive/STRATEGY_TRIALS.md
```
В них есть чувствительные детали; не копировать в новые коммиты.

## 8. Что не трогать

- Vendor `lua/*` (кроме `zapret-custom.lua`), `bin/*`, `windivert/*`,
  `blobs/*` — бинарники/апстрим; обновление только с источником и проверкой.
- `tools/*` — standalone dev-инструменты со своим CLI; не переносить их
  внутренние curl/tasklist-обёртки в product-код.
- `Windows build/*.zip`, `release.json(.sig)`, `hosts.txt` — release/data
  artifacts; hosts не парсить и не генерировать из кода.
- User-файлы (`lists/*-user.txt`, `presets/custom.txt`, `games.json`,
  `zapret2_config.json`, `logs/`) — не перезаписывать.
- `lists/ipset-exclude.txt` — системный; пользовательский —
  `ipset-exclude-user.txt`.
- Не ослаблять Ed25519 fail-closed и не откатывать обновления на «скачайте
  вручную»; не менять значения wire-статусов без синхронного фронта.
- Исторические «не баги» (проверять код перед выводами): `same_as_naked`
  симметричен; contested recheck намеренный; splice в full_analyzer;
  при 100% нет ложного no_bypass; `MainPage.bind` самолечится; блок-тайпы
  диагностики смотрят только `fail`.
- Старые raw-доки могут содержать чувствительные IP/провайдеров; не
  копировать, не цитировать в коммитах/релизах.

## 9. Проверки

Минимальная батарея перед сдачей:
```powershell
python -m compileall -q core server tools main.py
python tools/api_smoke.py
python tools/security/test_updates_security.py
python tools/args_golden.py compare
python tools/js_bundle_check.py
python tools/status_contract.py
```
Локально дополнительно: T36/T39/T40/T41/T43/T45/T46/T47/T48/T49 в
`%TEMP%\opencode` (не входят в репо).

Сборка/релиз — `AI_DOCS/RELEASE_CHECKLIST.md`: `build.py` (PyInstaller spec,
фильтры корневых дублей cygwin/WinDivert), `build_portable.py` (Python
3.13.14 embeddable, `._pth`, pythonnet/pywebview), `build_lite.py` (батники,
без Python). `requirements.txt` должен включать `niquests[http3]`; без него
spec падает fail-loud. `VERSION` в корне и `core/config.py` держать
синхронно; 0.10 immutable, следующие ассеты — только pretty-имена.
Исторически spec уменьшил exe до ~13.7 МБ / zip ~13.5 МБ за счёт удаления
корневых дублей cygwin/WinDivert и лишних pythonnet-файлов.
