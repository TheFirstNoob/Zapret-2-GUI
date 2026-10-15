// ══════════════════════════ ПРОВЕРКА СИСТЕМЫ ══════════════════════════

const DiagnosticsPage = {
  _last: '',

  onShow() {
    if (!this._bound) {
      this._bound = true;
      $('diagRunBtn').addEventListener('click', () => this.run());
      $('diagCopyBtn').addEventListener('click', () => this.copyReport());
    }
  },

  async run() {
    if (App.testActive) {
      showToast('Идёт другая проверка - дождитесь завершения', 'warn');
      return;
    }
    App.setTestActive(true);
    const btn = $('diagRunBtn');
    btn.disabled = true;
    btn.textContent = 'Проверяю…';
    $('diagCopyBtn').hidden = true;
    $('diagIdle').hidden = true;
    $('diagResults').hidden = true;
    $('diagLoading').hidden = false;
    const t0 = Date.now();
    const timer = setInterval(() => {
      const el = $('diagTimer');
      if (el) el.textContent = Math.round((Date.now() - t0) / 1000);
    }, 1000);
    try {
      const started = await apiPost('/diagnose/action', {});
      if (started.status !== 'ok') throw new Error(started.message || 'ошибка');
      let report = null;
      // Страховка от вечного цикла: диагностика на бэкенде не живёт дольше
      // трёх минут - если статус не пришёл, считаем backend зависшим.
      const deadline = Date.now() + 3 * 60 * 1000;
      while (report === null) {
        await new Promise(res => setTimeout(res, 300));
        if (Date.now() > deadline) throw new Error('backend не отвечает');
        const st = await apiGet('/diagnose/status');
        if (st.error) throw new Error(st.error);
        const cur = $('diagCurrent');
        if (cur && st.progress) cur.textContent = st.progress;
        if (st.running) Activity.set('diagnostics', st.progress || 'Проверка системы');
        if (!st.running) report = st.report;
      }
      if (!report) throw new Error('нет результата');
      Activity.done('Проверка системы завершена');
      localStorage.setItem('z2_diag_done', String(Date.now()));
      const note = $('diagDoneNote');
      if (note) note.hidden = false;
      this.render(report);
    } catch (e) {
      $('diagLoading').hidden = true;
      $('diagResults').hidden = false;
      $('diagSummary').innerHTML = '';
      $('diagList').innerHTML = '<div class="diag-err">Ошибка диагностики: ' + escapeHtml(String(e.message || e)) + '</div>';
      $('diagRecommend').hidden = true;
    }
    clearInterval(timer);
    App.setTestActive(false);
    btn.disabled = false;
    btn.textContent = this._last ? 'Повторить' : 'Проверить';
  },

  render(report) {
    const s = report.summary || {};
    $('diagLoading').hidden = true;
    $('diagResults').hidden = false;

    const badges = [];
    if (s.ok) badges.push(`<span class="badge badge-ok">✓ ${s.ok} пройдено</span>`);
    if (s.warn) badges.push(`<span class="badge badge-warn">! ${s.warn} внимание</span>`);
    if (s.fail) badges.push(`<span class="badge badge-err">✕ ${s.fail} ошибок</span>`);
    if (s.skip) badges.push(`<span class="badge badge-mute">- ${s.skip} пропущено</span>`);
    if (report.elapsed_sec != null) badges.push(`<span class="badge badge-mute">⏱ ${report.elapsed_sec} с</span>`);
    $('diagSummary').innerHTML = badges.join('');

    const ICONS = {
      ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
      warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      fail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
      skip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    };

    const rows = (report.checks || []).map(c => `
      <div class="diag-row chk-${c.status}">
        <div class="diag-icon">${ICONS[c.status] || ICONS.skip}</div>
        <div class="diag-param">${escapeHtml(c.name)}</div>
        <div class="diag-value"${c.tech ? ` data-popover-title="Технические детали" data-popover="${escapeHtml(c.tech)}"` : ''}>${escapeHtml(c.detail || '')}</div>
      </div>`).join('');
    $('diagList').innerHTML = rows || '<div class="empty-note">Нет результатов</div>';

    $('diagRecommend').hidden = !((s.fail || 0) > 0);

    this._last = report.report_text || '';
    $('diagCopyBtn').hidden = !this._last;
  },

  async copyReport() {
    if (!this._last) return;
    try {
      await navigator.clipboard.writeText(this._last);
      showToast('Отчёт скопирован', 'ok');
    } catch (e) {
      const ta = document.createElement('textarea');
      ta.value = this._last;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); showToast('Отчёт скопирован', 'ok'); }
      catch (e2) { showToast('Не удалось скопировать', 'warn'); }
      document.body.removeChild(ta);
    }
  },
};
