### Task 2: Главная — CSS блоков

**Files:**
- Modify: `frontend/css/app.css` (конец файла)

**Interfaces:**
- Produces: классы `.status-line`, `.status-line .dot` (лампа), `.action-panel`, `.conflict-inline`, `.z1-details`, `.main-grid` упрощение.

- [ ] **Step 1: Добавить стили** — `.status-line`: одна строка, крупный статус (шрифт 15-16px), лампа-точка (зелёная/красная/серая по классу `.ok/.fail/.off`); `.action-panel`: flex, отступ сверху, смысловой разделитель `border-top`; `.conflict-inline`: красный текст на тёмном, padding 8-10px; `.z1-details summary`: кнопочный стиль (cursor, hover), без маркера `list-style:none`.
- [ ] **Step 2: Проверка** — открыть Главную: статус заметен первым, панель действий прижата низом, Z1-детали раскрываются/сворачиваются.
- [ ] **Step 3: Commit** — `git commit -m "style(main): status line, action panel, conflict inline, Z1 details"`

---

### Task 3: Тестер — чип-опции вместо чекбоксов

**Files:**
- Modify: `frontend/index.html` (test-options, строки 277-290), `frontend/css/app.css`

**Interfaces:**
- Consumes: id `cdnCheck`, `extendedCheck`, `logCheck` — сохранить (JS читает checked).
- Produces: разметка чипов `<label class="chip-option"><input type="checkbox" id="cdnCheck"><span>...</span></label>`.

- [ ] **Step 1: Заменить разметку опций** на чипы с галочкой ✓ (стиль из frontend2, но в нашей палитре), id чекбоксов те же.
- [ ] **Step 2: CSS чипов** — `.chip-option`: граница, radius, checked-состояние — акцентная заливка, focus-visible.
- [ ] **Step 3: Проверка** — `node --check`; интро тестера: чипы кликабельны, состояние сохраняется (тест реально учитывает).
