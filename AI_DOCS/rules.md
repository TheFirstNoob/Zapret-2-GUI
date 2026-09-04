# Zapret2 GUI — Правила и накопленный опыт

> **Актуально для Pre-release 0.1 (2026-07-29). Читать перед любыми изменениями.**
>
> **⚠️ `default.txt` — универсальная стратегия, работает у всех протестированных провайдеров.**
> **`--payload` — имба, без него стратегии НЕ РАБОТАЮТ.**
> **Debug — грузит CPU + пинг, только для диагностики, выключать после.**

---

## 0. `default.txt` — универсальная стратегия ✅

**`default.txt` работает у ВСЕХ протестированных DPI:**
- Новороссийск («Новый Интернет»)
- Ижевск (Марк-ИТТ)
- Воронеж (JustLan)
- СПб (Т2 мобильный / Skynet дома)

Ранее считалось, что разные провайдеры требуют разных стратегий (hostfakesplit для JustLan, fake+multisplit для ТСПУ, fake only для Ростелекома). `default.txt` опроверг это — одна стратегия работает везде.

### Известный изъян
Один маленький — будет описан позднее.

### Структура default.txt
```
--wf-tcp-out 80,443,2053,2083,2087,2096,8443,%GameFilter%
--wf-udp-out 443,19294-19344,50000-50100,%GameFilter%
[Discord Voice] [Discord Media TCP] [Discord TCP tls]
[Google TCP tls] [General TCP] [QUIC Google] [QUIC General]
```

---

## 1. Ключевые находки

### `--payload` обязателен
`--payload` говорит lua-desync где в потоке искать данные. Без него:
- `multisplit` не знает где SNI → split по случайному смещению → 000
- `fake` не знает что заменять → фейк мимо цели → 000

**Всегда указывать:** `tls_client_hello`, `http_req`, `quic_initial`, `discord_ip_discovery`

### `repeats=N` — не ставить везде
- `nodrop` + `repeats=1` — достаточно
- QUIC: `repeats=6-11`
- **НЕ увеличивать «на всякий случай»**

### Debug режим
- `--debug=@debug_winws2.log` — пинг +50-150ms, CPU +15-30%
- `--debug=1` — ломает захват пакетов → 000
- Только для диагностики

---

## 2. Как работает Zapret2 (winws2.exe + lua-desync)

### Архитектура
```
winws2.exe (v1.0.2)
  ↓ WinDivert (драйвер ядра, перехватывает пакеты ДО ОС)
  ↓ Lua-движок (zapret-lib.lua + zapret-antidpi.lua)
  ↓ Профили (--new секции, каждая = отдельный обработчик)
  ↓ lua-desync функции (fake, multisplit, fakedsplit, ...)
```

### Ключевое различие nfqws1 vs lua-desync

| | nfqws1 (Zapret 1) | lua-desync (Zapret 2) |
|---|---|---|
| Комбинирование | `--dpi-desync=fake,multisplit` — один проход | `--lua-desync=fake:... --lua-desync=multisplit:...` — два вызова |
| Fooling | `--dpi-desync-fooling=ts` — глобально | `tcp_ts=N` — локально на функцию |
| Блобы | `--dpi-desync-fake-tls=<путь>` | `blob=<имя>` из `--blob` реестра |

---

## 3. Как мы ошибались (хронология)

### Ошибка 1: aiohttp вместо curl
aiohttp использует IPv6 happy-eyeballs → false TIMEOUT. Решение: `curl.exe -4`

### Ошибка 2: hostlist-ы фильтруют трафик
Стратегия не применяется к доменам вне include-списка. Решение: только hostlist-exclude.

### Ошибка 3: fooling ломает lua-desync
`tcp_ts` требует существующий timestamp. `ip_autottl` может сломать маршрутизацию.

### Ошибка 4: `fake` обязателен для этого DPI (опровергнуто)
Ранее считалось что multisplit без fake не работает. Сейчас default.txt использует оба.

