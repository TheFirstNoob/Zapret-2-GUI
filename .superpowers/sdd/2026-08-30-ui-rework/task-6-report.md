# Task 6 Report: a11y и шрифты

**Статус:** Выполнено, закоммичено.

**Коммит:** `d81ad5e` — `style(a11y): focus-visible, reduced-motion, system fonts` (ветка main, только `frontend/css/app.css`, +34/−10)

## Что сделано

### 1. `:focus-visible` (палитра `--accent`)
- `.btn` — убран `outline: none` (глушил фокус), добавлен `.btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }`.
- `.toggle-switch input:focus-visible + .toggle-slider` — outline 2px accent, offset 2px (input скрыт, индикатор на слайдере).
- `#z1Card summary` / `.z1-details summary` — добавлен `:focus-visible` (outline 2px accent, offset 2px).
- `.chip-option input:focus-visible + span` — уже был (стр. 917–920), не трогал.
- `.live-block-head:focus-visible` — уже был (стр. 1283–1286), не трогал.
- `.input/.select/.textarea` — `outline: none` оставлен намеренно: там есть собственный видимый индикатор фокуса (`:focus` → border-color + box-shadow, стр. 657–660), фокус не глушится.

### 2. `prefers-reduced-motion`
Существующий блок (лампа + стрелка) расширен:
- Универсальный ресет `*, *::before, *::after` — `animation-duration: 0.01ms !important`, `animation-iteration-count: 1 !important`, `transition-duration: 0.01ms !important`, `scroll-behavior: auto !important` (покрывает fadeIn страниц, tileIn плиток, slideIn тостов, spin спиннера, все transition).
- Кот на прогресс-баре: `.progress-bar .fill::after { display: none; }` — GIF остановить CSS нельзя, поэтому скрывается целиком.
- Пульсация лампы `.live-block.active .live-block-lamp { animation: none; }` и стрелка — сохранены из исходного блока.

### 3. Шрифты (JetBrains Mono полностью удалён из frontend)
- body → `Bahnschrift, "Segoe UI Variable", "Segoe UI", Tahoma, sans-serif`.
- Mono-стеки (`.textarea`, `.detail-value`, `.test-log`, `.time-ms`, `.tile-time`) → `"Cascadia Mono", Consolas, monospace`.
- `.info-row .value.mono`, `.textarea-list` — `"Cascadia Code"` → `"Cascadia Mono"`.
- `.blocked-chip` → `var(--font-mono, "Cascadia Mono", Consolas, monospace)`.
- Grep подтверждает: JetBrains / Fira Code / Cascadia Code в frontend больше нет.

## Проверка
- Баланс скобок: `node css-brace-check.js frontend/css/app.css` → `open: 346 close: 346 balanced: true`.
- HTML/JS/другие страницы не трогались (diff — только `frontend/css/app.css`).

## Сомнения
- `.input/.select/.textarea` оставили `outline: none` (есть кастомный фокус-стиль). Если нужен именно браузерный outline — тривиально добавить `:focus-visible` с accent.
- Визуальная проверка (Tab-навигация, системный шрифт, reduced-motion) на живом UI не проводилась — рекомендую в Task 7.