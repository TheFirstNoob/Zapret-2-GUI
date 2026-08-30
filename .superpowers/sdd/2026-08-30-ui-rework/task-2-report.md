# Task 2 Report — Главная: CSS блоков

**Status:** DONE
**Commit:** `7832076` — `style(main): status line, action panel, conflict inline, Z1 details` (только `frontend/css/app.css`, +17/−3)

## Что сделано

Продолжено поверх CSS Task 1 (2113d14, блок «Main page rework: Обход card»). Правки:

1. **`.main-grid` упрощение** (app.css:208) — `grid-template-columns: 1fr 1fr` → `1fr`. Обе карточки Главной (Обход и Тумблеры) уже занимали всю ширину (`#z2Card`/`.main-card-wide`), двухколоночная сетка осталась мёртвой. Другие страницы `main-grid` не используют (проверено grep по frontend/*.html). `.main-card-wide { grid-column: 1/-1 }` оставлен — безвредный no-op, нужен если сетка вернётся к 2 колонкам.
2. **Лампа-точки** (app.css:277-297):
   - `.status-dot` 8px → 10px + `flex-shrink: 0` (не даёт лампам схлопываться при длинных названиях стратегий в бейдже).
   - Новый `.status-dot-fail` — красный (`var(--err)` + свечение rgba(255,82,82,.3), тот же паттерн, что `--ok-glow` для зелёного). Итог: зелёный/красный/серый — `.status-dot-ok` / `.status-dot-fail` / `.status-dot-off`.
3. **`#z1Card summary` — кнопочный стиль** (app.css:1715-1741): `inline-flex`, padding 4×8 + отрицательный margin (тач-зона), `border-radius`, hover — заливка `var(--surface-hover)` + светлый текст, `transition: var(--transition)`. Маркер скрыт (`list-style:none` + `-webkit-details-marker`), `cursor:pointer` — как требовал бриф.
4. **Уже было от Task 1, не дублировал** (проверено, соответствует брифу): `.status-line` (flex, одна строка с wrap-фолбэком, 15px), `.status-line .status-badge` (15px/600), `.status-line .status-sep`, `.conflict-inline` (красный `--err` на `--err-bg`, padding 8×10, radius), `.action-panel` (flex column, margin/padding-top 14px, `border-top: var(--border)`), `#z2Card { grid-column: 1/-1 }`.

## Ключевые рулинги

- **id-селекторы первичны:** JS перезаписывает `className` у `#z1Card` и `#z2Card` (app.js:315-318, 345-348), стирая `z1-details`/`main-card`-дополнения. Все стили Z1 держатся на `#z1Card`, класс `.z1-details` — лишь алиас в тех же правилах (действует до первого апдейта JS). `#z2Card` стилизован по id с самого начала (Task 1).
- **Лампа:** бриф писал про классы `.dot`/`.ok/.fail/.off`, но JS реально эмитит `status-dot status-dot-ok|off` (app.js:314, 317, 344, 347) и я не трогал JS. Поэтому стилизованы существующие `.status-dot`-классы + добавлен `.status-dot-fail` для красного состояния. Мёртвый CSS под `.dot.ok` не добавлял.
- Палитра не менялась — только существующие переменные (`--err`, `--ok`, `--ok-glow`, `--text-muted`, `--surface-hover`, `--border`, `--radius-sm`, `--transition`). Свечение красной лампы — производное от `--err` в том же стиле, что `--ok-glow`.

## Проверка (по коду — визуально не доступно)

- `git status`/`git diff`: изменён только `frontend/css/app.css` — JS (app.js) не тронут, `frontend2/` не существует в этом репо (Test-Path → False), другие страницы не тронуты.
- Скобки CSS сбалансированы (310/310).
- Селекторы существуют: `.status-line`, `.status-dot`(+ok/fail/off), `.conflict-inline`, `.action-panel`, `.z1-details`/`#z1Card`, `#z2Card`, `.main-grid` — каждый объявлен ровно один раз, конфликтов с прежними правилами (`.card.ok`, `.phase-dot` и т.п.) нет.
- id в HTML на месте: `z2Card` (index.html:78), `conflictInline` (88), `z1Card` (113), `z2StatusBadge`/`z1StatusBadge` (81, 114) — `updateConflict` ходит по `conflictInline`, класс `conflict-inline` стилизует её.
- Визуальная проверка (Step 2 брифа) — пользователем через webview: статус первым, панель действий низом за `border-top`, Z1 раскрывается/сворачивается.

## Сомнения

1. **`.status-dot-fail` пока не эмитится JS** (ни один путь не ставит красную лампу на Главной) — добавлен по брифу «зелёная/красная/серая», но фактически применится, только если будущий код начнёт его использовать. Безвреден (специфичен, переопределяет только фон/свечение).
2. **`.z1-details` алиас** в селекторах summary — класс всё равно стирается JS; оставил для совместимости с будущими правками HTML, но фактически работает только `#z1Card`. Дублирования стилей нет — один и тот же блок правил.
3. Summary при открытом `<details>` не меняет вид (текст «развернуть» статичен) — это контент/JS, вне рамок Task 2; визуально состояние видно по раскрывшемуся содержимому.
4. Визуальный осмотр и webview-прогон невозможны отсюда — по коду всё сходится (см. Проверка).

## Ledger

- progress.md: добавлена запись Task 2.
- Зеркало Desktop: префлайт предписывает синк после каждой задачи — делаю оркестратор/пользователь (у меня нет инструкции на запись в «Zapret 2 GUI\»).