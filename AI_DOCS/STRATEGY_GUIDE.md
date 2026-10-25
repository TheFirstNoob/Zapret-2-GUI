# Strategy Guide — как искать и тестировать обход DPI

> Обновлено 2026-10-24. Основные правила — `AGENTS.md`; источники данных,
> исторические испытания и решение «не переоткрывать» —
> `ENGINEERING_NOTES.md`.

## 0. Ключевые правила

- **`--payload` обязателен:** без него lua-desync не знает, что искать.
  TLS — `tls_client_hello`, HTTP — `http_req`, QUIC — `quic_initial`,
  Discord voice — `discord_ip_discovery`; unknown UDP — `:payload=all`.
- **`repeats`:** Discord 8, YouTube 6, General TCP 8, QUIC без повторов.
  Не увеличивать «на всякий случай».
- **`nodrop` на SNI-блоках ломает цель:** оригинал идёт за фейком, DPI
  видит оба. Discord-блоки — в drop-режиме.
- **`tcp_ts` — только на fake;** на multisplit запрещён (PAWS).
- **Debug:** `--debug=@log` — дорого; `--debug=1` ломает захват.

## default.txt

Базовый пресет для большинства проверенных сетей. Это не гарантия на любом
маршруте: проблемный регион/провайдер может требовать отдельного профиля.

7 блоков:

- Discord Voice (UDP 19294-19344, 50000-50100)
- Discord Media TCP (2053, 2083, 2087, 2096, 8443)
- Discord TCP tls (443)
- Google TCP tls (443)
- General TCP (80, 443)
- QUIC Google (UDP 443)
- QUIC General (UDP 443)

## Как тестировать

```powershell
taskkill /F /IM winws2.exe 2>$null
# запустить профиль через GUI
curl.exe -4 -s -m 8 -H "User-Agent: Mozilla/5.0" -o NUL -w "%{http_code}" https://discord.com/ https://www.youtube.com/ https://www.google.com/
```

- Только `curl.exe`, не aiohttp (IPv6 даёт ложные TIMEOUT).
- `-4 -s -m 8`, реалистичный браузерный UA.
- `www.google.com` — канарейка; Discord/YouTube/Google — основные цели.
- QUIC-класс проверять браузером/отдельной H3-пробой, не TCP-статусом.
- Тестер может быть зелёным при SYN-блоке на конкретный эндпоинт: он
  проверяет не все IP, которые использует клиент.

## Справочник winws2

```
--wf-tcp-out PORT,...      перехват TCP
--wf-udp-out PORT,...      перехват UDP
--lua-init @file.lua       загрузка Lua (только форма =)
--blob NAME:@path          блоб (имя не с цифры)
--new                      новый профиль
--filter-tcp / -udp PORT   фильтр портов
--filter-l7 PROTO          L7-протокол
--hostlist=file            include
--hostlist-exclude         exclude
--out-range=-dN            ограничение исходящих
--payload=TYPE             тип пакета
```

Lua-desync функции: `fake`, `multisplit`, `multidisorder`, `fakedsplit`.
Параметры: `blob`, `tcp_ts` (только fake), `pos` (zero-based), `seqovl`,
`nodrop` (не на SNI), `repeats`.

## Что такое фейк

Фейк — не шифрование и не подпись. Это байты ClientHello, которые движок
подставляет в поток, чтобы ТСПУ увидел доминирующий SNI.

1. `fake:blob=X` отправляет блоб с уменьшенным `tcp_ts`; сервер отбрасывает
   его по PAWS, а DPI без PAWS видит фейк раньше настоящего hello.
2. `multisplit:pos=1:seqovl=681:seqovl_pattern=google_tls` режет настоящий
   hello, сдвигает первую часть по seq и заполняет окно байтами блоба.
3. `repeats` увеличивает долю SNI фейка: DPI классифицирует по
   доминирующему SNI, а не по «красоте» отдельного пакета.

Требования к блобу: валидный ClientHello и SNI внутри. JA3, набор шифров,
GREASE/padding на обход не влияют (в пределах наших замеров). Крупный блоб
даёт лишний сегмент/трафик; `tls_mod=rnd,dupsid` даёт вариативность на
сессию. Проверка: `python tools/tls_blob_report.py`.

## Файлы

```
bin/winws2.exe                          v1.0.6
lua/zapret-lib.lua, zapret-antidpi.lua  база/desync
blobs/*.bin                            фейки
lists/list-general.txt                 общий список
lists/list-google.txt                  Google
lists/list-discord.txt                 Discord
lists/list-exclude.txt                 исключения
```

## Исторические заметки

Сжаты в `ENGINEERING_NOTES.md`; полные исходники — в git-истории
(`0bd6626^:AI_DOCS/archive/`). Текущие правила — выше и в `AGENTS.md`.
