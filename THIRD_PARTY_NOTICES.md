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
- Что используется: справочные материалы и данные — структура батников
  (установка/удаление службы), синхронизация `hosts.txt`, пресеты для
  сравнения в тестах. Спасибо автору.

## V3nilla/IPSets-For-Bypass-in-Russia — CIDR-списки

- Источник: https://github.com/V3nilla/IPSets-For-Bypass-in-Russia
- Что используется: источник данных для ipset-списка (обход по подсетям).

## DanielLavrushin/b4 + tspu-docs — материалы по анализу ТСПУ

- Источник: https://github.com/DanielLavrushin/b4
- Лицензия кода: GPL-3.0. Код не копировался — использованы идеи и
  публичные материалы (tspu-docs) для диагностики.

## Прочее

- Списки доменов и прочие данные — собственные или собранные из открытых
  источников; пользовательские файлы (списки, конфиг) остаются
  собственностью пользователя.
