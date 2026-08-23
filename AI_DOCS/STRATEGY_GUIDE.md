# Strategy Guide — как искать и тестировать обход DPI
>
> **Обновлено: 2026-07-29 (Pre-release 0.1)**

---

> **⚠️ `default.txt` — универсальная стратегия. Работает у всех протестированных провайдеров.**
> **Размер EXE:** 18.0 MB (было 43.9 MB)

## 0. `--payload` — обязателен, без него ничего не работает

`--payload` говорит lua-desync *где в потоке* искать данные. Без → 000.

**Всегда указывать:**
- `--payload tls_client_hello` для TLS
- `--payload http_req` для HTTP
- `--payload quic_initial` для QUIC
- `--payload discord_ip_discovery` для Discord voice

## 0a. `repeats=N` — не ставить везде

- `nodrop` + `repeats=1` — достаточно
- QUIC: `repeats=6-11`
- **НЕ увеличивать «на всякий случай»**

## 0b. Debug режим

- `--debug=@debug_winws2.log` — каждый пакет, пинг +50-150ms, CPU +15-30%
- `--debug=1` — ломает захват пакетов → 000
- Только для диагностики

---

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

--comment=Discord Voice                   # UDP voice fix (19294-19344,50000-50100)
--comment=Discord Media TCP               # TCP 2053,2083,2087,2096,8443
--comment=Discord TCP tls                 # TCP 443 + hostlist discord
--comment=Google TCP tls                  # TCP 443 + hostlist google
--comment=General TCP                     # TCP 80,443 + hostlist general
--comment=QUIC Google                     # UDP 443 + hostlist google
--comment=QUIC General                    # UDP 443 + hostlist general
```

**Проверено на:** Новороссийск (Новый Интернет), Ижевск (Марк-ИТТ), Воронеж (JustLan), СПб (Т2)

---

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
-4              # только IPv4
-s              # silent
-m 8            # таймаут 8 секунд
-H "User-Agent: ..." # реалистичный браузерный UA
-o NUL          # вывод тела в никуда
-w "%{http_code}"  # только HTTP код
```

---

## Справочник параметров winws2

### Базовые
```
--wf-tcp-out PORT,...    # перехват TCP портов
--wf-udp-out PORT,...    # перехват UDP портов
--lua-init @file.lua     # загрузка Lua
```

### Блобы
```
--blob NAME:@path/file.bin   # из файла
```

### Профили
```
--new              # начало нового профиля
--filter-tcp PORT  # TCP порты
--filter-udp PORT  # UDP порты
--filter-l7 PROTO  # L7 протокол
--hostlist=file    # include: только эти домены
--hostlist-exclude # exclude: все кроме этих
--out-range=-dN    # N байт исходящих обрабатывать
--payload=TYPE     # тип данных
```

### Lua-desync функции
```
fake              # подмена пакета фейковым
multisplit        # разрыв на части с перекрытием
multidisorder     # разрыв + перестановка
fakedsplit        # фейк + разрыв
```

### Параметры lua-desync
```
blob=NAME         # блоб для подмены
tcp_ts=N          # +/- к timestamp
pos=N             # позиция разрыва
pos=midsld        # разрыв в середине SNI
seqovl=N          # перекрытие последовательности
nodrop            # не дропать оригинал
repeats=N         # кол-во повторов
```

---

## OLD_LOGS — исторические стратегии (Zapret 1)

Ранее считалось, что каждый провайдер требует своей стратегии. `default.txt` опроверг это.

| ISP | Стратегия Zapret 1 | Особенность |
|-----|-------------------|-------------|
| Ростелеком (Балаково) | `fake,fakedsplit` + pattern `0x00` | fakedsplit с нулевым паттерном |
| JustLan (Воронеж) | `hostfakesplit` + `ozon.ru` SNI spoofing | SNI spoofing |
| Марк-ИТТ (Ижевск) | `fake` + несколько блобов | YouTube blocked |
| СПб (Т2) | `fake` + несколько блобов | YouTube blocked |

**Сейчас `default.txt` работает у всех — универсальная стратегия найдена.**

---

## Что НЕ сработало (но может работать у других)

| Стратегия | Причина |
|-----------|--------|
| `fake` один, без tcp_ts | Fooling обязателен |
| `fake + multisplit` вместе | Слишком агрессивно (для некоторых DPI) |
| C hostlist=include | Домен не в списке |
| Без `--payload` | Payload не матчится |
| Без `--out-range -d10` | Без ограничения диапазона |

---

## Файлы, необходимые для работы

```
bin/winws2.exe                          # v1.0.2
lua/zapret-lib.lua                      # основная библиотека
lua/zapret-antidpi.lua                  # anti-DPI функции
blobs/tls_clienthello_www_google_com.bin # TLS ClientHello Google
blobs/quic_initial_www_google_com.bin   # QUIC Initial Google
lists/list-general.txt                  # общий список доменов
lists/list-google.txt                   # Google-специфичный список
lists/list-discord.txt                  # Discord-специфичный список
lists/list-exclude.txt                  # домены-исключения
```
