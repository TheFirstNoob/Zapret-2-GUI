// ══════════════════════════ ТЕСТЕР ══════════════════════════

const CdnStab = {
  _polling: false,
  _pollTicks: 0,
  _applied: new Set(),

  VERDICTS: {
    fix: { label: 'DPI режет - лечится', cls: 'bad', btn: { action: 'general', text: 'В обход' } },
    covered: { label: 'уже в ipset-all - наложения нет', cls: '', btn: null },
    ok: { label: 'чисто', cls: '', btn: null },
    break: { label: 'обход ломает', cls: 'bad', btn: { action: 'exclude', text: 'В стоп-лист' } },
    hard: { label: 'не лечится', cls: '', btn: null },
    dead: { label: 'хост мёртв (не блок)', cls: '', btn: null },
    unknown: { label: 'не проверено', cls: '', btn: null },
  },

  _bound: false,

  init() {
    if (this._bound) return;
    this._bound = true;
    $('cdnScanBtn').addEventListener('click', () => this.scan());
    $('cdnCancelBtn').addEventListener('click', () => this.cancel());
    App.bindHelpToggle('cdnHelpBtn', 'cdnHelpDetails');
  },

  cancel() {
    apiPost('/tester/action', { action: 'cancel' }).catch(() => {});
    this._fail('Сканирование отменено.');
  },

  async scan() {
    if (this._polling || App.testActive) return;
    this._applied = new Set();
    App.setTestActive(true);
    $('cdnScanBtn').disabled = true;
    $('cdnIdle').hidden = true;
    $('cdnResults').hidden = true;
    $('cdnScanning').hidden = false;
    $('cdnProgressTitle').textContent = 'Подготовка…';
    $('cdnProgressPct').textContent = '0%';
    $('cdnProgressFill').style.width = '0%';
    try {
      // apiPost уже добавляет /api - пути без префикса
      const r = await apiPost('/tester/action', { action: 'cdn_scan' });
      if (r.status !== 'ok') {
        this._fail('Не удалось запустить сканирование: ' + (r.message || ''));
        return;
      }
      this._polling = true;
      this._pollTicks = 0;
      this._poll();
    } catch (err) {
      this._fail('Ошибка запуска: ' + err.message);
    }
  },

  _fail(msg) {
    this._stop();
    Activity.fail('Скан CDN: ' + msg);
    $('cdnIdle').hidden = true;
    $('cdnResults').hidden = false;
    $('cdnResults').innerHTML = `<div class="empty-note st-err">${escapeHtml(msg)}</div>`;
    showToast(msg, 'error');
  },

  async _poll() {
    if (!this._polling) return;
    if (++this._pollTicks > 200) {  // ~4 минуты максимум
      this._fail('Сканирование не завершилось за отведённое время.');
      return;
    }
    let st;
    try {
      st = await apiGet('/tester/status');
    } catch {
      this._fail('Не удалось получить статус сканирования.');
      return;
    }
    if (st.running) {
      // M4: гонка старта - worker проставляет action_type асинхронно; первые
      // тики видят action прошлого прогона → ложное «другая задача»
      if (st.action && st.action !== 'cdn_scan' && this._pollTicks > 3) {
        this._fail('Запущена другая задача тестера - сканирование CDN прервано.');
        return;
      }
      const p = st.progress || {};
      $('cdnProgressTitle').textContent = p.message || 'Сканирование…';
      const pct = p.percent ?? 0;
      Activity.set('cdn', p.message || 'Скан CDN', pct, true);
      $('cdnProgressPct').textContent = Math.round(pct) + '%';
      $('cdnProgressFill').style.width = Math.min(100, Math.max(0, pct)) + '%';
      $('cdnProgressFill').setAttribute('aria-valuenow', Math.min(100, Math.max(0, pct)));
      setTimeout(() => this._poll(), 1200);
      return;
    }
    const fr = st.final_result;
    if (fr && fr.type === 'cdn_scan') {
      if (fr.error) {
        this._fail(fr.error);
        return;
      }
      this._render(fr);
      Activity.done('Скан CDN завершён');
      if (fr.naked_done && fr.note) showToast(fr.note);
    } else {
      this._fail(fr?.error || 'Сканирование прервано.');
    }
    this._stop();
  },

  _stop() {
    this._polling = false;
    App.setTestActive(false);
    $('cdnScanBtn').disabled = false;
    $('cdnScanning').hidden = true;
  },

  _render(fr) {
    const v = fr.verdicts || [];
    this._lastVerdicts = v;
    const counts = {};
    v.forEach(x => { counts[x.verdict] = (counts[x.verdict] || 0) + 1; });
    const sum = (k) => counts[k] || 0;
    const modeTxt = fr.ipset_mode
      ? 'Режим: IP-обход (тоггл включён)'
      : 'Режим: Hostlist (тоггл выключен)';
    const abFixed = v.filter(x => x.ipset === 'чинит').length;
    const abBroken = v.filter(x => x.ipset === 'ломает').length;
    const abRan = abFixed + abBroken > 0;
    // Кнопки есть у строк с IP-действиями: «чинит» (точечный ipset-обход
    // хоста), «ломает» при ipset-режиме (исключить IP), fix/break - доменные.
    const actionable = sum('fix') + sum('break') + (fr.ipset_mode ? abBroken : 0) + (!fr.ipset_mode ? abFixed : 0);

    let banner = '';
    if (abRan || actionable) {
      const recTitle = abRan
        ? (abBroken > abFixed
          ? 'Держите «Общий IP-обход» выключенным'
          : (abFixed > abBroken ? '«Общий IP-обход» можно держать включённым' : 'Эффект IP-обхода неоднозначный'))
        : 'Есть правки для применения';
      const recDesc = abRan
        ? `IP-обход чинит <b>${abFixed}</b> хост(а), но ломает <b>${abBroken}</b> - решайте по нужным хостам.`
        : 'Нажмите кнопки в строках - правка применится к спискам, обход перезапустится автоматически.';
      banner = `<div class="rec-banner">
        <div>
          <span class="rec-tag">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            Рекомендация по IP-обходу
          </span>
          <div class="rec-title">${recTitle}</div>
          <div class="rec-desc">${recDesc}</div>
        </div>
        ${actionable ? `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <button id="cdnApplyAll" class="btn btn-primary">Применить все правки (${actionable})</button>
          <span class="meta rec-note" id="cdnApplyAllNote"></span>
        </div>` : ''}
      </div>`;
    }

    const metrics = `
      <span class="m-badge success" data-popover="Эти хосты открываются и без обхода - с ними всё хорошо.">✓ Чисто: ${sum('ok')}</span>
      ${actionable ? `<span class="m-badge warning" data-popover="Этим хостам обход мешает или их режет DPI - можно исправить кнопкой в строке.">● Требует правки: ${actionable}</span>` : ''}
      <span class="m-badge danger" data-popover="Не отвечает даже без обхода - похоже, сервер недоступен, это не блокировка.">✕ Не лечится: ${sum('hard')}</span>
      ${sum('covered') ? `<span class="m-badge neutral" data-popover="Уже покрыты общим IP-обходом - трогать не нужно.">Уже в ipset: ${sum('covered')}</span>` : ''}
      <span class="m-badge neutral" data-popover="Не отвечают ни с обходом, ни без него - вероятно, хост выключен или устарел.">Мёртвые: ${sum('dead')}</span>
      <span class="metrics-mode">${modeTxt}</span>`;

    const badgeCls = { fix: 'action', break: 'action', ok: 'clean', hard: 'fatal', dead: 'dead', covered: 'clean', unknown: 'neutral' };
    const badgeLabel = { fix: 'DPI режет - лечится', break: 'обход ломает', covered: 'уже в ipset', dead: 'хост мёртв' };
    const rows = v.map(x => {
      const vd = this.VERDICTS[x.verdict] || this.VERDICTS.unknown;
      const applied = this._applied.has(x.domain);
      let btn = '';
      let act = vd.btn || null;
      let actText = act ? act.text : '';
      // A/B-действия IP-based: «чинит» в hostlist-режиме -> ipset-включения;
      // «ломает» в ipset-режиме -> IP в исключения.
      if (!act && x.ipset === 'чинит' && !fr.ipset_mode && (x.ips || []).length) {
        act = { action: 'ipset-include' };
        actText = 'В ipset-включения';
      }
      if (!act && x.ipset === 'ломает' && fr.ipset_mode && (x.ips || []).length) {
        act = { action: 'ipset-exclude' };
        actText = 'Исключить IP';
      }
      if (!applied && act) {
        const text = (fr.ipset_mode && act.action === 'general')
          ? 'В ipset-включения' : actText;
        btn = `<button class="btn-row-action" data-cdn-act="${act.action}" data-cdn-domain="${escapeHtml(x.domain)}">${text}</button>`;
      } else if (applied) {
        btn = '<span class="meta">применено</span>';
      }
      const ips = (fr.ipset_mode && x.ips && x.ips.length)
        ? `<span class="meta"> ${escapeHtml(x.ips.join(', '))}</span>` : '';
      return `<tr data-cdn-ips="${escapeHtml((x.ips || []).join(','))}">
        <td><div class="host-cell">
          <span class="host-name">${escapeHtml(x.domain)}</span>
          ${x.provider ? `<span class="cdn-tag">${escapeHtml(x.provider)}</span>` : ''}
        </div></td>
        <td>${x.alive === 'A' ? 'да' : 'нет'}</td>
        <td>${x.dpi === 'DET' ? '<span class="st-err">режет</span>' : (x.dpi === 'ok' ? 'не режет' : '-')}</td>
        <td><span class="verdict-badge ${badgeCls[x.verdict] || 'neutral'}">${escapeHtml(badgeLabel[x.verdict] || vd.label)}</span>${ips}</td>
        <td>${x.ipset === 'ломает' ? '<span class="ip-ab-tag breaks">ломает</span>'
          : (x.ipset === 'чинит' ? '<span class="ip-ab-tag fixes">чинит</span>' : '-')}</td>
        <td style="text-align:right">${btn}</td>
      </tr>`;
    }).join('');

    let guide;
    if (actionable) {
      guide = 'Нажмите кнопку в строке - правка применится к спискам, и обход перезапустится автоматически. «чинит» = точечный IP-обход хоста; «ломает» = исключить его IP из IP-обхода. Либо примените всё сразу кнопкой вверху.';
    } else if (abRan) {
      guide = 'Точечных правок списков не требуется - смотрите итог по IP-обходу выше.';
    } else {
      guide = 'Живые хосты отвечают, stateful DPI не обнаружен, а мёртвые не отвечают и без защиты - это не блокировка. Проверять больше нечего.';
    }

    $('cdnResults').innerHTML = banner + `
      <div class="metrics-bar">${metrics}</div>
      <div class="hosts-table-wrap"><table class="hosts-table">
        <thead><tr>
          <th style="width:250px">Хост и CDN</th>
          <th style="width:90px">Под защитой</th>
          <th style="width:120px">Stateful DPI</th>
          <th>Вердикт</th>
          <th style="width:100px">IP-обход</th>
          <th style="width:170px;text-align:right">Действие</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="6"><div class="empty-note">Нет данных</div></td></tr>'}</tbody>
      </table></div>
      <div class="cdn-guide">${guide}</div>`;
    $('cdnResults').hidden = false;
    $('cdnResults').querySelectorAll('[data-cdn-act]').forEach(b =>
      b.addEventListener('click', () => this.apply(b, fr.ipset_mode)));
    const ab = $('cdnApplyAll');
    if (ab) ab.addEventListener('click', () => this.applyAll(fr));
    $('cdnResults').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  },

  // Собрать список правок из вердиктов (та же логика, что в apply()).
  _collectActions(fr) {
    const out = [];
    (this._lastVerdicts || []).forEach(x => {
      let action = null;
      if (x.verdict === 'fix') action = 'general';
      else if (x.verdict === 'break') action = 'exclude';
      else if (x.ipset === 'чинит' && !fr.ipset_mode && (x.ips || []).length) action = 'ipset-include';
      else if (x.ipset === 'ломает' && fr.ipset_mode && (x.ips || []).length) action = 'ipset-exclude';
      if (action && !this._applied.has(x.domain)) {
        out.push({ domain: x.domain, action, ips: x.ips || [] });
      }
    });
    return out;
  },

  async applyAll(fr) {
    const actions = this._collectActions(fr);
    if (!actions.length) return;
    const workingDomains = (this._lastVerdicts || [])
      .filter(x => x.alive === 'A')
      .map(x => x.domain);
    const preview = actions.map(a => `  ${a.domain} - ${a.action}`).join('\n');
    if (!confirm(`Применить все правки по матрице?\n\n${preview}\n\nОдин перезапуск обхода. Пропуски (наложения/нет IP) будут показаны.`)) return;
    const btn = $('cdnApplyAll');
    if (btn) { btn.disabled = true; btn.textContent = 'Применяю…'; }
    try {
      const r = await apiPost('/cdn/apply-all', {
        actions,
        working_domains: workingDomains,
      });
      if (r.status === 'ok') {
        (r.applied || []).forEach(d => this._applied.add(d));
        const skipped = r.skipped && r.skipped.length
          ? ` Пропущено: ${r.skipped.map(s => `${s.domain} (${s.reason})`).join('; ')}` : '';
        showToast(r.message, 'ok');
        const note = $('cdnApplyAllNote');
        if (note) note.textContent = skipped ? `⚠ ${skipped}` : '✓ всё применено';
        this._render(fr);
      } else {
        showToast('Ошибка: ' + (r.message || ''), 'error');
        if (btn) { btn.disabled = false; btn.textContent = `Применить все правки (${actions.length})`; }
      }
    } catch (err) {
      showToast('Ошибка: ' + err.message, 'error');
      if (btn) { btn.disabled = false; btn.textContent = `Применить все правки (${actions.length})`; }
    }
  },

  async apply(btn, ipsetMode) {
    const domain = btn.dataset.cdnDomain;
    const action = btn.dataset.cdnAct;
    const row = btn.closest('tr');
    const ips = row ? row.dataset.cdnIps : '';
    btn.disabled = true;
    btn.textContent = '…';
    try {
      // apiPost уже добавляет /api - путь без префикса
      // working_domains: живые в основном прогоне (кроме самой цели) - сервер
      // резолвит их в protection-множество и расширяет правки до наибольшего
      // чистого префикса (anycast сам вырождается в /32).
      const workingDomains = (this._lastVerdicts || [])
        .filter(x => x.alive === 'A' && x.domain !== domain)
        .map(x => x.domain);
      const r = await apiPost('/cdn/recommendation', {
        domain, action,
        ips: ips ? ips.split(',') : [],
        working_domains: workingDomains,
      });
      if (r.status === 'ok') {
        this._applied.add(domain);
        btn.textContent = '✓ ' + r.message.split(',')[0];
        showToast('Применено: ' + domain, 'ok');
      } else {
        btn.disabled = false;
        btn.textContent = (ipsetMode && action === 'general') ? 'В ipset-включения' : (action === 'general' ? 'В обход' : 'В стоп-лист');
        showToast('Ошибка: ' + (r.message || ''), 'error');
      }
    } catch (err) {
      btn.disabled = false;
      btn.textContent = (ipsetMode && action === 'general') ? 'В ipset-включения' : (action === 'general' ? 'В обход' : 'В стоп-лист');
      showToast('Ошибка: ' + err.message, 'error');
    }
  },
};
