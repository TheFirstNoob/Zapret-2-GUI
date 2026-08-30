### Task 6: Общее — a11y и шрифты

**Files:**
- Modify: `frontend/css/app.css`

**Interfaces:**
- Produces: `:focus-visible` глобально; `prefers-reduced-motion`; системные шрифты (Bahnschrift/Segoe UI Variable/Cascadia Mono fallback) — убрать JetBrains Mono из стека.

- [ ] **Step 1: CSS-правки** — `:focus-visible` на .btn/.toggle/.chip-option/.live-block summary; media `prefers-reduced-motion` (отключить анимации кота/прогресса); font-family: системный стек, JetBrains Mono удалить.
- [ ] **Step 2: Проверка** — `node --check` не нужен (CSS), визуально: фокус виден (Tab), анимации отключаются, шрифт системный.
- [ ] **Step 3: Commit** — `git commit -m "style(a11y): focus-visible, reduced-motion, system fonts"`

---

### Task 7: Регрессия и сборка

**Files:**
- All above + дистрибутивы

