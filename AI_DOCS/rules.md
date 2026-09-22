# Zapret2 GUI — Правила и накопленный опыт

> **Обновлено 2026-09-13 (Pre-Release 0.7.1). Читать перед любыми изменениями.**
> Свежие правила и снапшот — AGENTS.md; методика тестирования — STRATEGY_GUIDE;
> детали экспериментов — STRATEGY_TRIALS. Этот файл — базовые принципы движка и кода.

> **⚠️ `default.txt` — универсальная стратегия (все протестированные провайдеры).**
> **`--payload` — имба, без него стратегии НЕ РАБОТАЮТ.**
> **Debug — грузит CPU + пинг, только диагностика.**

## 0. `default.txt` — универсальная стратегия ✅

Работает у всех протестированных DPI (Новороссийск, Ижевск, Воронеж, СПб Т2/Skynet) —
ранее считалось, что каждый провайдер требует своей стратегии, опровергнуто.
7 блоков: Discord Voice, Discord Media TCP, Discord TCP tls, Google TCP tls,
General TCP, QUIC Google, QUIC General.

## 1. Ключевые находки

- **`--payload` обязателен** — без него multisplit не знает где SNI (split по
  случайному смещению → 000), fake не знает что заменять (мимо цели → 000).
- **`repeats=N`** — Т2: Discord 8 минимум; YouTube 6; General TCP 8; QUIC без
  repeats. Не увеличивать «на всякий случай» (подробности — AGENTS §4).
- **Debug**: `--debug=@log` — +50-150ms/CPU +15-30%; `--debug=1` — 000.

## 2. Как работает Zapret2 (winws2.exe + lua-desync)

```
winws2.exe (v1.0.5)
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

## 3. Как мы ошибались (хронология)

1. **aiohttp вместо curl** — IPv6 happy-eyeballs → false TIMEOUT. Только `curl.exe -4`.
2. **hostlist-ы фильтруют трафик** — стратегия не применяется вне include-списка.
3. **fooling ломает lua-desync** — tcp_ts требует существующий timestamp;
   ip_autottl может сломать маршрутизацию.
4. **fake обязателен для этого DPI (опровергнуто)** — multisplit без fake работает;
   default использует оба.
5. **Кастомные Lua — несовместимость версий** — GitHub-пресеты под v0.9.x,
   наш v1.0.5 имеет изменения API.
6. **WinDivert cleanup без задержки** — `WINDIVERT_CLEANUP_DELAY = 0.5s` — НЕ МЕНЯТЬ.
7. **разные DPI = разные стратегии (опровергнуто ✅)** — default универсален.

## 4. Правила тестирования

- **ТОЛЬКО `curl.exe`** (НЕ aiohttp); флаги `-4 -s -m 8` + реалистичный UA.
- **Canary:** `www.google.com` — должен быть 200 всегда.
- Тест-домены: discord.com, www.youtube.com, www.google.com, gateway.discord.gg,
  cdn.discordapp.com, i.ytimg.com, redirector.googlevideo.com, www.gstatic.com,
  www.cloudflare.com, cdnjs.cloudflare.com.
- Контроль (не влияет на счёт): google/gstatic/cloudflare + РФ (vk.ru, ya.ru,
  gosuslugi.ru). Заведомо-мёртвые (telegram/x/fb/inst/linkedin/whatsapp/fcm/apple —
  глубокий IP-блок) УБРАНЫ из теста (2026-09-11) — только шум.
- Методология: запустить default → curl 3 домена (discord/youtube/google);
  200/200/200 → стратегия работает.

## 5. Scoring

```
STATE_SCORE: OK=1.0, TIMEOUT=0.0, ERROR=0.0, FAIL=-0.5
SMOKE_THRESHOLD=0.2
HTTP code >= 100 -> OK
```
- TIMEOUT=0.0 (не штрафуем — вина DPI, не профиля).
- Актуальный счёт стратегии = `network_rate` (только сетевые тесты, без пингов,
  без QUIC-класса) — AGENTS снапшот.

## 6. Что НЕ работает (не тратить время)

- Кастомные Lua из GitHub (несовместимы с v1.0.5).
- `hostlist` include без CatchAll (стратегия не применяется вне списка).
- aiohttp (IPv6, ложные TIMEOUT).
- `--debug=1` (ломает захват → 000).
- Короткие 8.3 пути с `@`-префиксом (ломает winws2; см. AGENTS §1).

## 7. Служба Windows

- `build_service_bat(root, exe, args)` → `_zapret_service.bat` (регенерируется
  ПЕРЕД install И start — протухший bat поднимал старую стратегию молча).
- `sc create zapret2` через временный .bat; конфликт с Zapret 1 проверяется.
- `status()` парсит STATE из `sc query` (не tasklist — иначе ложное
  «запущена» при ручном winws2).
- Удаление: taskkill → sc delete.

## 8. Auto Hostlist

Тоггл в UI → автосоздаёт `lists/zapret-auto.txt`; `--hostlist-auto=<путь>`
(без `@`!) инжектится в блоки General TCP и QUIC General; winws2 сам добавляет
обнаруженные домены и мониторит их.

## 9. Код-стайл

- **НЕТ `time.sleep()` в async-функциях** — `await asyncio.sleep()`.
- Одна функция — одна ответственность; НЕТ повторяющихся колбэков (фабрики);
  НЕТ мёртвых атрибутов; утилиты — в `core/utils.py`; единая точка
  сериализации (`_serialize_result`); `_` префикс для приватных методов.
- **Текстовые файлы — UTF-8 без BOM** (правки только Write/Edit; не через
  PS 5.1 — AGENTS правило 6). Исключения: test.ps1 (utf-8-sig), .bat/.cmd
  (chcp 65001 + UTF-8 без BOM + CRLF, либо ASCII).
- **Всё, что вызывает tasklist/sc/curl — `encoding="oem", errors="replace"`**
  (CP866 на русской Windows крашил UnicodeDecodeError-ом).
- **Пользовательские тексты (README, UI, описания релизов) — от первого лица
  («я»)**: проект ведёт один автор, «мы» не используем. Комментарии кода и
  техническая документация — безликие.

### Стиль русских текстов (по отзыву друзей, 2026-09-22)

- **Без точки с запятой** в русских текстах и списках: вместо `;` — точка и
  новое предложение (или перестроить фразу). В таблицах и коде — не трогаем.
- **Тире — только обычный дефис** `-` (с пробелами). Длинное тире `—` не
  используем (народ так не пишет).
- **Не путать название программы с числительными**: не «Два Zapret», а
  «два обхода» / «другие обходы» (иначе читается как «Zapret 2»).
- **Ключевое слово-запрет выделять жирным**: в инструкции hosts — именно
  «**никогда** не заменяйте файл целиком».
- Жаргон расшифровывать при первом упоминании (см. истор. пример: «семья» →
  «группа сервисов», «флак» → «нестабильно», «батч» → «сразу все»,
  блоб — «заготовка поддельного пакета»).