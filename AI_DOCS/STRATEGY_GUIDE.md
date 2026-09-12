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