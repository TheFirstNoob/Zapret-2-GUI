# Task 3 Report: Тестер — чип-опции вместо чекбоксов

**Статус:** выполнено

**Коммит:** `1be5326` — `feat(tester): chip options instead of checkboxes`

## Что сделано

### frontend/index.html (test-options, интро тестера)
- Три `label.checkbox-label` с чекбоксами заменены на чипы `<label class="chip-option"><input type="checkbox" id="..."><span>...</span></label>`.
- id сохранены: `cdnCheck`, `extendedCheck`, `logCheck` — JS читает `.checked` (frontend/js/app.js:947-949).
- Доп. текст вынесен в `<small>` (как в frontend2): `CDN-хосты <small>+5–10 мин</small>` и т.д.

### frontend/css/app.css
- `.test-options` переведён из колонки в flex-wrap (в духе `.options` в frontend2).
- Новые стили `.chip-option`:
  - скрытый input (`position:absolute; opacity:0; pointer-events:none` — клик работает через label);
  - span: граница `--border-strong`, radius 24px, фон `--surface`, hover — граница `--accent`;
  - checked: граница/текст `--accent`, фон `--accent-bg`, галочка `✓` через `::before`;
  - `input:focus-visible + span` — outline 2px `--accent`.
- Палитра — существующие переменные app.css (`--accent`, `--accent-bg`, `--border-strong`, `--surface`, `--text-secondary`, `--text-muted`); жёлтый/капс из frontend2 не копировались.

## Проверка
- `node --check frontend/js/app.js` — OK (JS не изменялся, синтаксис не нарушен).
- Визуально по коду: чипы кликабельны (input внутри label), checked-состояние сохраняется (id те же, `.checked` читается там же), галочка отображается только в checked-состоянии.
- `git diff --stat`: изменены только `frontend/index.html` и `frontend/css/app.css`. `frontend2/` и другие страницы не тронуты.

## Сомнения
- Стиль проверен только по коду (запуск GUI не выполнялся).
- В frontend2 класс называется `.chip-opt`, в брифе — `.chip-option`; использован вариант из брифа.