### Ошибка 5: Кастомные Lua — несовместимость версий
GitHub-пресеты писаны под winws2 v0.9.x, наш v1.0.2 имеет изменения API.

### Ошибка 6: WinDivert cleanup без задержки
`WINDIVERT_CLEANUP_DELAY = 0.5s` — НЕ МЕНЯТЬ.

### Ошибка 7: разные DPI = разные стратегии (опровергнуто ✅)
Ранее на основе OLD_LOGS считалось что каждый провайдер требует своей стратегии.
`default.txt` работает у всех — стратегия универсальна.

---

## 4. Правила тестирования

### Инструменты
- **ТОЛЬКО `curl.exe`** для HTTP/TLS тестов. НЕ aiohttp.
- **Флаги curl:** `-4 -s -m 8` + реалистичный `User-Agent`
- **Canary:** `www.google.com` — должен быть 200 всегда

### Домены для теста
```
discord.com, www.youtube.com, www.google.com,
gateway.discord.gg, cdn.discordapp.com, i.ytimg.com,
redirector.googlevideo.com, www.gstatic.com,
www.cloudflare.com, cdnjs.cloudflare.com
```

### Методология
1. Запустить default.txt
2. Проверить curl-ом 3 домена: discord.com, youtube.com, google.com
3. Если 200/200/200 → стратегия работает

---

## 5. Scoring

```
STATE_SCORE: OK=1.0, TIMEOUT=0.0, ERROR=0.0, FAIL=-0.5
SMOKE_THRESHOLD=0.2
HTTP code >= 100 -> OK
```

- TIMEOUT=0.0 (не штрафуем — это вина DPI, не профиля)
- OK=1.0 (ответ пришёл, DPI не сбросил соединение)

---

## 6. Что НЕ работает (не тратить время)

- **Кастомные Lua из GitHub** — несовместимы с v1.0.2
- **`hostlist` include без CatchAll** — стратегия не применяется к доменам вне списка
- **aiohttp** — использует IPv6, даёт ложные TIMEOUT
- **`--debug=1`** — ломает захват пакетов → все 000
- **Короткие 8.3 пути с `@`-префиксом** — ломает winws2

---

## 7. Служба Windows

### Установка
- `build_service_bat(root, exe, args)` → пишет `_zapret_service.bat`
- `sc create zapret2` → создаёт службу
- Проверка конфликта с Zapret 1

### Статус
- `status()` парсит STATE из `sc query zapret2`, а не проверяет tasklist
- Это исключает ложное "служба запущена" когда winws2 запущен вручную

### Удаление
- taskkill → sc delete → готово

---

## 8. Auto Hostlist

- Включается тогглом в UI
- Автосоздаёт `lists/zapret-auto.txt` если файла нет
- `--autohostlist=@path` инжектится в блоки General TCP и QUIC General
- winws2 сам добавляет обнаруженные домены и мониторит их

---

## 9. Код-стайл

- **НЕТ `time.sleep()` в async-функциях.** Использовать `await asyncio.sleep()`.
- **Одна функция — одна ответственность.**
- **НЕТ повторяющихся колбэков.** Фабрики для сериализации.
- **НЕТ мёртвых атрибутов.**
- **Выносить утилиты в `core/utils.py`.**
- **Единая точка сериализации.** Одна функция `_serialize_result`.
- `_` префикс для приватных/внутренних методов.
- **Текстовые файлы — UTF-8 без BOM.** Правки только Write/Edit; не
  перекодировать через PS 5.1 (см. AGENTS правило 6). Единственное
  исключение — `test.ps1` (utf-8-sig для PS 5.1).
- **.bat/.cmd — НЕ UTF-8-стандарт**: cmd читает их в кодовой странице
  консоли. Кириллица: `chcp 65001 >nul` + UTF-8 (без BOM) + CRLF, либо ASCII.
  Никогда LF.
