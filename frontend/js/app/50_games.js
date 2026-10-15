// ══════════════════════════ СПИСКИ ══════════════════════════

// ── Игровые блокировки: домены (авторизация) + UDP-фикс (коннект) ──
// Домены применяются сразу (hot-reload hostlist), UDP-профили - при
// следующем запуске обхода/переустановке службы.
const GamesPage = {
  _data: null,
  _open: {},
  _svcWired: false,
  _customWired: false,
  _editId: null,
  _checks: {},

  async onShow() {
    const body = $('gamesBody');
    if (!this._svcWired) {
      const svcBtn = $('gamesSvcBtn');
      if (svcBtn) svcBtn.addEventListener('click', () => this.reinstallService());
      this._svcWired = true;
    }
    if (!this._customWired) {
      const add = $('gamesAddBtn');
      if (add) add.addEventListener('click', () => this.openCustomForm(null));
      const save = $('gcSave');
      if (save) save.addEventListener('click', () => this.saveCustom());
      const cancel = $('gcCancel');
      if (cancel) cancel.addEventListener('click', () => this.closeCustomForm());
      this._customWired = true;
    }
    try {
      const r = await apiGet('/games');
      this._data = (r.games && Array.isArray(r.games.games))
        ? r.games : { games: [] };
      this.render();
    } catch (e) {
      body.innerHTML = '<div class="empty-note">Не удалось загрузить: '
        + escapeHtml(e.message || String(e)) + '</div>';
    }
  },

  render() {
    const body = $('gamesBody');
    const games = this._data.games || [];
    const q = (($('gamesSearch') && $('gamesSearch').value) || '')
      .trim().toLowerCase();
    const visible = games.map((g, gi) => ({ g, gi })).filter(({ g }) =>
      !q || String(g.name || '').toLowerCase().includes(q) ||
      (g.domains || []).some(d =>
        String(d.domain || '').toLowerCase().includes(q)));
    if (!visible.length) {
      body.innerHTML = '<div class="empty-note">' +
        (games.length ? 'Ничего не найдено' : 'Список пуст') + '</div>';
      return;
    }
    body.innerHTML = visible.map(({ g, gi }) => {
      const open = !!this._open[g.id || gi];
      const domCount = (g.domains || []).length;
      const domOn = (g.domains || []).filter(d => d.on).length;
      const udpCount = (g.udp || []).length;
      const udpOn = (g.udp || []).filter(u => u.on).length;
      const udpPorts = (g.udp || []).map(u => u.ports).join(', ');
      const check = this._checks[g.id || gi] || null;
      const mark = (domain) => {
        if (!check) return '';
        const r = check[domain];
        if (!r) return '';
        return r.ok
          ? ' <span class="st-ok">✓</span>'
          : ` <span class="st-err" title="код ${escapeHtml(r.code)}">✗ ${escapeHtml(r.code)}</span>`;
      };
      return `
      <div class="game-item${open ? ' open' : ''}">
        <div class="game-row" data-g-expand="${gi}">
          <div class="game-left">
            <svg class="game-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
            <span class="game-title">${escapeHtml(g.name || g.id)}</span>
            <div class="game-badges">
              ${domCount ? `<span class="pill-badge" data-popover-title="Домены игры" data-popover="Включено ${domOn} из ${domCount}: ${escapeHtml((g.domains || []).map(d => d.domain).join(', '))}">домены: ${domOn}/${domCount}</span>` : ''}
              ${udpCount ? `<span class="pill-badge" data-popover-title="UDP-фикс" data-popover="Включено ${udpOn} из ${udpCount}. Порт: ${escapeHtml(udpPorts || '')}">UDP-фикс: ${udpOn}/${udpCount}</span>` : ''}
            </div>
          </div>
          <label class="switch" title="Включить игру" data-g-noexp="1">
            <input type="checkbox" data-g-on="${gi}" ${g.enabled ? 'checked' : ''}>
            <span class="switch-track"><span class="switch-knob"></span></span>
          </label>
        </div>
        <div class="game-details">
          <div class="detail-group">
            <div class="group-label">Домены авторизации и лобби</div>
            ${(g.domains || []).map((d, di) => `
              <label class="rule-item">
                <input type="checkbox" class="cbx" data-g-dom="${gi}:${di}" ${d.on ? 'checked' : ''}>
                <div class="rule-content">
                  <div class="rule-main-line">
                    <span class="rule-target">${escapeHtml(d.domain)}${mark(d.domain)}</span>
                  </div>
                  ${d.note ? `<div class="rule-comment">${d.tag ? `<span class="${d.warn ? 'comment-warning' : 'comment-tag'}">${escapeHtml(d.tag)}:</span> ` : ''}${escapeHtml(d.note)}</div>` : ''}
                </div>
              </label>`).join('') || '<div class="empty-note">Доменов нет</div>'}
          </div>
          <div class="detail-group">
            <div class="group-label">UDP-фикс (подключение к игровым серверам)</div>
            ${(g.udp || []).map((u, ui) => `
              <label class="rule-item">
                <input type="checkbox" class="cbx" data-g-udp="${gi}:${ui}" ${u.on ? 'checked' : ''}>
                <div class="rule-content">
                  <div class="rule-main-line">
                    <span class="rule-target">Порт UDP ${escapeHtml(u.ports)}</span>
                    <span class="pill-badge" style="color: var(--ok)">fake на старте</span>
                    ${(u.cidrs || []).length ? '' : '<span class="pill-badge" style="color: var(--warn-text)">широкий</span>'}
                  </div>
                  ${u.note ? `<div class="rule-comment">${u.tag ? `<span class="comment-tag">${escapeHtml(u.tag)}:</span> ` : ''}${escapeHtml(u.note)}</div>` : ''}
                  <div class="ip-subnets">Подсети: ${(u.cidrs || []).length ? escapeHtml((u.cidrs || []).join(', ')) : 'не заданы - правило широкое (весь порт)'}</div>
                </div>
              </label>`).join('') || '<div class="empty-note">UDP-правил нет</div>'}
          </div>
          <div class="game-actions" data-g-noexp="1">
            <button class="btn btn-sm" data-g-check="${gi}" ${domOn ? '' : 'disabled'} title="Быстрая проба включённых доменов игры: открываются ли они сейчас">Проверить домены</button>
            <button class="btn btn-sm" data-g-analyze="${gi}" ${g.process ? '' : 'disabled'} title="${g.process ? 'Запустить сетевой анализ процесса игры' : 'У игры не задан процесс'}">Анализ приложения</button>
            <span class="meta">${g.process ? 'процесс: ' + escapeHtml(g.process) : 'процесс не задан'}</span>
            ${g.custom ? `<button class="btn btn-sm" data-g-edit="${gi}">Изменить</button>
            <button class="btn btn-sm btn-danger-text" data-g-del="${gi}">Удалить</button>` : ''}
          </div>
        </div>
      </div>`;
    }).join('');
    body.querySelectorAll('[data-g-expand]').forEach(row =>
      row.addEventListener('click', (ev) => {
        if (ev.target.closest('[data-g-noexp]')) return;
        const gi = +row.dataset.gExpand;
        const key = games[gi].id || gi;
        this._open[key] = !this._open[key];
        this.render();
      }));
    body.querySelectorAll('[data-g-on]').forEach(cb =>
      cb.addEventListener('change', () => {
        games[+cb.dataset.gOn].enabled = cb.checked;
        this.save();
      }));
    body.querySelectorAll('[data-g-dom]').forEach(cb =>
      cb.addEventListener('change', () => {
        const [gi, di] = cb.dataset.gDom.split(':').map(Number);
        games[gi].domains[di].on = cb.checked;
        this.save();
      }));
    body.querySelectorAll('[data-g-udp]').forEach(cb =>
      cb.addEventListener('change', () => {
        const [gi, ui] = cb.dataset.gUdp.split(':').map(Number);
        games[gi].udp[ui].on = cb.checked;
        this.save();
      }));
    body.querySelectorAll('[data-g-analyze]').forEach(btn =>
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.analyzeGame(+btn.dataset.gAnalyze);
      }));
    body.querySelectorAll('[data-g-check]').forEach(btn =>
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.checkDomains(+btn.dataset.gCheck);
      }));
    body.querySelectorAll('[data-g-edit]').forEach(btn =>
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.openCustomForm(+btn.dataset.gEdit);
      }));
    body.querySelectorAll('[data-g-del]').forEach(btn =>
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        this.deleteCustom(+btn.dataset.gDel);
      }));
  },

  // Быстрая проба включённых доменов игры (сквозь текущий обход, если он есть)
  async checkDomains(gi) {
    const g = (this._data.games || [])[gi];
    if (!g) return;
    const key = g.id || gi;
    const btn = document.querySelector(`[data-g-check="${gi}"]`);
    if (btn) { btn.disabled = true; btn.textContent = 'Проверяю…'; }
    Activity.set('games', `Проверка доменов: ${g.name || g.id}`);
    try {
      const r = await apiPost('/games/check', { id: g.id || gi });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const map = {};
      (r.results || []).forEach(x => { map[x.domain] = x; });
      this._checks[key] = map;
      const bad = (r.results || []).filter(x => !x.ok);
      if (!r.results || !r.results.length) {
        Activity.done('Нечего проверять');
        showToast('Нет включённых доменов', 'warn');
      } else if (bad.length) {
        Activity.fail(`Не открываются: ${bad.length}`);
        showToast('Не открываются: ' + bad.map(x => x.domain).join(', '), 'warn');
      } else {
        Activity.done('Все домены открываются');
        showToast('Все домены открываются', 'ok');
      }
      this.render();
    } catch (e) {
      Activity.fail('Проверка доменов: ошибка');
      showToast('Проверка доменов: ' + (e.message || e), 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Проверить домены'; }
    }
  },

  openCustomForm(gi) {
    const form = $('gamesCustomForm');
    if (!form) return;
    const title = $('gamesCustomTitle');
    if (gi === null || gi === undefined) {
      this._editId = null;
      if (title) title.textContent = 'Своя игра';
      $('gcName').value = '';
      $('gcProcess').value = '';
      $('gcDomains').value = '';
      $('gcPorts').value = '';
      $('gcCidrs').value = '';
    } else {
      const g = (this._data.games || [])[gi];
      if (!g || !g.custom) return;
      this._editId = g.id;
      if (title) title.textContent = 'Своя игра: ' + (g.name || g.id);
      $('gcName').value = g.name || '';
      $('gcProcess').value = g.process || '';
      $('gcDomains').value = (g.domains || []).map(d => d.domain).join('\n');
      const u = (g.udp || [])[0] || {};
      $('gcPorts').value = u.ports || '';
      $('gcCidrs').value = (u.cidrs || []).join('\n');
    }
    form.hidden = false;
    $('gcName').focus();
  },

  closeCustomForm() {
    const form = $('gamesCustomForm');
    if (form) form.hidden = true;
    this._editId = null;
  },

  async saveCustom() {
    const btn = $('gcSave');
    if (btn) btn.disabled = true;
    try {
      const r = await apiPost('/games/custom', {
        action: 'save',
        game: {
          id: this._editId || '',
          name: ($('gcName').value || '').trim(),
          process: ($('gcProcess').value || '').trim(),
          domains_text: $('gcDomains').value || '',
          ports: ($('gcPorts').value || '').trim(),
          cidrs_text: $('gcCidrs').value || '',
        },
      });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      this._data = (r.games && Array.isArray(r.games.games)) ? r.games : this._data;
      this.closeCustomForm();
      this.render();
      showToast(r.message || 'Сохранено', 'ok');
    } catch (e) {
      showToast('Своя игра: ' + (e.message || e), 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async deleteCustom(gi) {
    const g = (this._data.games || [])[gi];
    if (!g || !g.custom) return;
    const ok = await Confirm.ask({
      title: 'Удалить свою игру?',
      text: `«${g.name || g.id}» будет удалена вместе с доменами и UDP-правилом.`,
      ok: 'Удалить',
    });
    if (!ok) return;
    try {
      const r = await apiPost('/games/custom', { action: 'delete', id: g.id });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      this._data = (r.games && Array.isArray(r.games.games)) ? r.games : this._data;
      this.render();
      showToast('Игра удалена', 'ok');
    } catch (e) {
      showToast('Удаление: ' + (e.message || e), 'error');
    }
  },

  async reinstallService() {
    const ok = await Confirm.ask({
      title: 'Переустановить службу?',
      text: 'Это нужно, чтобы UDP-фикс игр вступил в силу. Обход на пару секунд прервётся.',
      ok: 'Переустановить',
    });
    if (!ok) return;
    MainPage.svcInstall();
  },

  analyzeGame(gi) {
    const g = (this._data.games || [])[gi];
    const proc = ((g && g.process) || '').trim();
    if (!proc) {
      showToast('У игры не задан процесс для анализа', 'error');
      return;
    }
    // Запомним игру: в анализе найденные домены можно будет добавить сразу в неё
    TesterPage._gameContext = { id: g.id || gi, name: g.name || g.id };
    location.hash = '#probe';
    setTimeout(async () => {
      const inp = $('probeProcInput');
      if (inp) inp.value = proc;
      try { await TesterPage.scanProbeProcesses(true); } catch (e) { /* не критично */ }
      if (TesterPage._hintProbeProcess) TesterPage._hintProbeProcess();
      TesterPage.startProbe();
    }, 250);
  },

  async save() {
    try {
      const r = await apiPost('/games/save', { games: this._data });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'Сохранено', 'ok');
    } catch (e) {
      showToast('Игровые блокировки: ' + (e.message || e), 'error');
    }
  },
};
