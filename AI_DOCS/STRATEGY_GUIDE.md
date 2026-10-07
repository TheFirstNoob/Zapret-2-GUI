# Strategy Guide — как искать и тестировать обход DPI

> **Обновлено: 2026-09-13 (Pre-Release 0.7.1)**

> **⚠️ `default.txt` — универсальная стратегия. Работает у всех протестированных провайдеров.**
> Детали механик и правил — AGENTS.md; результаты испытаний — STRATEGY_TRIALS.md.

## 0. Ключевые правила (кратко)

- **`--payload` обязателен** — без него lua-desync не знает где искать: 000.
  Всегда: `tls_client_hello` (TLS), `http_req` (HTTP), `quic_initial` (QUIC),
  `discord_ip_discovery` (Discord voice).
- **`repeats=N` — не ставить везде**: Discord на Т2 = 8 минимум (порог плавает,
  8 = запас), YouTube (google-блок) = 6, General TCP = 8, QUIC — без repeats.
  Для прочих сетей не увеличивать «на всякий случай». (2026-09-12: старое
  «nodrop + repeats=1» устарело — на Т2 повтор обязателен даже с nodrop.)
- **`nodrop` на SNI-блоках ломает цель** (2026-09-10, github; тот же класс, что
  youtube 4d16a19): оригинал с реальным SNI идёт следом за фейком → DPI видит
  оба и блочит. Фикс: fake БЕЗ nodrop + repeats, multisplit без nodrop/tcp_ts.
- **Debug**: `--debug=@debug_winws2.log` — пинг +50-150ms, CPU +15-30% (только
  диагностика); `--debug=1` — ломает захват → 000.

## default.txt — универсальная стратегия

**Структура (7 блоков):**
```
--wf-tcp-out 80,443,2053,2083,2087,2096,8443,%GameFilter%
--wf-udp-out 443,19294-19344,50000-50100,%GameFilter%
--lua-init @lua/zapret-lib.lua
--lua-init @lua/zapret-antidpi.lua
--blob google_tls:@blobs/tls_clienthello_www_google_com.bin
--blob quic_google:@blobs/quic_initial_www_google_com.bin
--lua-gc 60
--comment=Discord Voice / Discord Media TCP / Discord TCP tls
--comment=Google TCP tls / General TCP / QUIC Google / QUIC General
```

**Проверено на:** Новороссийск (Новый Интернет), Ижевск (Марк-ИТТ), Воронеж (JustLan), СПб (Т2).

## Как тестировать (проверенная методика)

### Быстрая проверка
```powershell
taskkill /F /IM winws2.exe 2>$null
# запустить профиль через GUI
curl.exe -4 -s -m 8 -H "User-Agent: Mozilla/5.0" -o NUL -w "%{http_code}" https://discord.com/ https://www.youtube.com/ https://www.google.com/
```

### Домены-канарейки
| Домен | Без обхода | С обходом |
|-------|-----------|----------|
| discord.com | 000/таймаут | 200 |
| www.youtube.com | 000/таймаут | 200 |
| www.google.com | 200 | 200 |

Google.com всегда 200 — НЕЛЬЗЯ использовать как канарейку.

### Важные curl-флаги
```
-4              # только IPv4 (aiohttp/IPv6 дают ложные TIMEOUT — только curl)
-s -m 8         # silent, таймаут 8с
-H "User-Agent: ..."  # реалистичный браузерный UA
-o NUL -w "%{http_code}"  # только HTTP код
```

## Справочник параметров winws2

### Базовые
```
--wf-tcp-out PORT,...    # перехват TCP портов
--wf-udp-out PORT,...    # перехват UDP портов
--lua-init @file.lua     # загрузка Lua (только =форма, см. AGENTS §1)
```

### Блобы
```
--blob NAME:@path/file.bin   # из файла; имя НЕ с цифры (AGENTS правило 2)
```

### Профили
```
--new              # начало нового профиля
--filter-tcp PORT  # TCP порты
--filter-udp PORT  # UDP порты
--filter-l7 PROTO  # L7 протокол
--hostlist=file    # include: только эти домены (в профиле объединяются)
--hostlist-exclude # exclude: все кроме этих
--out-range=-dN    # N байт исходящих обрабатывать
--payload=TYPE     # тип данных
```

### Lua-desync функции и параметры
```
fake              # подмена пакета фейковым
multisplit        # разрыв на части с перекрытием
multidisorder     # разрыв + перестановка
fakedsplit        # фейк + разрыв

blob=NAME         # блоб для подмены
tcp_ts=N          # +/- к timestamp (только на fake! PAWS, AGENTS §7)
pos=N             # позиция разрыва (zero-based!); pos=midsld — в середине SNI
seqovl=N          # перекрытие последовательности
nodrop            # не дропать оригинал (не ставить на SNI-блоки!)
repeats=N         # кол-во повторов (см. правила выше)
```

### 0.1. Что такое фейк и что ему действительно нужно

Фейк — это **не шифрование, не ключ и не подпись**. Это обычные байты ClientHello,
которые zapret подставляет в поток вместо первых байтов настоящего приветствия.
Никто их не проверяет на подлинность: ни сервер, ни ТСПУ.

Что происходит на проводе (по коду `lua/zapret-antidpi.lua`):

