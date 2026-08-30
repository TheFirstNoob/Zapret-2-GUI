### Task 3: Тестер — чип-опции вместо чекбоксов

**Files:**
- Modify: `frontend/index.html` (test-options, строки 277-290), `frontend/css/app.css`

**Interfaces:**
- Consumes: id `cdnCheck`, `extendedCheck`, `logCheck` — сохранить (JS читает checked).
- Produces: разметка чипов `<label class="chip-option"><input type="checkbox" id="cdnCheck"><span>...</span></label>`.

- [ ] **Step 1: Заменить разметку опций** на чипы с галочкой ✓ (стиль из frontend2, но в нашей палитре), id чекбоксов те же.
- [ ] **Step 2: CSS чипов** — `.chip-option`: граница, radius, checked-состояние — акцентная заливка, focus-visible.
- [ ] **Step 3: Проверка** — `node --check`; интро тестера: чипы кликабельны, состояние сохраняется (тест реально учитывает).
- [ ] **Step 4: Commit** — `git commit -m "feat(tester): chip options instead of checkboxes"`

---

### Task 4: Тестер — живой вывод блоками по стратегиям

**Files:**
- Modify: `frontend/js/app.js` (`_addResultRowImmediate`, строки 1235-1275; poll-обработчик прогресса, строки 996-1022), `frontend/css/app.css`, `frontend/index.html` (testLiveResults, строки 312-332)

**Interfaces:**
- Consumes: `data.profile` (сервер уже шлёт); `getStatusIcon`, `formatTimeColored`, `getRowClass` — переиспользуются.
- Produces: методы `_liveBlockFor(profile)`, `_setLiveCurrent(profile)`, `_finishLiveProfile(profile, score)`; контейнер `#testLiveBlocks`; классы `.live-block`, `.live-block.active`, `.live-block.done`, `.live-block.expanded`.

- [ ] **Step 1: HTML** — внутри `#testLiveResults` после h3 добавить `<div id="testLiveBlocks"></div>` (таблицу-заглушку убрать или оставить пустой для совместимости).
