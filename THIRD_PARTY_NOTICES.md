# Сторонние компоненты и лицензии

Zapret 2 GUI — обёртка; ядро обхода — сторонние open-source компоненты.
Собственный код проекта (GUI, backend, сборочные скрипты) — MIT, см. [LICENSE](LICENSE).
Компоненты ниже распространяются под своими лицензиями; их копирайты
принадлежат их авторам.

## zapret2 — движок обхода (winws2, lua-скрипты)

- Источник: https://github.com/bol-van/zapret2
- Лицензия: MIT
- Copyright (c) 2016-2026 bol-van
- Что поставляется в дистрибутивах: `bin/winws2.exe`, `bin/cygwin1.dll`,
  `lua/*.lua`, часть `blobs/*`, список `windivert/`.

Полный текст лицензии:

```
MIT License

Copyright (c) 2016-2026 bol-van

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## WinDivert — драйвер перехвата трафика

- Источник: https://github.com/basil00/WinDivert
- Автор: Graham Cleus (basil00)
- Лицензия: на выбор LGPL v3 или GPL v2 (двойное лицензирование)
- Что поставляется: `bin/WinDivert.dll`, `bin/WinDivert64.sys`

## Flowseal/zapret-discord-youtube — Zapret 1

- Источник: https://github.com/Flowseal/zapret-discord-youtube
- Лицензия: MIT (Copyright (c) 2016-2026 bol-van, 2024-2026 Flowseal)
- Что используется: справочные материалы и данные — структура батников
  (установка/удаление службы), синхронизация `hosts.txt`, пресеты для
  сравнения в тестах, бинарные блобы из `blobs/` — `ACTIVE_DISCORD_UDP.bin`,
  `ACTIVE_GAME_UDP.bin`, `stun2.bin` (образцы UDP-пакетов для fake-режима).
  Спасибо автору.

## Runnin4ik/dpi-detector — данные ASN/DPI-проб

- Источник: https://github.com/Runnin4ik/dpi-detector
- Лицензия: MIT (Copyright (c) 2026 Runnin4ik; полный текст — upstream
  `LICENSE`, https://github.com/Runnin4ik/dpi-detector/blob/main/LICENSE)
- Что используется: `lists/cdn-asn-probes.json` (upstream `tcp16.json`),
  `lists/whitelist-sni.txt` — снимок; sha256 и порядок обновления —
  `AI_DOCS/ENGINEERING_NOTES.md` §1. Идея ASN-скана (IP:443 + 32 КБ)
  реализована самостоятельно в `core/tester.py`.
- Обновление: `python tools/sync_dpi_detector.py [--apply]`.

## hyperion-cs/dpi-checkers — CDN-батарея (данные suite.v2)

- Источник: https://github.com/hyperion-cs/dpi-checkers
- Лицензия: Apache License 2.0
- Что используется: набор хостов `ru/tcp-16-20/suite.v2.json` (36 хостов)
  лёг в `core/tester_defs.py::CDN_HOSTS` (порядок upstream сохранён);
  производные подмножества — `lists/list-cdn-test.txt` (12),
  `lists/list-cdn-fix.txt` (9) и fix-класс-хосты в `lists/list-general.txt`.
- Снимок: `suite.v2.json` sha256 `9c844313a8120e54…f50e7e` (2026-06-16);
  сверка 2026-11-14 = upstream HEAD `bb38d7a` (файл не менялся).

## V3nilla/IPSets-For-Bypass-in-Russia — CIDR-списки

- Источник: https://github.com/V3nilla/IPSets-For-Bypass-in-Russia
- Что используется: источник данных для ipset-списка (обход по подсетям).

## DanielLavrushin/b4 + tspu-docs — материалы по анализу ТСПУ

- Источник: https://github.com/DanielLavrushin/b4
- Лицензия кода: GPL-3.0. Код не копировался — использованы идеи и
  публичные материалы (tspu-docs) для диагностики.

## Python и GUI-зависимости

Поставляются в portable/exe-сборках (версии могут отличаться в зависимости
от момента сборки; актуальные версии фиксируются в `requirements.txt`):

| Компонент | Назначение | Лицензия | Источник |
|---|---|---|---|
| Python 3.13 | runtime portable-сборки | PSF-2.0 | https://www.python.org/ |
| pywebview | GUI-окно WebView2 | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| pythonnet | мост .NET/WebView2 | MIT | https://github.com/pythonnet/pythonnet |
| clr-loader | загрузка CLR | MIT | https://github.com/pythonnet/clr-loader |
| niquests | HTTP/H3-проба | Apache-2.0 | https://github.com/jawah/niquests |
| urllib3-future | HTTP-транспорт niquests | MIT | https://github.com/jawah/urllib3.future |
| qh3 | QUIC/HTTP3 | MIT | https://github.com/jawah/qh3 |
| jh2 | HTTP/2 | MIT | https://github.com/jawah/jh2 |
| wassima | системные сертификаты | MIT | https://github.com/jawah/wassima |
| h11 | HTTP/1.1 | MIT | https://github.com/python-hyper/h11 |
| charset-normalizer | кодировки HTTP | MIT | https://github.com/jawah/charset_normalizer |
| bottle | HTTP-сервер pywebview | MIT | https://github.com/bottlepy/bottle |
| proxy_tools | прокси-утилиты pywebview | MIT | https://github.com/jtushman/proxy_tools |
| typing_extensions | typing backport | PSF-2.0 | https://github.com/python/typing_extensions |
| cffi | CFFI | MIT | https://github.com/python-cffi/cffi |
| pycparser | парсер C | BSD-3-Clause | https://github.com/eliben/pycparser |
| OpenSSL | TLS/криптография runtime | Apache-2.0 | https://www.openssl.org/ |

Полные тексты лицензий доступны в upstream-репозиториях и в метаданных
установленных пакетов. PyInstaller используется только как инструмент сборки;
его собственный код в пользовательский архив не включается.

## Прочее

- Списки доменов и прочие данные — собственные или собранные из открытых
  источников; пользовательские файлы (списки, конфиг) остаются
  собственностью пользователя.
