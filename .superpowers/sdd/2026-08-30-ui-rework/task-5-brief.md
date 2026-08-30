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

