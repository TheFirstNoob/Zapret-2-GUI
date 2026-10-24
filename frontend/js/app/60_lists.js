const ListsPage = {
  _loaded: false,
  saved: {},
  _badLines: {},   // key -> массив номеров ошибочных строк (для гутера)
  _bundled: null,   // Set доменов из bundled-включений (для проверки приоритетов)
  _activeList: 'domInc',

  showList(key) {
    if (!this.editors[key]) return;
    this._activeList = key;
    document.querySelectorAll('[data-list-tab]').forEach(t => {
      const on = t.dataset.listTab === key;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('[data-list-panel]').forEach(p =>
      p.classList.toggle('active', p.dataset.listPanel === key));
    const ta = $(key + 'Textarea');
    if (ta) this._syncNums(key);
  },

  editors: {
    domInc: { api: '/include-list', kind: 'domain' },
    domExc: { api: '/exclude-list', kind: 'domain' },
    ipInc: { api: '/ipset-include-list', kind: 'cidr' },
    ipExc: { api: '/ipset-exclude-list', kind: 'cidr' },
  },

  onShow() {
    if (!this._loaded) {
      this._loaded = true;
      const helpBtn = $('toggleHelpBtn');
      if (helpBtn) helpBtn.addEventListener('click', () => {
        const det = $('helpDetails');
        const open = !!det && det.hidden;
        if (det) det.hidden = !open;
        helpBtn.classList.toggle('is-open', open);
      });
      document.querySelectorAll('[data-save]').forEach(btn =>
        btn.addEventListener('click', () => this.save(btn.dataset.save)));
      // Вкладки списков: один большой редактор вместо четырёх окон
      document.querySelectorAll('[data-list-tab]').forEach(tab =>
        tab.addEventListener('click', () => this.showList(tab.dataset.listTab)));
      this.showList(this._activeList || 'domInc');
      apiGet('/bundled-domains')
        .then(r => { this._bundled = new Set(r.domains || []); })
        .catch(() => {});
      Object.keys(this.editors).forEach(key => {
        const ta = $(key + 'Textarea');
        ta.addEventListener('input', () => this.validate(key));
        ta.addEventListener('scroll', () => this._syncNums(key));
        this.load(key);
      });
      // резервная копия настроек (экспорт/импорт юзер-файлов)
      const exp = $('btnSettingsExport');
      if (exp) exp.addEventListener('click', () => this.exportSettings());
      const hc = $('btnListsCheck');
      if (hc) hc.addEventListener('click', () => this.checkHealth(true));
      const hd = $('btnListsDedupe');
      if (hd) hd.addEventListener('click', () => this.dedupeLists());
    }
    this.checkHealth(false);
    this.loadContested();
  },

  async exportSettings() {
    const btn = $('sideExport');
    if (btn) btn.disabled = true;
    try {
      const r = await apiPost('/settings/export', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const fileName = (r.name || '').split('\\').pop();
      showToast(`Настройки сохранены: ${fileName} в папке программы`, 'ok');
    } catch (e) {
      showToast('Экспорт не удался: ' + (e.message || e), 'error');
    }
    if (btn) btn.disabled = false;
  },

  async importSettings(input) {
    const file = input.files && input.files[0];
    if (!file) return;
    // Импорт без спроса перетирает текущие списки, пресеты и конфиг, причём
    // восстановить их после можно только экспортом, которого у новичка может
    // не быть. Остальные разрушительные действия спрашивают через Confirm.
    const ok = await Confirm.ask({
      title: 'Импорт настроек из архива',
      text: `Файл «${file.name}» заменит текущие настройки Zapret 2: списки доменов и ipset, пресеты и файл конфигурации. Ваши текущие значения будут потеряны без возможности отмены.`,
      ok: 'Импортировать и заменить',
      danger: true,
    });
    if (!ok) { input.value = ''; return; }
    const btn = $('sideExport');
    if (btn) btn.disabled = true;
    try {
      const b64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
        reader.onerror = () => reject(new Error('не удалось прочитать файл'));
        reader.readAsDataURL(file);
      });
      const r = await apiPost('/settings/import', { data: b64 });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'Настройки восстановлены', 'ok');
      await this.load('domInc');
      await this.load('domExc');
      await this.load('ipInc');
      await this.load('ipExc');
    } catch (e) {
      showToast('Импорт не удался: ' + (e.message || e), 'error');
    }
    input.value = '';
    if (btn) btn.disabled = false;
  },

  // ── Спорные домены (AWS и др.: десинк одним нужен, других ломает) ──
  async loadContested() {
    const body = $('contestedBody');
    const prot = $('contestedProt');
    if (!body) return;
    try {
      const r = await apiGet('/contested/status');
      if (prot) {
        const dot = prot.querySelector('.dot');
        const txt = prot.querySelector('.state-text');
        const running = !!r.protection_running;
        dot.className = 'dot ' + (running ? 'dot-ok' : 'dot-off');
        txt.className = 'state-text ' + (running ? 'st-ok' : 'st-mute');
        txt.textContent = running ? 'проба идёт через работающий обход' : 'обход не запущен - проба будет «в голую»';
      }
      body.innerHTML = '';
      for (const it of (r.items || [])) {
        const block = document.createElement('div');
        block.className = 'service-block';
        block.innerHTML = `
          <div class="service-row">
            <div class="service-info">
              <span class="service-name">${escapeHtml(it.title)}</span>
              <span class="service-domain">${escapeHtml(it.domain)}</span>
            </div>
            <div class="service-desc">${escapeHtml(it.why)}</div>
            <div class="service-actions">
              <button class="btn btn-sm btn-primary" data-ct-check="${escapeHtml(it.id)}">Проба</button>
              <span class="switch-cap">в обход</span>
              <label class="switch" title="Включить/выключить обход для этого домена">
                <input type="checkbox" ${it.enabled ? 'checked' : ''} data-ct-id="${escapeHtml(it.id)}">
                <span class="switch-track"><span class="switch-knob"></span></span>
              </label>
            </div>
          </div>
          <div data-ct-result="${escapeHtml(it.id)}"></div>`;
        body.appendChild(block);
      }
      body.querySelectorAll('[data-ct-id]').forEach(cb =>
        cb.addEventListener('change', () => this.toggleContested(cb.dataset.ctId, cb.checked, cb)));
      body.querySelectorAll('[data-ct-check]').forEach(btn =>
        btn.addEventListener('click', () => this.checkContested(btn.dataset.ctCheck, btn)));
    } catch (err) {
      frontendLog('contested: CATCH ' + (err.message || String(err)));
      body.innerHTML = '<div class="empty-note">Не удалось загрузить спорные домены: '
        + escapeHtml(err.message || String(err)) + '</div>';
    }
  },

  async toggleContested(id, enabled, cb) {
    cb.disabled = true;
    try {
      const r = await apiPost('/contested/toggle', { id, enabled });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message, 'ok');
      const res = document.querySelector(`[data-ct-result="${id}"]`);
      if (res) res.textContent = '';
      // Не перезагружаем редактор поверх несохранённого текста.
      if (!this._dirtyCheck('domInc')) await this.load('domInc');
    } catch (e) {
      showToast('Спорные домены: ' + (e.message || e), 'error');
      cb.checked = !enabled;
    }
    cb.disabled = false;
  },

  async checkContested(id, btn) {
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = 'Проба…';
    const res = document.querySelector(`[data-ct-result="${id}"]`);
    if (res) {
      res.innerHTML = '<div class="test-result-box loading"><div class="mini-spinner"></div>' +
        '<span>Отправка тестового запроса (до 10 сек)…</span></div>';
    }
    try {
      const r = await apiPost('/contested/check', { id });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const code = parseInt(r.code, 10);
      const alive = code >= 100 && code < 500 && code !== 0;
      const engine = !!r.engine_running;
      const toggled = !!r.enabled;
      const protectedNow = engine && toggled;  // домен реально обрабатывается обходом
      const badge = `${alive ? '✓' : '✕'} HTTP ${r.code || '-'} · ${r.elapsed} с`;
      let title, advice;
      if (alive) {
        if (protectedNow) {
          title = 'Работает с обходом';
          advice = 'Домен включён в обход и отвечает. Тумблер можно оставить включённым.';
        } else if (toggled) {
          title = 'Работает без обхода';
          advice = 'Обход сейчас не запущен. Тумблер включён - перепроверьте после запуска обхода: если с обходом сервис ломается, тумблер стоит выключить.';
        } else {
          title = 'Работает без обхода';
          advice = 'Домен не в обходе и отвечает. Тумблер не нужен - держите выключенным.';
        }
      } else if (protectedNow) {
        title = 'С обходом не отвечает';
        advice = 'Тумблер включён - вероятно, текущий десинк ломает сервис. Выключите тумблер и повторите пробу: правка списков применяется к новым подключениям. Если и без обхода нет - жёсткий блок, потребуется WARP.';
      } else if (!engine) {
        title = 'Обход не запущен';
        advice = toggled
          ? 'Запустите обход и повторите пробу - тумблер уже включён.'
          : 'Запустите обход и повторите пробу. Если сервис без обхода не живёт - включите тумблер.';
      } else {
        title = 'Не отвечает и без обхода';
        advice = 'Домен не в обходе. Включите тумблер и повторите пробу - правка списков применяется к новым подключениям. Если и с обходом нет - IP-блок, поможет только WARP.';
      }
      if (res) {
        res.innerHTML = `
          <div class="test-result-box ${alive ? 'success' : 'danger'}">
            <span class="res-badge">${badge}</span>
            <div class="res-content">
              <span class="res-title">${title}</span>
              <span class="res-advice">${advice}</span>
            </div>
          </div>`;
      }
      showToast(`Проба: HTTP ${r.code || '-'}`, alive ? 'ok' : 'error');
    } catch (e) {
      if (res) {
        res.innerHTML = `<div class="test-result-box danger">
          <span class="res-badge">✕</span>
          <div class="res-content"><span class="res-title">Ошибка пробы</span>
          <span class="res-advice">${escapeHtml(e.message || String(e))}</span></div></div>`;
      }
      showToast('Проба: ' + (e.message || e), 'error');
    }
    btn.textContent = label;
    btn.disabled = false;
  },

  // ── Здоровье списков: дубли/повторы/конфликты (серверный list_health) ──

  async checkHealth(warnIfClear) {
    const txt = $('listsHealthText');
    const btn = $('btnListsDedupe');
    if (!txt) return;
    txt.textContent = 'Проверяю…';
    try {
      const r = await apiGet('/lists/health');
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const bits = [];
      if (r.total_dups) bits.push(`дубли: ${r.total_dups}`);
      if (r.total_cross) bits.push(`повторы между вашими списками: ${r.total_cross}`);
      if (r.total_redundant) bits.push(`повторы уже включённых: ${r.total_redundant}`);
      if (r.total_conflicts) bits.push(`конфликты вкл/искл: ${r.total_conflicts}`);
      if (bits.length) {
        const example = (r.conflicts[0] && r.conflicts[0].entry)
          || (r.redundant[0] && r.redundant[0].entry) || '';
        txt.innerHTML = `<span class="st-err">Найдено: ${escapeHtml(bits.join(' · '))}</span>`
          + (example ? ` <span class="meta">(например: ${escapeHtml(example)})</span>` : '');
        if (btn) btn.hidden = false;
        if (warnIfClear) showToast('Списки: ' + bits.join(' · '), 'warn');
      } else {
        txt.textContent = 'Проблем не найдено - списки чистые.';
        if (btn) btn.hidden = true;
        if (warnIfClear) showToast('Списки в порядке', 'ok');
      }
    } catch (e) {
      txt.textContent = 'Не удалось проверить: ' + (e.message || e);
    }
  },

  async dedupeLists() {
    const ok = await Confirm.ask({
      title: 'Убрать дубли во всех списках?',
      text: 'Несохранённые правки в полях будут потеряны.',
      ok: 'Убрать дубли',
      danger: true,
    });
    if (!ok) return;
    const btn = $('btnListsDedupe');
    btn.disabled = true;
    try {
      const r = await apiPost('/lists/dedupe', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.total ? `Убрано лишних записей: ${r.total}` : 'Дублей не найдено', 'ok');
      Object.keys(this.editors).forEach(key => this.load(key));
      this.checkHealth(false);
    } catch (e) {
      showToast('Не удалось почистить: ' + (e.message || e), 'error');
    }
    btn.disabled = false;
  },

  // Кнопка «В обход» из подсказок анализа приложения (дедуп на сервере)
  async addDomainSuggestion(btn) {
    const domain = btn.dataset.addDomain;
    btn.disabled = true;
    try {
      const r = await apiPost('/lists/add-domain', { domain, mode: 'include' });
      btn.textContent = r.message || 'Готово';
      showToast(`${domain}: ${r.message || ''}`.trim(), r.status === 'ok' ? 'ok' : 'warn');
      if (r.status === 'ok') this.checkHealth(false);
    } catch (e) {
      btn.textContent = 'Ошибка';
      showToast('Не удалось добавить: ' + (e.message || e), 'error');
    }
  },

  async load(key) {
    const e = this.editors[key];
    try {
      const r = await apiGet(e.api);
      $(key + 'Textarea').value = r.content || '';
      this.saved[key] = $(key + 'Textarea').value;
      this.validate(key);
    } catch (err) {
      $(key + 'Valid').innerHTML = '<span class="bad">не удалось загрузить список</span>';
    }
  },

  _dirtyCheck(key) {
    const dirty = $(key + 'Textarea').value !== (this.saved[key] ?? '');
    const cnt = $(key + 'Count');
    if (cnt) cnt.classList.toggle('dirty', dirty);
    const btn = document.querySelector(`[data-save="${key}"]`);
    if (btn) btn.classList.toggle('dirty', dirty);
    const ta = $(key + 'Textarea');
    const card = ta && ta.closest('.list-card');
    if (card) card.classList.toggle('is-dirty', dirty);
    return dirty;
  },

  validate(key) {
    const e = this.editors[key];
    const ta = $(key + 'Textarea');
    const lines = ta.value.split('\n');
    let ok = 0;
    const bad = [];
    lines.forEach((line, i) => {
      const s = line.trim();
      if (!s || s.startsWith('#')) return;
      if (e.kind === 'domain' ? this._validDomain(s) : this._validCidr(s)) ok++;
      else bad.push(i + 1);
    });
    this._badLines[key] = bad;
    this._syncNums(key);
    const dirty = this._dirtyCheck(key);

    const cnt = $(key + 'Count');
    if (cnt) cnt.textContent = String(ok);

    const btn = document.querySelector(`[data-save="${key}"]`);
    if (btn) btn.disabled = bad.length > 0 || !dirty;

    const wrap = ta.closest('.editor-wrapper');
    if (wrap) wrap.classList.toggle('has-error', bad.length > 0);
    const card = ta.closest('.list-card');
    if (card) card.classList.toggle('is-error', bad.length > 0);

    const ICON_ERR = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
    const ICON_DOT = '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="8"/></svg>';
    const ICON_OK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    const box = $(key + 'Valid');
    box.className = 'status-msg';
    box.removeAttribute('data-popover');
    if (bad.length) {
      box.classList.add('status-error');
      const errText = `строки с ошибкой: ${bad.slice(0, 12).join(', ')}${bad.length > 12 ? '…' : ''} - сохранение заблокировано`;
      box.innerHTML = ICON_ERR + `<span>${errText}</span>`;
      box.setAttribute('data-popover', errText);
    } else if (dirty) {
      box.classList.add('status-unsaved');
      box.innerHTML = ICON_DOT + '<span>изменения не сохранены - нажмите «Сохранить»</span>';
    } else if (ok === 0) {
      box.classList.add('status-empty');
      box.innerHTML = '<span>список пуст - ни на что не влияет</span>';
    } else {
      box.classList.add('status-synced');
      box.innerHTML = ICON_OK + '<span>сохранено</span>';
    }
    $(key + 'Result').textContent = '';
    return bad.length === 0;
  },

  // Пересечение пользовательского списка с bundled-включениями
  _bundledOverlap(key) {
    if (!this._bundled || !this._bundled.size) return [];
    if (key !== 'domInc' && key !== 'domExc') return [];
    return $(key + 'Textarea').value.split('\n')
      .map(l => l.trim().toLowerCase())
      .filter(l => l && !l.startsWith('#') && this._bundled.has(l));
  },

  _fmtList(items) {
    return items.slice(0, 3).join(', ') + (items.length > 3 ? ` +${items.length - 3}` : '');
  },

  _validDomain(s) {
    if (/\s|,|;|\//.test(s) || s.startsWith('.') || s.endsWith('.')) return false;
    return /^[A-Za-z0-9А-Яа-яЁё]([A-Za-z0-9А-Яа-яЁё_-]*[A-Za-z0-9А-Яа-яЁё])?(\.[A-Za-z0-9А-Яа-яЁё]([A-Za-z0-9А-Яа-яЁё_-]*[A-Za-z0-9А-Яа-яЁё])?)+\.?$/.test(s);
  },

  _syncNums(key) {
    const ta = $(key + 'Textarea');
    const nums = $(key + 'Nums');
    if (!nums) return;
    const n = ta.value.split('\n').length;
    const bad = new Set(this._badLines[key] || []);
    let html = '';
    for (let i = 1; i <= n; i++) {
      html += (i > 1 ? '\n' : '') + (bad.has(i) ? `<span class="bad-line">${i}</span>` : String(i));
    }
    nums.innerHTML = html;
    nums.scrollTop = ta.scrollTop;
  },

  _validCidr(s) {
    if (s.indexOf(':') >= 0) return /^[0-9a-fA-F:]+(\/\d{1,3})?$/.test(s);
    const m = s.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/(\d{1,2}))?$/);
    if (!m) return false;
    for (let i = 1; i <= 4; i++) if (+m[i] > 255) return false;
    if (m[5] != null && +m[5] > 32) return false;
    return true;
  },

  async save(key) {
    if (!this.validate(key)) {
      showToast('Исправьте ошибочные строки - список не сохранён', 'error');
      return;
    }
    const e = this.editors[key];
    const el = $(key + 'Result');
    const sent = $(key + 'Textarea').value;
    el.textContent = 'Сохранение…';
    try {
      const r = await apiPost(e.api, { content: sent });
      if (r.status === 'ok') {
        el.textContent = 'сохранено';
        // Фиксируем именно ОТПРАВЛЕННОЕ значение: если пользователь печатал
        // во время запроса, его новые символы остаются dirty и не теряются.
        this.saved[key] = sent;
        // winws2 перечитывает списки на лету (mtime) - правка вступает в
        // силу для НОВЫХ подключений, перезапуск обхода не нужен.
        let msg = 'Список сохранён - применится к новым подключениям';
        let type = 'ok';
        const overlap = this._bundledOverlap(key);
        if (key === 'domExc' && overlap.length) {
          // Исключение сильнее включения (hostlist.c: exclude проверяется
          // первым) - пользователь должен знать, что обход на домен отключится.
          msg = 'Приоритет у исключения: обход отключится для ' + this._fmtList(overlap) + '. ' + msg;
          type = 'warn';
        } else if (key === 'domInc' && overlap.length) {
          msg += ' (уже в стандартных списках - дубль безвреден: ' + this._fmtList(overlap) + ')';
        }
        showToast(msg, type);
        this.validate(key);
      } else {
        el.textContent = 'ошибка';
        showToast('Ошибка сохранения: ' + (r.message || ''), 'error');
      }
    } catch (err) {
      el.textContent = 'ошибка';
      showToast('Ошибка: ' + err.message, 'error');
    }
  },
};