1. `fake:blob=X` отправляет блоб **дополнительным** пакетом с уменьшенным
   `tcp_ts` (−1000). Сервер отбрасывает его по PAWS (старый TSVal), а ТСПУ без
   PAWS видит фейк **раньше** настоящего ClientHello.
2. `multisplit:pos=1:seqovl=681:seqovl_pattern=google_tls` режет **настоящий**
   ClientHello, уменьшает seq первой части на 681 и заполняет освободившиеся
   681 байт **байтами блоба** (`pattern(pat,1,seqovl)`). Сборщик ТСПУ, который
   склеивает поток по seq, видит на местах 0…680 байты блоба, а не настоящие.
   Отсюда ровно `seqovl=681` — это размер google-блоба.
3. `repeats=N` добивает объём: ТСПУ классифицирует по **доминирующему SNI**
   (доля ≥90% = пропуск, AGENTS §4), поэтому важна не структура пакета, а
   **доля SNI фейка** в том, что видит фильтр.

Отсюда требования к файлу-фейку — ровно два:

- **валидный ClientHello** (record → handshake → длина → расширения): его
  парсят и winws2, и ТСПУ; непарсящийся пакет для фильтра — просто шум;
- **SNI внутри**: блокировка HTTPS идёт по SNI (EXTERNAL_NOTES §1, 17.5.3).
  Без SNI фейк не даёт доминирующего SNI и техника теряет смысл.

Всё остальное — JA3, размер, набор шифров, GREASE, padding, ALPN — на **обход**
не измерено: виндовый дамп `sochi_park` (4 шифра, `0x00ff`, пустой
`ec_point_formats`) пробивает так же, как google (STRATEGY_TRIALS, «Блоб фейка
не влияет»). Вариативность на каждую сессию даёт не файл, а `tls_mod=rnd,dupsid`
— рандомизация или копирование session_id настоящего приветствия.

**Размер при этом не бесплатен по трафику.** `rawsend_dissect_segmented` режет
payload по `mss - extra_len`, поэтому:

- блоб < MSS → 1 сегмент; блоб > MSS (например 1889/1907 Б) → **2 сегмента**;
- при `repeats=8` это ~15 КБ против ~2 КБ на одно приветствие;
- а ТСПУ анализирует именно «размеры пакетов + вариации, частоты, паттерны»
  (tspu-docs 23.1) — то есть это меняет то, на что он смотрит.

На Т2 для блобов <MSS это вышло нейтральным. Для 1889/1907 Б **замеров у нас
нет** — там фейк не проверен ни на одном нашем провайдере, только в чужом треде.

Второе место, где размер обязателен: блоб в `seqovl_pattern`. Берётся ровно
`seqovl` байт от начала, а если блоб короче — `pattern()` **повторяет** его
(`string.rep`), и короткий синтетик превратится в тройное повторение куска.
В приложении подмена фейка `seqovl_pattern` не трогает, так что это не наш путь;
но в презете, где pattern указывает на короткий блоб, вылезет.

Практический вывод: фейк — это **носитель SNI и, иногда, источник байтов для
перекрытия**. Улучшать его «правдоподобие» без замеров смысла нет; улучшать
*SNI-доминирование* (repeats, порядок блоков) — смысл есть. Крупный фейк — это
плата за лишний сегмент и лишний килобайт, а не за обход.

Проверить любой файл: `python tools/tls_blob_report.py` — печатает структуру,
SNI, его позицию, key_share, padding и JA3.

## OLD_LOGS — исторические стратегии (Zapret 1)

Ранее считалось, что каждый провайдер требует своей стратегии. `default.txt` опроверг это.

| ISP | Стратегия Zapret 1 | Особенность |
|-----|-------------------|-------------|
| Ростелеком (Балаково) | `fake,fakedsplit` + pattern `0x00` | fakedsplit с нулевым паттерном |
| JustLan (Воронеж) | `hostfakesplit` + `ozon.ru` SNI spoofing | SNI spoofing |
| Марк-ИТТ (Ижевск) | `fake` + несколько блобов | YouTube blocked |
| СПб (Т2) | `fake` + несколько блобов | YouTube blocked |

**Сейчас `default.txt` работает у всех — универсальная стратегия найдена.**

## Что НЕ сработало (но может работать у других)

| Стратегия | Причина |
|-----------|--------|
| `fake` один, без tcp_ts | Fooling обязателен |
| `fake + multisplit` вместе | Слишком агрессивно (для некоторых DPI) |
| C hostlist=include | Домен не в списке |
| Без `--payload` | Payload не матчится |
| Без `--out-range -d10` | Без ограничения диапазона |

## Файлы, необходимые для работы

```
bin/winws2.exe                          # v1.0.5
lua/zapret-lib.lua                      # основная библиотека
lua/zapret-antidpi.lua                  # anti-DPI функции
blobs/tls_clienthello_www_google_com.bin # TLS ClientHello Google
blobs/quic_initial_www_google_com.bin   # QUIC Initial Google
lists/list-general.txt                  # общий список доменов
lists/list-google.txt                   # Google-специфичный список
lists/list-discord.txt                  # Discord-специфичный список
lists/list-exclude.txt                  # домены-исключения
```