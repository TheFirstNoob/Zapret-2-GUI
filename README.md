# Zapret 2 GUI

GUI-обёртка для **Zapret 2** (winws2 / lua-desync) — обход DPI/ТСПУ на Windows без VPN.
Основан на версии 1.0.2

> [!IMPORTANT]
> Я не буду исключать что программа делалась с помощью ИИ. Я делюсь своим рабочим результатом который работает у меня и пользователей моего дискорда. Все дальнейшие отзывы уже были по принципу "друг посоветовал" и так далее. Иначе говоря работа программы подтверждена!

> [!WARNING]
>
> ### АНТИВИРУСЫ
> WinDivert может вызвать реакцию антивируса.
> WinDivert - это инструмент для перехвата и фильтрации трафика, необходимый для работы zapret.
> Он может использоваться как хорошими, так и плохими программами, но сам по себе не является вирусом.
>
> **Выдержка из [`readme.md`](https://github.com/bol-van/zapret-win-bundle/blob/master/readme.md#%D0%B0%D0%BD%D1%82%D0%B8%D0%B2%D0%B8%D1%80%D1%83%D1%81%D1%8B) репозитория [bol-van/zapret-win-bundle](https://github.com/bol-van/zapret-win-bundle)*
>
> Некоторые антивирусы склонны относить файлы WinDivert к классам повышенного риска или хакерским инструментам. Происходит удаление файла и помещение его в карантин. При этом детект обязательно имеет название `WinDivert` или `Not-a-virus:RiskTool.Multi.WinDivert`
>
> Добавьте папку с запретом в исключения антивируса, либо отключите детектирование PUA (потенциально нежелательных приложений). Например, в касперском есть галочка "Обнаруживать легальные приложения, которые злоумышленники часто используют для нанесения вреда". При аккуратной и правильной настройке исключений - рекомендуется настроить исключение, но если вы не до конца понимаете что делаете - рекомендуется отключить детект PUA.

---

## Возможности

- 🎯 **Универсальная стратегия `default`** — работает у большинства протестированных провайдеров без ручного подбора
- 🧪 **Тестер DPI** — проверка всех стратегий с подсчётом успеха, тест «голого» соединения и сравнение с Zapret 1
- 🩺 **Диагностика** — одна кнопка: права, путь установки, процесс, служба, конфликты, связь с заблокированными сайтами + отчёт для поддержки в буфер обмена
- 📦 **Служба Windows** — автозапуск обхода после перезагрузки
- ⚙️ **Тогглы**: GameFilter (игровые порты), Discord Voice (UDP), Auto Hostlist, DEBUG-режим
- 📝 **Пользовательские списки** — свои включения/исключения доменов прямо в UI
- 🔀 **Менеджер Zapret 1** — запуск/остановка классических стратегий (ALT и т.п.) из одного окна

## Быстрый старт

1. Скачайте `Zapret2GUI.zip` из [Releases](../../releases) и распакуйте **в путь без кириллицы** (например `C:\Zapret2GUI\`)
2. Запустите `Zapret2GUI.exe`, согласитесь с UAC (нужны права администратора — без них WinDivert не загрузится)
3. Нажмите **▶ Запустить** (стратегия `default`)
4. Если что-то не работает — откройте **Диагностику** и нажмите «Запустить проверку»

**Требования:** Windows 10/11 x64, права администратора.

## Как это работает

```
Zapret2GUI.exe (webview GUI + локальный HTTP-сервер)
        │
        ▼
bin/winws2.exe ── WinDivert (перехват пакетов до стека ОС)
        │              │
        ▼              ▼
lua/zapret-lib.lua + zapret-antidpi.lua   (движок desync)
        │
        ▼
пресеты (presets/*.txt) — 7 блоков фильтров на порты/протоколы/домены:
Discord Voice · Discord Media · Discord TCP · Google TCP · General TCP · QUIC Google · QUIC General
```

Стратегия комбинирует `fake` (поддельный ClientHello с «просевшим» TCP-timestamp — сервер отбрасывает его по PAWS, а DPI видит подделку первым) и `multisplit` (разрыв реального ClientHello с наложением seqovl). Подробнее — в [AI_DOCS/STRATEGY_GUIDE.md](AI_DOCS/STRATEGY_GUIDE.md).

## Стратегии (пресеты)

| Пресет | Подход |
|---|---|
| `default` | **Универсальная** — fake + multisplit, рекомендована |
| `fake-only` | Только fake |
| `fakedsplit` | Fake + fakedsplit |
| `fake-disorder` | Fake + disorder (кастомная lua) |
| `fake-multidisorder` | Fake + multidisorder |
| `hostfakesplit` | Подмена хоста + разрыв |
| `multisplit-pure` / `multisplit-seqovl` | Чистые разрывы |

Смысл каждого параметра — в [AI_DOCS/rules.md](AI_DOCS/rules.md) и справке `bin\winws2.exe --help`.

## Сборка из исходников

```bat
git clone https://github.com/TheFirstNoob/Zapret-2-GUI.git
cd Zapret-2-GUI
pip install -r requirements.txt
python main.py          :: запуск из исходников
pip install pyinstaller
python build.py         :: сборка dist\Zapret2GUI.exe (~18 МБ)
```

## Известные особенности

- **Кириллица в пути** — не запускается без коротких имён 8.3. Держите путь ASCII (`C:\Zapret2GUI\`)
- **Killer NIC** — конфликтует с WinDivert; отключите Bandwidth Control в Killer Control Center
- **Яндекс.Браузер** принудительно подменяет DNS — тестируйте в Firefox/Chrome
- **YouTube по TCP** — в редких сетях браузер идёт через QUIC (работает), а TCP-путь не пробивается; на работу в браузере не влияет
- **Два Zapret одновременно** — нельзя: WinDivert-фильтры конфликтуют. Программа сама следит за этим

## Структура проекта

```
├── main.py               # точка входа (UAC, webview GUI)
├── server/server.py      # локальный HTTP backend
├── core/                 # логика: launcher, tester, diagnostics, служба
├── frontend/             # SPA: HTML/CSS/JS
├── presets/              # стратегии для winws2
├── lua/                  # lua-движок desync
├── blobs/                # бинарные заготовки ClientHello/QUIC
├── lists/                # списки доменов
├── bin/                  # winws2.exe + WinDivert
└── AI_DOCS/              # техническая документация проекта
```

## Благодарности

- [zapret](https://github.com/bol-van/zapret2) — bol-van, оригинальный проект
- Сообществу Windows-порта winws и движка winws2 (lua-desync)
- [WinDivert](https://github.com/basil00/WinDivert) — Graham Cleus
