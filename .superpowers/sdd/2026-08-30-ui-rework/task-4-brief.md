### Task 4: Тестер — живой вывод блоками по стратегиям

**Files:**
- Modify: `frontend/js/app.js` (`_addResultRowImmediate`, строки 1235-1275; poll-обработчик прогресса, строки 996-1022), `frontend/css/app.css`, `frontend/index.html` (testLiveResults, строки 312-332)

**Interfaces:**
- Consumes: `data.profile` (сервер уже шлёт); `getStatusIcon`, `formatTimeColored`, `getRowClass` — переиспользуются.
- Produces: методы `_liveBlockFor(profile)`, `_setLiveCurrent(profile)`, `_finishLiveProfile(profile, score)`; контейнер `#testLiveBlocks`; классы `.live-block`, `.live-block.active`, `.live-block.done`, `.live-block.expanded`.

- [ ] **Step 1: HTML** — внутри `#testLiveResults` после h3 добавить `<div id="testLiveBlocks"></div>` (таблицу-заглушку убрать или оставить пустой для совместимости).
- [ ] **Step 2: `_addResultRowImmediate` — группировка** — ключ строки: `profile|domain|test_type`; блок на профиль создаётся лениво: заголовок-кнопка (лампа + `profile · ok/n · N%` + стрелка) + tbody строк; `this._liveCurrent` — подсветка активного блока при смене profile.
- [ ] **Step 3: Делегированный обработчик** — клик по заголовку блока → toggle `.expanded` (сворачивание), `aria-expanded` синхронизировать.
- [ ] **Step 4: Прогресс-привязка** — в poll-обработчике: при сообщении «Тестируем стратегию X...» — `_setLiveCurrent(X)`; при «Стратегия X: NN%» — `_finishLiveProfile(X, NN)` (заголовок-скор + класс done → сворачивание, активный снимается).
- [ ] **Step 5: CSS блоков** — `.live-block`: рамка, margin-bottom; `.active`: подсветка (рамка акцентная + лёгкая заливка); `.done`: сворачивание (строки display:none, заголовок остаётся); `.expanded` раскрывает; заголовок-кнопка: полная ширина, hover, focus-visible.
- [ ] **Step 6: Проверка** — `node --check`; прогон теста (2-3 стратегии): блоки отдельные, активная подсвечена, завершённые сворачиваются, клик разворачивает, строки НЕ перемешиваются между стратегиями.
- [ ] **Step 7: Commit** — `git commit -m "feat(tester): live results grouped per strategy — active highlight, done collapse"`

---

### Task 5: Тестер — единый вердикт-итог (доделки)

**Files:**
- Modify: `frontend/js/app.js` (render итога, строки 1540-1610)

**Interfaces:**
- Consumes: `rec.best_profile`, `custom` (уже в final) — готово с прошлых итераций.
- Produces: без дублей: убрать строку «Рекомендуемая стратегия: X» из таблицы (дубль вердикта); custom — компактная строка (источники чипами, без кнопки); заголовок вердикта уже содержит «лучшая: X».

- [ ] **Step 1: Убрать дубль** — в таблице результатов удалить блок `Рекомендуемая стратегия: <strong>...` (строка ~1598).
- [ ] **Step 2: Проверить custom-карточку** — она уже info-only (сделано); при `relation==='equal'` и `best_profile!=='custom'` добавить подпись «совпадает с лучшей — запуск кнопкой выше» (уже есть для isBest; расширить на equal).
- [ ] **Step 3: Проверка** — `node --check`; итог после теста: один вердикт, одна кнопка, custom-строка информативна.
- [ ] **Step 4: Commit** — `git commit -m "feat(tester): single verdict summary — no duplicated recommendation, custom as info line"`

---

### Task 6: Общее — a11y и шрифты

**Files:**
- Modify: `frontend/css/app.css`

**Interfaces:**
- Produces: `:focus-visible` глобально; `prefers-reduced-motion`; системные шрифты (Bahnschrift/Segoe UI Variable/Cascadia Mono fallback) — убрать JetBrains Mono из стека.

- [ ] **Step 1: CSS-правки** — `:focus-visible` на .btn/.toggle/.chip-option/.live-block summary; media `prefers-reduced-motion` (отключить анимации кота/прогресса); font-family: системный стек, JetBrains Mono удалить.
- [ ] **Step 2: Проверка** — `node --check` не нужен (CSS), визуально: фокус виден (Tab), анимации отключаются, шрифт системный.
- [ ] **Step 3: Commit** — `git commit -m "style(a11y): focus-visible, reduced-motion, system fonts"`
