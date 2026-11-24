// ══════════════════════════ ПРОВЕРКА СИСТЕМЫ ══════════════════════════

const DiagnosticsPage = {
  _last: '',

  onShow() {
    if (!this._bound) {
      this._bound = true;
      $('diagRunBtn').addEventListener('click', () => this.run());
      $('diagCopyBtn').addEventListener('click', () => this.copyReport());
      $('discordFixScanBtn').addEventListener('click', () => this.discordFixScan());
      $('discordFixEnableHostsBtn').addEventListener('click', () => this.discordFixEnable('hosts'));
      $('discordFixEnableBtn').addEventListener('click', () => this.discordFixEnable('full'));
      $('discordFixRotateBtn').addEventListener('click', () => this.discordFixRotate());
      $('discordFixDisableBtn').addEventListener('click', () => this.discordFixDisable());
      $('youtubeFixEnableBtn').addEventListener('click', () => this.youtubeFixEnable());
      $('youtubeFixRotateBtn').addEventListener('click', () => this.youtubeFixRotate());
      $('youtubeFixDisableBtn').addEventListener('click', () => this.youtubeFixDisable());
    }
    this.discordFixLoad();
    this.youtubeFixLoad();
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
      let pollFails = 0;
      // Страховка от вечного цикла: диагностика на бэкенде не живёт дольше
      // трёх минут - если статус не пришёл, считаем backend зависшим.
      const deadline = Date.now() + 3 * 60 * 1000;
      while (report === null) {
        await new Promise(res => setTimeout(res, 300));
        if (Date.now() > deadline) throw new Error('backend не отвечает');
        let st;
        try {
          st = await apiGet('/diagnose/status');
          pollFails = 0;
        } catch (e) {
          // Единичный сбой HTTP не означает, что диагностика остановилась:
          // сервер продолжает проверку, поэтому коротко терпим и опрашиваем.
          pollFails += 1;
          if (pollFails < 5) continue;
          throw e;
        }
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
      Activity.fail('Проверка системы: ' + String(e.message || e));
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
  async discordFixLoad() {
    try {
      const r = await apiGet('/discord-fix/status');
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const active = !!r.enabled;
      $('discordFixEnableBtn').hidden = active;
      $('discordFixEnableHostsBtn').hidden = active;
      $('discordFixDisableBtn').hidden = !active;
      $('discordFixRotateBtn').hidden = !active;
      const dnsState = r.mode === 'hosts'
        ? 'hosts-only (без задачи/DNS)'
        : (r.mode === 'task'
          ? 'автозапуск: ' + (r.task_state || '?')
          : (r.dns_running ? 'DNS работает (GUI)' : 'DNS не запущен'));
      const mapped = Object.keys(r.mapped_hosts || {}).length;
      const skipped = (r.skipped_hosts || []).length;
      $('discordFixStatus').textContent = active
        ? 'Включён: ' + dnsState + ' · IP ' + (r.selected_ip || '?') + ' · hosts ' + (r.hosts_block ? 'OK' : 'нет') + (r.mode === 'hosts' ? ' · исправлено доменов: ' + mapped + (skipped ? ' · не удалось: ' + skipped : '') : '')
        : 'Выключен. «Лёгкий» правит только hosts для статических доменов; полный добавляет локальный DNS/задачу для динамических хостов (голос/стрим).';
    } catch (e) {
      $('discordFixStatus').textContent = 'Не удалось прочитать состояние: ' + String(e.message || e);
    }
  },

  _discordFixBusy(on) {
    for (const id of ['discordFixScanBtn', 'discordFixEnableBtn', 'discordFixEnableHostsBtn', 'discordFixRotateBtn', 'discordFixDisableBtn']) {
      const el = $(id);
      if (el) el.disabled = !!on;
    }
  },

  async discordFixScan() {
    this._discordFixBusy(true);
    try {
      const r = await apiGet('/discord-fix/scan');
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const box = $('discordFixScanResult');
      const lines = (r.entries || []).slice(0, 12).map(e => e.host + ' -> ' + e.ip);
      box.hidden = false;
      box.textContent = 'Найдено записей Discord/CF в hosts: ' + (r.count || 0) + (lines.length ? '\n' + lines.join('\n') : '') + ((r.count || 0) > lines.length ? '\n…' : '');
      showToast('hosts: найдено ' + (r.count || 0) + ' записей', 'ok');
    } catch (e) {
      showToast('Проверка hosts: ' + String(e.message || e), 'error');
    } finally {
      this._discordFixBusy(false);
      this.discordFixLoad();
    }
  },

  async discordFixEnable(mode = 'full') {
    const light = mode === 'hosts';
    const ok = await Confirm.ask({
      title: light ? 'Включить лёгкий hosts-обход?' : 'Включить полный обход Discord/Cloudflare?',
      text: light
        ? 'Программа проверит статические домены и пропишет в hosts только те, где текущий адрес не работает. Задача автозапуска и локальный DNS не создаются. Динамические c-*.discord.media (голос/стрим) этот режим не покрывает.'
        : 'Будут изменены system hosts, добавлены NRPT-правила и создана задача автозапуска при старте Windows для локального DNS на 127.0.0.1:53. GUI можно закрыть. Это временный обход, не VPN. При блокировке пула IP понадобится WARP/другой маршрут.',
      ok: 'Включить',
    });
    if (!ok) return;
    this._discordFixBusy(true);
    try {
      const r = await apiPost('/discord-fix/enable', { mode: light ? 'hosts' : 'full' });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'Обход включён', 'ok');
    } catch (e) {
      showToast('Не удалось включить: ' + String(e.message || e), 'error');
    } finally {
      this._discordFixBusy(false);
      this.discordFixLoad();
    }
  },

  async youtubeFixLoad() {
    try {
      const r = await apiGet('/youtube-fix/status');
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const active = !!r.enabled;
      $('youtubeFixEnableBtn').hidden = active;
      $('youtubeFixRotateBtn').hidden = !active;
      $('youtubeFixDisableBtn').hidden = !active;
      $('youtubeFixStatus').textContent = active
        ? 'Тест включён: edge ' + (r.selected_ip || '?') + ' · NRPT ' + (r.nrpt_rules || 0) + ' · зона ' + (r.zone || '.googlevideo.com')
        : 'Выключен. Включение поднимет локальный DNS на 127.0.0.1:53 и NRPT-зону .googlevideo.com.';
    } catch (e) {
      $('youtubeFixStatus').textContent = 'Не удалось прочитать состояние: ' + String(e.message || e);
    }
  },

  _youtubeFixBusy(on) {
    for (const id of ['youtubeFixEnableBtn', 'youtubeFixRotateBtn', 'youtubeFixDisableBtn']) {
      const el = $(id);
      if (el) el.disabled = !!on;
    }
  },

  async youtubeFixEnable() {
    const ok = await Confirm.ask({
      title: 'Включить тестовый YouTube GGC worker?',
      text: 'Будет поднят локальный DNS на 127.0.0.1:53 и добавлена NRPT-зона .googlevideo.com. Все A-запросы *.googlevideo.com пойдут на выбранный Google edge. Задачи/автозапуска нет; при выходе из программы режим снимается. Chrome/Edge Secure DNS должен быть выключен. Это тест, не VPN.',
      ok: 'Включить',
    });
    if (!ok) return;
    this._youtubeFixBusy(true);
    try {
      const r = await apiPost('/youtube-fix/enable', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'Тест включён', 'ok');
    } catch (e) {
      showToast('Не удалось включить: ' + String(e.message || e), 'error');
    } finally {
      this._youtubeFixBusy(false);
      this.youtubeFixLoad();
    }
  },

  async youtubeFixRotate() {
    this._youtubeFixBusy(true);
    try {
      const r = await apiPost('/youtube-fix/rotate', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'Edge сменён', 'ok');
    } catch (e) {
      showToast('Не удалось сменить edge: ' + String(e.message || e), 'error');
    } finally {
      this._youtubeFixBusy(false);
      this.youtubeFixLoad();
    }
  },

  async youtubeFixDisable() {
    this._youtubeFixBusy(true);
    try {
      const r = await apiPost('/youtube-fix/disable', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'Тест выключен', 'ok');
    } catch (e) {
      showToast('Не удалось выключить: ' + String(e.message || e), 'error');
    } finally {
      this._youtubeFixBusy(false);
      this.youtubeFixLoad();
    }
  },

  async discordFixRotate() {
    const ok = await Confirm.ask({
      title: 'Сменить рабочий IP?',
      text: 'Будет выбран другой случайный рабочий IP из пула. Discord переподключится к новому адресу.',
      ok: 'Сменить',
    });
    if (!ok) return;
    this._discordFixBusy(true);
    try {
      const r = await apiPost('/discord-fix/rotate', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'IP сменён', 'ok');
    } catch (e) {
      showToast('Не удалось сменить IP: ' + String(e.message || e), 'error');
    } finally {
      this._discordFixBusy(false);
      this.discordFixLoad();
    }
  },

  async discordFixDisable() {
    this._discordFixBusy(true);
    try {
      const r = await apiPost('/discord-fix/disable', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'Обход выключен', 'ok');
    } catch (e) {
      showToast('Не удалось выключить: ' + String(e.message || e), 'error');
    } finally {
      this._discordFixBusy(false);
      this.discordFixLoad();
    }
  },
};
const DNS_PROVIDER_PRESETS = {
  google: { primary: '8.8.8.8', secondary: '8.8.4.4' },
  cloudflare: { primary: '1.1.1.1', secondary: '1.0.0.1' },
  quad9: { primary: '9.9.9.9', secondary: '149.112.112.112' },
  comss: { primary: '212.109.221.20', secondary: '212.109.195.93' },
};

const DnsPanel = {
  _bound: false,
  _busy: false,
  _canReset: false,

  onShow() {
    if (!this._bound) {
      this._bound = true;
      $('dnsApplyBtn').addEventListener('click', () => this.apply());
      $('dnsResetBtn').addEventListener('click', () => this.reset());
      $('dnsMainProvider').addEventListener('change', e => this._fillProvider('main', e.target.value));
      $('dnsReserveProvider').addEventListener('change', e => this._fillProvider('reserve', e.target.value));
      for (const id of ['dnsMainPrimary', 'dnsMainSecondary', 'dnsReservePrimary', 'dnsReserveSecondary']) {
        $(id).addEventListener('input', () => this._syncProviderSelects());
      }
    }
    this.load();
  },

  async load() {
    try {
      const r = await apiGet('/dns/status');
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      this._render(r);
    } catch (e) {
      $('dnsCurrent').textContent = 'Не удалось прочитать DNS: ' + String(e.message || e);
      $('dnsActive').textContent = '';
      const resetBtn = $('dnsResetBtn');
      if (resetBtn) resetBtn.disabled = true;
    }
  },

  _render(r) {
    const st = r.state || {};
    const cur = (st.servers || []).join(', ');
    if (st.ok) {
      const adapter = st.adapter ? st.adapter + ': ' : '';
      $('dnsCurrent').textContent = adapter + (cur || 'авто / DHCP') +
        (st.dhcp ? ' (DHCP)' : ' (вручную)');
    } else {
      $('dnsCurrent').textContent = 'DNS не прочитан: ' + (st.error || 'нет активного адаптера');
    }
    const active = r.active || 'unknown';
    const labels = { main: 'текущий: Основной', reserve: 'текущий: Резервный',
                     custom: 'текущий DNS не совпадает с профилями', system: 'текущий: системный',
                     unknown: '' };
    $('dnsActive').textContent = labels[active] || '';
    const profiles = r.profiles || {};
    this._setProfile('main', profiles.main);
    this._setProfile('reserve', profiles.reserve);
    if (active === 'main' || active === 'reserve') $('dnsProfile').value = active;
    const resetBtn = $('dnsResetBtn');
    this._canReset = !!r.can_reset;
    if (resetBtn) {
      resetBtn.disabled = !this._canReset;
      resetBtn.title = this._canReset
        ? 'Вернуть DNS, сохранённый перед первым применением профиля'
        : 'Нет сохранённого исходного DNS: сначала примените профиль';
    }
    this._syncProviderSelects();
  },

  _setProfile(key, p) {
    if (!p) return;
    const cap = key === 'main' ? 'Main' : 'Reserve';
    $('dns' + cap + 'Primary').value = p.primary || '';
    $('dns' + cap + 'Secondary').value = p.secondary || '';
  },

  _fillProvider(key, provider) {
    const p = DNS_PROVIDER_PRESETS[provider];
    if (!p) return;
    const cap = key === 'main' ? 'Main' : 'Reserve';
    $('dns' + cap + 'Primary').value = p.primary;
    $('dns' + cap + 'Secondary').value = p.secondary;
  },

  _syncProviderSelects() {
    for (const [key, cap] of [['main', 'Main'], ['reserve', 'Reserve']]) {
      const p = $('dns' + cap + 'Primary').value.trim().toLowerCase();
      const s = $('dns' + cap + 'Secondary').value.trim().toLowerCase();
      let match = 'custom';
      for (const [name, preset] of Object.entries(DNS_PROVIDER_PRESETS)) {
        if (p === preset.primary && s === preset.secondary) match = name;
      }
      $('dns' + cap + 'Provider').value = match;
    }
  },

  _profiles() {
    return {
      main: { primary: $('dnsMainPrimary').value.trim(), secondary: $('dnsMainSecondary').value.trim() },
      reserve: { primary: $('dnsReservePrimary').value.trim(), secondary: $('dnsReserveSecondary').value.trim() },
    };
  },

  async apply() {
    if (this._busy) return;
    this._busy = true;
    const btn = $('dnsApplyBtn');
    btn.disabled = true;
    btn.textContent = 'Применяю…';
    try {
      const r = await apiPost('/dns/apply', {
        profile: $('dnsProfile').value,
        profiles: this._profiles(),
      });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast('DNS применён', 'ok');
      this._render(r);
    } catch (e) {
      showToast('DNS не изменён: ' + String(e.message || e), 'error');
    } finally {
      this._busy = false;
      btn.disabled = false;
      btn.textContent = 'Применить';
    }
  },

  async reset() {
    if (this._busy) return;
    this._busy = true;
    const btn = $('dnsResetBtn');
    btn.disabled = true;
    btn.textContent = 'Возвращаю…';
    try {
      const r = await apiPost('/dns/reset', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast('DNS возвращён к исходному', 'ok');
      this._render(r);
    } catch (e) {
      showToast('Не удалось вернуть DNS: ' + String(e.message || e), 'error');
    } finally {
      this._busy = false;
      btn.disabled = !this._canReset;
      btn.textContent = 'Вернуть системный DNS';
    }
  },
};
