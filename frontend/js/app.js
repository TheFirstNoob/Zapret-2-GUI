/**
 * Zapret2 Manager — frontend.
 * Vanilla JS, single script. Backend contract: /api/* polling.
 */

'use strict';

const APP_TOKEN = window.APP_TOKEN || '__APP_TOKEN__';
const SCORE_OK = 80;
const SCORE_MID = 40;

let PROFILES = [];

// token-инъекция для /api/*
const _origFetch = window.fetch;
window.fetch = function (url, opts) {
  opts = opts || {};
  if (typeof url === 'string' && url.startsWith('/api/')) {
    opts.headers = Object.assign({ 'X-App-Token': APP_TOKEN }, opts.headers || {});
  }
  return _origFetch(url, opts);
};

window.onerror = function (msg, url, line) {
  console.error('JS ERROR line ' + line + ': ' + msg);
};

// ── utils ──

function $(id) { return document.getElementById(id); }

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function formatTime(ms) {
  const n = parseFloat(ms) || 0;
  return n < 1000 ? n.toFixed(0) + 'ms' : (n / 1000).toFixed(1) + 's';
}

async function apiGet(path) {
  const r = await fetch('/api' + path);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch('/api' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

let _toastTimer = null;
function showToast(msg, type) {
  const t = $('toast');
  t.textContent = msg;
  t.className = 'toast' + (type ? ' ' + type : '');
  t.hidden = false;
  requestAnimationFrame(() => { t.style.opacity = '1'; });
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    t.style.opacity = '0';
    setTimeout(() => { t.hidden = true; }, 250);
  }, 3600);
}

function rateClass(v) {
  return v >= SCORE_OK ? 'st-ok' : v >= SCORE_MID ? 'st-warn' : 'st-err';
}

// ── глобальный статус (чип в сайдбаре + Главная) ──

const Status = {
  timer: null,
  svcTimer: null,
  last: null,          // /api/status ответ
  svc: null,           // /api/service/status ответ

  start() {
    this.refresh();
    this.refreshService();
    this.timer = setInterval(() => this.refresh(), 4000);
    this.svcTimer = setInterval(() => this.refreshService(), 9000);
  },

  async refresh() {
    try {
      const data = await apiGet('/status');
      this.last = data;
      this.render();
    } catch (e) {
      $('protDot').className = 'dot dot-unknown';
      $('protText').textContent = 'нет связи…';
    }
  },

  async refreshService() {
    try { this.svc = await apiGet('/service/status'); }
    catch (e) { this.svc = null; }
    this.render();
    if (App.currentPage === 'main') MainPage.renderServiceLine();
  },

  render() {
    const d = this.last;
    if (!d) return;
    const z2 = d.zapret || {}, z1 = d.zapret1 || {}, svc = this.svc;
    const dot = $('protDot'), txt = $('protText'), sub = $('protSub');

    let state; // 'ok' | 'off' | 'warn' | 'err'
    if (z2.running && z1.running) state = 'err';
    else if (z2.running) state = 'ok';
    else if (z1.running) state = 'warn';
    else state = 'off';

    dot.className = 'dot dot-' + state;
    const chip = $('protChip');
    chip.className = 'prot-chip state-' + state;
    if (state === 'ok') {
      txt.textContent = 'Обход работает';
      sub.textContent = (svc && svc.running) ? 'через службу' : 'PID ' + (z2.pid || '—');
    } else if (state === 'warn') {
      txt.textContent = 'Работает Zapret 1';
      sub.textContent = 'Zapret 2 остановлен';
    } else if (state === 'err') {
      txt.textContent = 'Конфликт Z1 + Z2';
      sub.textContent = 'обход может не работать';
    } else {
      txt.textContent = 'Обход выключен';
      sub.textContent = (svc && svc.installed && !svc.running) ? 'служба остановлена' : '';
    }
    MainPage.renderStatus(d);
  },
};

// ── router ──

const App = {
  currentPage: 'main',
  pages: ['main', 'tester', 'lists', 'diagnostics'],

  async init() {
    this.bindNav();
    this.handleHash();
    window.addEventListener('hashchange', () => this.handleHash());
    this.loadVersion();
    this.checkUpdate();
    try {
      const data = await apiGet('/profiles');
      PROFILES = (data.profiles || []).map(p => p.name);
    } catch (e) { PROFILES = ['default']; }
    Status.start();
    if (this.currentPage === 'main') MainPage.onShow();
  },

  bindNav() {
    document.querySelectorAll('.nav-link').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        window.location.hash = link.dataset.page;
      });
    });
  },

  handleHash() {
    const hash = window.location.hash.replace('#', '') || 'main';
    if (!this.pages.includes(hash)) { window.location.hash = this.currentPage; return; }
    this.currentPage = hash;
    document.querySelectorAll('.nav-link').forEach(l =>
      l.classList.toggle('active', l.dataset.page === hash));
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    $('page-' + hash).classList.add('active');
    const titles = { main: 'Главная', tester: 'Подбор стратегии', lists: 'Списки', diagnostics: 'Проверка системы' };
    $('pageTitle').textContent = titles[hash];
    if (hash === 'main') MainPage.onShow();
    if (hash === 'lists') ListsPage.onShow();
    if (hash === 'diagnostics') DiagnosticsPage.onShow();
    if (hash === 'tester') TesterPage.onShow();
  },

  async loadVersion() {
    try {
      const d = await apiGet('/version');
      if (d.version) $('appVersion').textContent = d.version;
    } catch (e) { /* ignore */ }
  },

  async checkUpdate() {
    try {
      const r = await apiGet('/update-check');
      if (r.available && r.latest) {
        $('updateVersion').textContent = r.latest;
        $('updateLink').href = r.url || '#';
        $('updateMirrorLink').href = r.mirror_url || '#';
        $('updateBanner').hidden = false;
      }
    } catch (e) { /* silent */ }
  },
};

// ══════════════════════════ ГЛАВНАЯ ══════════════════════════

const MainPage = {
  _busy: false,
  _z2Running: false,
  _z2Strategy: '',
  _loaded: false,

  onShow() {
    if (!this._loaded) {
      this._loaded = true;
      this.loadConfig();
      this.bind();
      MainPage.renderServiceLine();
    }
    if (Status.last) this.renderStatus(Status.last);
  },

  bind() {
    $('btnZ2Toggle').addEventListener('click', () => this.toggleZ2());
    $('btnStopZ1Now').addEventListener('click', () => this.stopZ1());
    $('btnApplyToggles').addEventListener('click', () => this.restartZapret());
    $('svcAutoSwitch').addEventListener('change', (e) => this.setSvcAuto(e.target.checked));
    $('btnZ1SaveDir').addEventListener('click', () => this.saveZ1Dir());
    $('btnZ1Toggle').addEventListener('click', () => this.toggleZ1());
    $('updateBannerClose').addEventListener('click', () => { $('updateBanner').hidden = true; });
    $('btnSvcStart').addEventListener('click', () => this.startSvcNow());

    ['toggleGameFilter', 'toggleAutoHostlist', 'toggleIpFilter',
      'toggleDiscordVoice', 'toggleWinws2Debug'].forEach(id => {
      $(id).addEventListener('change', () => this.saveToggles());
    });
  },

  async loadConfig() {
    try {
      const r = await apiGet('/config');
      const c = r.config || {};
      $('toggleGameFilter').value = c.game_filter_mode || 'off';
      $('toggleAutoHostlist').checked = !!c.autohostlist;
      $('toggleIpFilter').checked = !!c.ipset_catchall;
      $('toggleDiscordVoice').checked = !!c.discord_voice;
      $('toggleWinws2Debug').checked = !!c.winws2_debug;
      $('z1DirPath').value = c.zapret1_dir || '';
      if (c.last_profile) {
        this._savedProfile = c.last_profile;
        const sel = $('strategySelect');
        if ([...sel.options].some(o => o.value === c.last_profile)) sel.value = c.last_profile;
      }
      if (c.zapret1_last_strategy) this._z1SavedStrategy = c.zapret1_last_strategy;
      if (c.zapret1_dir) this.scanZ1Strategies();
    } catch (e) { /* ignore */ }
  },

  populateProfiles(list) {
    if (!list || !list.length) return;
    const sig = list.join(',');
    if (sig === this._profilesSig) return;
    this._profilesSig = sig;
    const sel = $('strategySelect');
    const cur = sel.value || this._savedProfile || '';
    sel.innerHTML = '';
    for (const p of list) {
      const o = document.createElement('option');
      o.value = p; o.textContent = p;
      sel.appendChild(o);
    }
    if (cur && list.includes(cur)) sel.value = cur;
    else if (list.includes('default')) sel.value = 'default';
    sel.onchange = () => {
      if (sel.value) apiPost('/config', { last_profile: sel.value }).catch(() => {});
    };
  },

  renderStatus(d) {
    if (!d) return;
    const z2 = d.zapret || {}, z1 = d.zapret1 || {};
    const st = $('z2State');
    const badge = st.querySelector('.dot');
    const text = st.querySelector('.state-text');
    const conflict = z2.running && z1.running;

    // статусные рамки панелей: ok / warn (внимание) / err (конфликт)
    const z2p = $('z2Panel');
    z2p.classList.remove('is-ok', 'is-warn', 'is-err');
    if (conflict) z2p.classList.add('is-err');
    else if (z2.running) z2p.classList.add('is-ok');
    else if (z1.running) z2p.classList.add('is-warn');
    const z1p = $('z1Panel');
    z1p.classList.remove('is-ok', 'is-warn', 'is-err');
    if (z1.running && z2.running) z1p.classList.add('is-err');
    else if (z1.running) z1p.classList.add('is-warn');
    if (z2.running) {
      badge.className = 'dot ' + (conflict ? 'dot-warn' : 'dot-ok');
      text.className = 'state-text ' + (conflict ? 'st-warn' : 'st-ok');
      text.textContent = conflict ? 'Работает (конфликт с Zapret 1)' : 'Работает';
    } else if (z1.running) {
      badge.className = 'dot dot-warn';
      text.className = 'state-text st-warn';
      text.textContent = 'Выключен (работает Zapret 1)';
    } else {
      badge.className = 'dot dot-off';
      text.className = 'state-text st-mute';
      text.textContent = 'Выключен';
    }
    $('z2Meta').textContent = z2.running
      ? 'PID ' + (z2.pid || '—') + ' · стратегия «' + (z2.strategy || '?') + '»'
      : '';

    this._z2Running = z2.running;
    this._z2Strategy = z2.strategy || '';
    const btn = $('btnZ2Toggle');
    if (!this._busy) {
      btn.textContent = z2.running ? 'Остановить' : 'Запустить';
      btn.classList.toggle('btn-primary', !z2.running);
      btn.disabled = false;
    }

    $('conflictBanner').hidden = !(z2.running && z1.running);
    $('togglesOverlay').hidden = !z1.running;

    // Zapret 1 — единый стиль статуса с Zapret 2 (слова и цвет текста)
    const zs = $('z1State');
    const z1Text = zs.querySelector('.state-text');
    const z1Conflict = z1.running && z2.running;
    zs.querySelector('.dot').className = 'dot ' + (z1Conflict ? 'dot-warn' : z1.running ? 'dot-ok' : 'dot-off');
    z1Text.className = 'state-text ' + (z1Conflict ? 'st-warn' : z1.running ? 'st-ok' : 'st-mute');
    z1Text.textContent = z1.running ? 'Работает' : 'Выключен';
    const z1btn = $('btnZ1Toggle');
    z1btn.textContent = z1.running ? 'Остановить' : 'Запустить';
    z1btn.classList.toggle('btn-primary', !z1.running);

    // перезапуск по изменённым тогглам — только когда что-то изменено и запущено
    this._updateApplyHint();
    this.populateProfiles(d.profiles || []);
  },

  renderServiceLine() {
    const sw = $('svcAutoSwitch');
    const svc = Status.svc;
    if (!svc) return;
    if (!this._svcBusy) sw.checked = svc.installed;
    $('btnSvcStart').hidden = !(svc.installed && !svc.running);
    $('svcStatusText').textContent = !svc.installed ? ''
      : (svc.running ? 'установлена · запущена' : 'установлена · остановлена');
  },

  async startSvcNow() {
    const btn = $('btnSvcStart');
    btn.disabled = true;
    try {
      const r = await apiPost('/service/start', {});
      showToast(r.status === 'ok' ? 'Служба запущена' : ('Ошибка: ' + (r.message || '')),
        r.status === 'ok' ? 'ok' : 'error');
    } catch (e) {
      showToast('Ошибка: ' + e.message, 'error');
    }
    btn.disabled = false;
    Status.refreshService();
    Status.refresh();
  },

  _collectToggles() {
    return {
      game_filter_mode: $('toggleGameFilter').value,
      discord_voice: $('toggleDiscordVoice').checked,
      winws2_debug: $('toggleWinws2Debug').checked,
      autohostlist: $('toggleAutoHostlist').checked,
      ipset_catchall: $('toggleIpFilter').checked,
    };
  },

  async saveToggles() {
    const t = this._collectToggles();
    try {
      await apiPost('/config', t);
      if (this._z2Running) showToast('Сохранено. Перезапустите, чтобы применить', 'warn');
      else showToast('Сохранено', 'ok');
    } catch (e) {
      showToast('Не удалось сохранить: ' + e.message, 'error');
    }
    this._updateApplyHint();
  },

  _updateApplyHint() {
    const btn = $('btnApplyToggles');
    const hint = $('applyTogglesHint');
    if (this._z2Running) {
      btn.hidden = false;
      hint.textContent = 'Параметры применяются после перезапуска';
    } else {
      btn.hidden = true;
      hint.textContent = '';
    }
  },

  async toggleZ2() {
    if (this._z2Running) return this.stop();
    const profile = $('strategySelect').value;
    if (!profile) { showToast('Выберите стратегию', 'warn'); return; }
    this._setBusy(true);
    try {
      await apiPost('/config', Object.assign({ last_profile: profile }, this._collectToggles()));
      const r = await apiPost('/start', { profile });
      if (r.status === 'ok') showToast('Обход запущен: ' + profile, 'ok');
      else showToast('Не удалось запустить: ' + (r.message || 'ошибка'), 'error');
    } catch (e) {
      showToast('Ошибка запуска: ' + e.message, 'error');
    }
    this._setBusy(false);
    Status.refresh();
  },

  async stop() {
    this._setBusy(true);
    try {
      const r = await apiPost('/stop', {});
      showToast(r.status === 'ok' ? 'Обход остановлен' : ('Ошибка: ' + r.message),
        r.status === 'ok' ? 'ok' : 'error');
    } catch (e) { showToast('Ошибка: ' + e.message, 'error'); }
    this._setBusy(false);
    Status.refresh();
  },

  async restartZapret() {
    const strategy = this._z2Strategy || $('strategySelect').value;
    if (!strategy) return;
    const btn = $('btnApplyToggles');
    btn.disabled = true;
    try {
      await apiPost('/config', this._collectToggles());
      await apiPost('/stop', {});
      await new Promise(r => setTimeout(r, 1200));
      const r = await apiPost('/start', { profile: strategy });
      showToast(r.status === 'ok' ? 'Перезапущено: ' + strategy : ('Ошибка: ' + r.message),
        r.status === 'ok' ? 'ok' : 'error');
    } catch (e) {
      showToast('Ошибка перезапуска: ' + e.message, 'error');
    }
    btn.disabled = false;
    Status.refresh();
  },

  _setBusy(b) {
    this._busy = b;
    $('btnZ2Toggle').disabled = b;
    $('svcAutoSwitch').disabled = b;
  },

  async setSvcAuto(on) {
    const sw = $('svcAutoSwitch');
    this._svcBusy = true;
    sw.disabled = true;
    try {
      if (on) {
        if (!Status.svc || !Status.svc.installed) {
          const t = this._collectToggles();
          const r = await apiPost('/service/install', {
            profile: $('strategySelect').value,
            game_filter: t.game_filter_mode, discord_voice: t.discord_voice,
            debug: t.winws2_debug, autohostlist: t.autohostlist,
            ipset_catchall: t.ipset_catchall,
          });
          if (r.status !== 'ok') throw new Error(r.message || 'не установлено');
        }
        const r = await apiPost('/service/start', {});
        if (r.status !== 'ok') throw new Error(r.message || 'не запущена');
        showToast('Служба включена — обход работает без программы', 'ok');
      } else {
        if (Status.svc && Status.svc.running) await apiPost('/service/stop', {}).catch(() => {});
        const r = await apiPost('/service/remove', {});
        if (r.status !== 'ok') throw new Error(r.message || 'не удалена');
        showToast('Служба удалена', 'ok');
      }
    } catch (e) {
      sw.checked = !on;
      showToast('Со службой не вышло: ' + e.message, 'error');
    }
    this._svcBusy = false;
    sw.disabled = false;
    Status.refreshService();
    Status.refresh();
  },

  // ── Zapret 1 ──

  async saveZ1Dir() {
    const dir = $('z1DirPath').value.trim();
    if (!dir) { showToast('Укажите папку Zapret 1', 'warn'); return; }
    try {
      const r = await apiPost('/zapret1/save-dir', { path: dir });
      if (r.status === 'ok') { showToast('Путь сохранён', 'ok'); this.scanZ1Strategies(); }
      else showToast(r.message || 'Ошибка', 'error');
    } catch (e) { showToast('Ошибка: ' + e.message, 'error'); }
  },

  async scanZ1Strategies() {
    const sel = $('z1StrategySelect');
    sel.disabled = true;
    sel.innerHTML = '<option>сканирование…</option>';
    try {
      const r = await apiGet('/zapret1/strategies');
      const strs = r.strategies || [];
      sel.innerHTML = '';
      if (!strs.length) {
        sel.innerHTML = '<option value="">— в папке нет .bat —</option>';
        return;
      }
      sel.disabled = false;
      for (const s of strs) {
        const o = document.createElement('option');
        o.value = s.name; o.textContent = s.name + '.bat';
        sel.appendChild(o);
      }
      if (this._z1SavedStrategy && strs.some(s => s.name === this._z1SavedStrategy)) {
        sel.value = this._z1SavedStrategy;
      }
    } catch (e) {
      sel.innerHTML = '<option value="">— ошибка сканирования —</option>';
    }
  },

  async toggleZ1() {
    const running = Status.last && Status.last.zapret1 && Status.last.zapret1.running;
    try {
      if (running) {
        const r = await apiPost('/zapret1/stop', {});
        showToast(r.status === 'ok' ? 'Zapret 1 остановлен' : ('Ошибка: ' + r.message),
          r.status === 'ok' ? 'ok' : 'error');
      } else {
        const strategy = $('z1StrategySelect').value;
        if (!strategy) { showToast('Выберите стратегию Zapret 1', 'warn'); return; }
        const r = await apiPost('/zapret1/start', { strategy });
        showToast(r.status === 'ok' ? ('Zapret 1 запущен: ' + strategy) : ('Ошибка: ' + (r.message || '')),
          r.status === 'ok' ? 'ok' : 'error');
      }
    } catch (e) { showToast('Ошибка: ' + e.message, 'error'); }
    Status.refresh();
  },

  async stopZ1() { await this.toggleZ1(); },
};

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
    const btn = $('diagRunBtn');
    btn.disabled = true;
    btn.textContent = 'Проверяю…';
    const results = $('diagResults');
    $('diagCopyBtn').hidden = true;
    $('diagSummary').hidden = true;
    const t0 = Date.now();
    results.innerHTML = '<div class="empty-note">Выполняется проверка: <b id="diagCurrent">…</b> · <span class="mono" id="diagTimer">0</span> с</div>';
    const timer = setInterval(() => {
      const el = $('diagTimer');
      if (el) el.textContent = Math.round((Date.now() - t0) / 1000);
    }, 1000);
    try {
      const started = await apiPost('/diagnose/action', {});
      if (started.status !== 'ok') throw new Error(started.message || 'ошибка');
      let report = null;
      while (report === null) {
        await new Promise(res => setTimeout(res, 300));
        const st = await apiGet('/diagnose/status');
        if (st.error) throw new Error(st.error);
        const cur = $('diagCurrent');
        if (cur && st.progress) cur.textContent = st.progress;
        if (!st.running) report = st.report;
      }
      if (!report) throw new Error('нет результата');
      localStorage.setItem('z2_diag_done', '1');
      const note = $('diagDoneNote');
      if (note) note.hidden = false;
      this.render(report);
    } catch (e) {
      results.innerHTML = '<div class="empty-note st-err">Ошибка диагностики: ' + escapeHtml(String(e.message || e)) + '</div>';
    }
    clearInterval(timer);
    btn.disabled = false;
    btn.textContent = 'Проверить';
  },

  render(report) {
    const icons = { ok: 'ok', warn: 'warn', fail: 'err', skip: 'idle' };
    const s = report.summary || {};
    $('diagSummary').hidden = false;
    $('diagSummary').innerHTML =
      (s.ok ? `<span class="st-ok">Проверено: ${s.ok}</span>` : '') +
      (s.warn ? `<span class="st-warn">Внимание: ${s.warn}</span>` : '') +
      (s.fail ? `<span class="st-err">Ошибки: ${s.fail}</span>` : '') +
      (s.skip ? `<span class="st-mute">Пропущено: ${s.skip}</span>` : '') +
      (report.elapsed_sec != null ? `<span class="st-mute">заняло ${report.elapsed_sec} с</span>` : '');

    const rows = (report.checks || []).map(c => `
      <tr class="chk-row-${c.status}">
        <td style="width:14px"><span class="dot dot-${icons[c.status] || 'idle'}"></span></td>
        <td class="check-name">${escapeHtml(c.name)}</td>
        <td class="check-detail"${c.tech ? ` title="${escapeHtml(c.tech)}"` : ''}>${escapeHtml(c.detail || '')}</td>
      </tr>`).join('');
    let html = `<table class="check-table"><tbody>${rows || '<tr><td class="empty-note">Нет результатов</td></tr>'}</tbody></table>`;

    if ((s.fail || 0) > 0) {
      html += `<div class="notice notice-warn" style="margin-top:10px">
        <span>Есть проблемы. Если нужно подобрать стратегию под ваш интернет — начните подбор.</span>
        <button class="btn btn-sm" onclick="location.hash='tester'">Начать подбор</button>
      </div>`;
    }
    $('diagResults').innerHTML = html;

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

// ══════════════════════════ СПИСКИ ══════════════════════════

const ListsPage = {
  _loaded: false,
  saved: {},

  editors: {
    domInc: { api: '/include-list', kind: 'domain' },
    domExc: { api: '/exclude-list', kind: 'domain' },
    ipInc: { api: '/ipset-include-list', kind: 'cidr' },
    ipExc: { api: '/ipset-exclude-list', kind: 'cidr' },
  },

  onShow() {
    if (!this._loaded) {
      this._loaded = true;
      document.querySelectorAll('[data-save]').forEach(btn =>
        btn.addEventListener('click', () => this.save(btn.dataset.save)));
      Object.keys(this.editors).forEach(key => {
        const ta = $(key + 'Textarea');
        ta.addEventListener('input', () => this.validate(key));
        ta.addEventListener('scroll', () => this._syncNums(key));
        this.load(key);
      });
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
    return dirty;
  },

  validate(key) {
    this._syncNums(key);
    this._dirtyCheck(key);
    const e = this.editors[key];
    const lines = $(key + 'Textarea').value.split('\n');
    let ok = 0;
    const bad = [];
    lines.forEach((line, i) => {
      const s = line.trim();
      if (!s || s.startsWith('#')) return;
      if (e.kind === 'domain' ? this._validDomain(s) : this._validCidr(s)) ok++;
      else bad.push(i + 1);
    });
    const cnt = $(key + 'Count');
    if (cnt) cnt.textContent = String(ok);
    const box = $(key + 'Valid');
    if (bad.length) {
      box.innerHTML = `<span class="bad">строки с ошибкой: ${bad.slice(0, 12).join(', ')}${bad.length > 12 ? '…' : ''} — сохранение заблокировано</span>`;
    } else if (this._dirtyCheck(key)) {
      box.innerHTML = '<span class="dirty-note">изменения не сохранены — нажмите «Сохранить»</span>';
    } else if (ok === 0) {
      box.textContent = 'пусто — список ни на что не влияет';
    } else {
      box.textContent = '';
    }
    $(key + 'Result').textContent = '';
    return bad.length === 0;
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
    nums.textContent = Array.from({ length: n }, (_, i) => i + 1).join('\n');
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
      showToast('Исправьте ошибочные строки — список не сохранён', 'error');
      return;
    }
    const e = this.editors[key];
    const el = $(key + 'Result');
    el.textContent = 'Сохранение…';
    try {
      const r = await apiPost(e.api, { content: $(key + 'Textarea').value });
      if (r.status === 'ok') {
        el.textContent = 'сохранено';
        this.saved[key] = $(key + 'Textarea').value;
        showToast('Список сохранён', 'ok');
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

// ══════════════════════════ ТЕСТЕР ══════════════════════════

const TesterPage = {
  state: {
    cdnTest: false, extendedTest: false, collectLogs: false,
    vpnActive: false,
    currentResults: null, nakedResults: null, phase2Results: null,
    fullAnalysisResults: null,
    collectFormData: null, collectBatFile: null,
    testStartTime: 0, elapsedInterval: null,
    rows: null, currentKey: null, knownResults: 0,
  },

  onShow() {
    if (!this._bound) {
      this._bound = true;
      $('btnStartTest').addEventListener('click', () => this.startTest());
      $('btnDiagCheck').addEventListener('click', () => { location.hash = 'diagnostics'; });
      $('btnCancelTest').addEventListener('click', () => this.cancelTest());
      if (localStorage.getItem('z2_diag_done')) $('diagDoneNote').hidden = false;
      this.bindModals();
    }
  },

  // ── таблица стратегий ──

  _label(key) {
    if (key === '__naked__') return 'Без защиты (базовый уровень)';
    if (key === '__current__') return 'Zapret 1 (текущий)';
    return key;
  },

  _resetTable() {
    $('stratTbody').innerHTML =
      '<tr class="strat-empty"><td colspan="6">Ожидание первых результатов…</td></tr>';
    this.state.rows = new Map();
    this.state.currentKey = null;
  },

  _rowFor(profileKey) {
    const key = (profileKey || '__naked__').trim() || '__naked__';
    let r = this.state.rows.get(key);
    if (r) return r;
    const empty = $('stratTbody').querySelector('.strat-empty');
    if (empty) empty.remove();

    const tr = document.createElement('tr');
    tr.className = 'strat-row expandable';
    tr.innerHTML =
      `<td class="col-strat"><span class="strat-name">${escapeHtml(this._label(key))}</span></td>` +
      '<td class="col-state"><span class="strat-state"><span class="dot dot-idle"></span><span class="st-text">в очереди</span></span></td>' +
      '<td class="col-rate">—</td><td class="col-mini">—</td><td class="col-mini">—</td><td class="col-rate">0/0</td>';

    const detail = document.createElement('tr');
    detail.className = 'strat-detail';
    detail.hidden = true;
    detail.innerHTML = '<td colspan="6"><table class="host-table"><tbody></tbody></table></td>';

    $('stratTbody').appendChild(tr);
    $('stratTbody').appendChild(detail);
    if (key === '__naked__' || key === '__current__') tr.classList.add('row-baseline');

    tr.addEventListener('click', () => {
      detail.hidden = !detail.hidden;
    });

    r = {
      key, tr, detail,
      tbody: detail.querySelector('tbody'),
      stateDot: tr.querySelector('.dot'),
      stateText: tr.querySelector('.st-text'),
      rateCell: tr.children[2],
      discordCell: tr.children[3],
      ytCell: tr.children[4],
      hostsCell: tr.children[5],
      hosts: new Map(), ok: 0, total: 0, netOk: 0, netTotal: 0,
    };
    this.state.rows.set(key, r);
    return r;
  },

  _setCurrent(key) {
    this._rowFor(key);
    if (this.state.currentKey && this.state.currentKey !== key) {
      const prev = this.state.rows.get(this.state.currentKey);
      if (prev) { prev.tr.classList.remove('is-current'); prev.detail.hidden = true; }
    }
    this.state.currentKey = key;
    const row = this.state.rows.get(key);
    row.tr.classList.add('is-current');
    row.stateDot.className = 'dot dot-warn';
    row.stateText.textContent = 'тестируется…';
    row.detail.hidden = false;
  },

  _finishRow(key) {
    const row = this.state.rows.get(key);
    if (!row) return;
    row.tr.classList.remove('is-current');
    const rate = (row.netTotal || row.total)
      ? (row.netTotal ? row.netOk / row.netTotal : row.ok / row.total) * 100 : 0;
    row.stateDot.className = 'dot ' + (rate >= SCORE_OK ? 'dot-ok' : rate >= SCORE_MID ? 'dot-warn' : 'dot-err');
    row.stateText.textContent = 'готово';
    row.tr.classList.remove('st-good', 'st-mid', 'st-bad');
    row.tr.classList.add(rate >= SCORE_OK ? 'st-good' : rate >= SCORE_MID ? 'st-mid' : 'st-bad');
    row.detail.hidden = true;
    if (this.state.currentKey === key) this.state.currentKey = null;
  },

  _addHostRow: (function (processFn, delayMs) {
    let queue = [], timer = null;
    return function (item) {
      queue.push(item);
      if (!timer) timer = setTimeout(() => {
        const batch = queue; queue = []; timer = null;
        processFn(batch);
      }, delayMs);
    };
  })(function (batch) { for (const b of batch) TesterPage._addHostImmediate(b); }, 90),

  _addHostImmediate(data) {
    const row = this._rowFor(data.profile);
    const mapKey = (data.domain || '') + '|' + (data.test_type || '');
    const isOk = data.status === 'OK' || data.status === 'OK_BLOCKED';
    const isPing = data.test_type === 'ping';
    let h = row.hosts.get(mapKey);
    const wasOk = h ? h.ok : false;
    if (!h) {
      h = { tr: document.createElement('tr'), ok: false };
      h.tr.innerHTML =
        '<td style="width:16px"></td>' +
        `<td class="h-domain" style="width:26%">${escapeHtml(data.domain || '?')}${data.cdn_provider ? `<span class="badge-cdn">${escapeHtml(data.cdn_provider)}</span>` : ''}</td>` +
        `<td style="width:9%" class="h-type"></td>` +
        `<td style="width:9%" class="h-code"></td>` +
        `<td style="width:9%" class="h-time"></td>` +
        '<td class="h-err"></td>';
      row.tbody.appendChild(h.tr);
      row.total++;
      if (!isPing) row.netTotal++;
    }
    h.ok = isOk;
    // считаем «доступность» и «хосты» вживую (сеть, без пингов — как финальный network_rate)
    if (isOk && !wasOk) { row.ok++; if (!isPing) row.netOk++; }
    if (!isOk && wasOk) { row.ok--; if (!isPing) row.netOk--; }
    row.hostsCell.textContent = row.netOk + '/' + row.netTotal;
    if (row.netTotal) {
      const rate = row.netOk / row.netTotal * 100;
      row.rateCell.innerHTML = `<span class="${rateClass(rate)}">${rate.toFixed(0)}%</span>`;
    }
    h.tr.className = isOk ? 'hrow-ok'
      : (data.status === 'TIMEOUT' || data.status === 'BLOCKED' || data.status === 'FAIL'
        ? 'hrow-err' : 'hrow-warn');
    const stIcon = isOk ? '<span class="st-ok">✓</span>'
      : data.status === 'TIMEOUT' || data.status === 'BLOCKED' || data.status === 'FAIL'
        ? '<span class="st-err">✗</span>'
        : '<span class="st-warn">•</span>';
    const cells = h.tr.children;
    cells[0].innerHTML = stIcon;
    cells[2].textContent = data.test_type || '';
    cells[3].textContent = data.status_code || (data.status === 'TCP16_20' || data.status === 'DPI_DROP' ? 'DPI' : '');
    cells[4].textContent = data.time_ms != null ? formatTime(data.time_ms) : '';
    cells[5].textContent = data.error || '';
    row.hosts.set(mapKey, h);
    if (data.domain === 'discord.com' || (data.domain === 'gateway.discord.gg' && !row._discord)) {
      row._discord = true;
      row.discordCell.innerHTML = isOk ? '<span class="st-ok">✓</span>' : '<span class="st-err">✗</span>';
    }
    if (data.domain === 'www.youtube.com' && !row._yt) {
      row._yt = true;
      row.ytCell.innerHTML = isOk ? '<span class="st-ok">✓</span>' : '<span class="st-err">✗</span>';
    }
  },

  _handleProgressMessage(msg) {
    if (!msg) return;
    let m = msg.match(/^Голый тест: (\d+)\/(\d+) доступно$/);
    if (m) {
      const row = this.state.rows.get('__naked__');
      if (row) {
        const rate = +m[1] / +m[2] * 100;
        row.rateCell.innerHTML = `<span class="${rateClass(rate)}">${Math.round(rate)}%</span>`;
        row.hostsCell.textContent = m[1] + '/' + m[2];
      }
      this._finishRow('__naked__');
      return;
    }
    m = msg.match(/^Тестируем стратегию (.+?) \(\d+\/\d+\)\.\.\.$/) ||
            msg.match(/^Тестируем собранную стратегию (.+?)\.\.\.$/) ||
            msg.match(/^Голый тест.*$/);
    if (m) {
      const key = /^Голый/.test(msg) ? '__naked__' : m[1];
      this._setCurrent(key);
      $('testCurrentPhase').textContent = /^Голый/.test(msg)
        ? 'Базовый уровень: проверяем без защиты'
        : 'Тестирую стратегию: ' + key;
      return;
    }
    m = msg.match(/^Стратегия (.+?): (\d+(?:\.\d+)?)%$/) ||
        msg.match(/^Стратегия (.+?): не запустилась$/);
    if (m) {
      const row = this.state.rows.get(m[1]);
      if (row) {
        row.rateCell.innerHTML = m[2] !== undefined
          ? Math.round(+m[2]) + '%'
          : '<span class="st-err">0%</span>';
        row.tr.classList.add('st-bad');
      }
      this._finishRow(m[1]);
    }
  },

  // ── опрос тестера ──

  _startTesterAction(actionData, callbacks) {
    const { resultType, onResult, progressConfig, onError, onCancel, onIntermediate } = callbacks || {};
    const { startPercent = 0, scalePercent = 1, textTemplate = '' } = progressConfig || {};
    let known = this.state.knownResults = 0;
    let started = false;
    let pollActive = true;

    fetch('/api/tester/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(actionData),
    }).then(r => {
      if (!r.ok) throw Error('HTTP ' + r.status);
      started = true;
    }).catch(() => {
      pollActive = false;
      if (onError) onError();
    });

    const pollId = setInterval(() => {
      if (!pollActive) { clearInterval(pollId); return; }
      if (!started) return;
      apiGet('/tester/status').then(state => {
        if (!pollActive) return;
        if (state.cancelled) {
          pollActive = false; clearInterval(pollId);
          $('testCurrentPhase').textContent = 'Тест отменён';
          this.clearElapsedTimer();
          setTimeout(() => this.resetToIntro(), 1300);
          return;
        }
        if (state.progress) {
          $('testProgressFill').style.width =
            Math.min(100, startPercent + (state.progress.percent || 0) * scalePercent) + '%';
          if (state.progress.message) {
            if (textTemplate) $('testProgressMsg').textContent = textTemplate.replace('{msg}', state.progress.message);
            this._handleProgressMessage(state.progress.message);
          }
        }
        const results = state.results || [];
        while (known < results.length) {
          const item = results[known++];
          if (!item) continue;
          const type = item.type || '';
          if (type === 'test_result' || (item.domain && item.status)) this._addHostRow(item);
          else if (type === 'intermediate') {
            if (onIntermediate) onIntermediate(item);
            else this.addTestLog((item.profile || '?') + (item.blob ? ' + ' + item.blob : '') +
              ' score=' + (item.success_rate != null ? item.success_rate.toFixed(0) : '?'));
          }
        }
        if (!state.running) {
          const fr = state.final_result;
          if (state.error) {
            pollActive = false; clearInterval(pollId);
            this.clearElapsedTimer();
            $('testCurrentPhase').textContent = 'Ошибка: ' + state.error;
            showToast('Тест прерван: ' + state.error, 'error');
            setTimeout(() => this.resetToIntro(), 2500);
            return;
          }
          if (!fr) {
            pollActive = false; clearInterval(pollId);
            this.clearElapsedTimer();
            $('testCurrentPhase').textContent = 'Тест завершился без результата';
            showToast('Тест завершился без результата — запустите подбор заново', 'warn');
            setTimeout(() => this.resetToIntro(), 1800);
            return;
          }
          pollActive = false; clearInterval(pollId);
          if (state.all_results && !fr.all_results) fr.all_results = state.all_results;
          if (fr.restored) showToast(fr.restored, /Не удалось|не восстановлен/.test(fr.restored) ? 'warn' : 'ok');
          if (resultType && fr.type === resultType) { if (onResult) onResult(fr); }
          else if (fr.type === 'current_result') { this.state.currentResults = fr; this.runFullPipelinePhase1(); }
          else if (fr.type === 'naked_result') { if (onResult) onResult(fr); }
          else if (fr.type === 'need_zapret1') {
            this.clearElapsedTimer();
            $('testRun').hidden = true;
            $('needZapret1Overlay').classList.add('open');
            $('needZapret1Status').textContent = '';
          }
          else if (fr.type === 'check_result') { if (onResult) onResult(fr); }
          else if (fr.type === 'final') {
            this.state.fullAnalysisResults = fr.all_results || [];
            this._fillTable(this.state.fullAnalysisResults);
            this._finishAdvancedPhase4();
          }
          else if (onResult) onResult(fr);
        }
      }).catch(() => {
        if (pollActive && known === 0) {
          pollActive = false; clearInterval(pollId);
          if (onError) onError();
        }
      });
    }, 350);
    return pollId;
  },

  // ── запуск ──

  startTest() {
    this.state.cdnTest = $('cdnCheck').checked;
    this.state.advancedTest = $('extendedCheck').checked;
    this.state.collectLogs = $('logCheck').checked;
    this.resetAllState();
    this.runVpnCheck();
  },

  resetAllState() {
    Object.assign(this.state, {
      currentResults: null, nakedResults: null, phase2Results: null,
      fullAnalysisResults: null, collectFormData: null, collectBatFile: null,
    });
    $('testLog').innerHTML = '';
    $('testSummary').hidden = true;
    $('testSummary').innerHTML = '';
    this._resetTable();
  },

  runVpnCheck() {
    const pollId = this._startTesterAction({ action: 'check_vpn' }, {
      onResult: (final) => {
        clearInterval(pollId);
        this.state.vpnActive = !!final.vpn_active;
        if (final.vpn_active) {
          $('vpnDetails').textContent = final.details || '';
          $('testRun').hidden = true;
          $('vpnOverlay').classList.add('open');
          $('vpnStatus').textContent = '';
        } else {
          this.runPipeline();
        }
      },
      onError: () => this.runPipeline(),
    });
  },

  runPipeline() {
    $('vpnOverlay').classList.remove('open');
    $('testerIntro').hidden = true;
    $('testRun').hidden = false;
    $('testCurrentPhase').textContent = 'Подготовка…';
    $('testProgressFill').style.width = '0%';
    $('testProgressMsg').textContent = '';
    $('btnStartTest').disabled = true;
    this.startElapsedTimer();
    if (this.state.advancedTest) this.runFullPipelinePhase0();
    else this.runBasicPhase2();
  },

  runBasicPhase2() {
    $('testCurrentPhase').textContent = 'Стратегии тестируются по очереди';
    this._startTesterAction(
      { action: 'test_profiles', profiles: PROFILES, skip_cdn: !this.state.cdnTest },
      {
        progressConfig: { startPercent: 0, scalePercent: 1, textTemplate: '{msg}' },
        onResult: (d) => {
          this.state.phase2Results = d;
          this._fillTable(d.all_results || []);
          this.finalizePipeline('basic');
        },
        onError: () => { $('testCurrentPhase').textContent = 'Ошибка теста'; this.clearElapsedTimer(); },
      });
  },

  runFullPipelinePhase0() {
    $('testCurrentPhase').textContent = 'Фаза 1 из 4: текущий Zapret 1';
    this._startTesterAction({ action: 'current', skip_cdn: !this.state.cdnTest }, {
      progressConfig: { startPercent: 0, scalePercent: 0.08 },
      onError: () => { $('testCurrentPhase').textContent = 'Ошибка (Zapret 1)'; this.clearElapsedTimer(); },
    });
  },

  runFullPipelinePhase1() {
    $('testCurrentPhase').textContent = 'Фаза 2 из 4: базовый уровень без защиты';
    this._startTesterAction({ action: 'naked', skip_cdn: !this.state.cdnTest }, {
      resultType: 'naked_result',
      progressConfig: { startPercent: 8, scalePercent: 0.07 },
      onResult: (d) => {
        this.state.nakedResults = d;
        const row = this.state.rows.get('__naked__');
        if (row) {
          const rate = d.network_rate || 0;
          row.rateCell.innerHTML = `<span class="${rateClass(rate)}">${rate.toFixed(0)}%</span>`;
          row.hostsCell.textContent = (d.net_ok_count != null ? d.net_ok_count : 0) + '/' + (d.net_total != null ? d.net_total : 0);
        }
        this._finishRow('__naked__');
        this.runFullPipelinePhase2();
      },
      onError: () => { $('testCurrentPhase').textContent = 'Ошибка (naked)'; this.clearElapsedTimer(); },
    });
  },

  runFullPipelinePhase2() {
    $('testCurrentPhase').textContent = 'Фаза 3 из 4: тест стратегий Zapret 2';
    this._startTesterAction(
      { action: 'test_profiles', profiles: PROFILES, skip_cdn: !this.state.cdnTest },
      {
        resultType: 'result',
        progressConfig: { startPercent: 15, scalePercent: 0.1 },
        onResult: (d) => {
          this.state.phase2Results = d;
          this._fillTable(d.all_results || []);
          this.runFullPipelinePhase3();
        },
        onError: () => { $('testCurrentPhase').textContent = 'Ошибка теста'; this.clearElapsedTimer(); },
      });
  },

  runFullPipelinePhase3() {
    if (!PROFILES.length) {
      $('testCurrentPhase').textContent = 'Нет профилей для анализа';
      this.clearElapsedTimer();
      this.finalizePipeline('full');
      return;
    }
    $('testCurrentPhase').textContent = 'Фаза 4 из 4: полный анализ комбинаций';
    this._startTesterAction({ action: 'full_analysis', profiles: PROFILES }, {
      progressConfig: { startPercent: 25, scalePercent: 0.35 },
      onError: () => { $('testCurrentPhase').textContent = 'Ошибка анализа'; this.clearElapsedTimer(); },
    });
  },

  _finishAdvancedPhase4() {
    $('testProgressFill').style.width = '95%';
    this.finalizePipeline('full');
  },

  // ── заполнение таблицы финальными числами ──

  _fillTable(allResults) {
    for (const r of allResults) {
      const key = r.profile || '';
      const row = this._rowFor(key);
      const rate = r.network_rate != null ? r.network_rate : (r.success_rate || 0);
      row.rateCell.innerHTML = `<span class="${rateClass(rate)}">${rate.toFixed(0)}%</span>`;
      if (r.net_ok_count != null) row.hostsCell.textContent = r.net_ok_count + '/' + r.net_total;
      const statusOf = (domains) => {
        const found = (r.results || []).filter(x => domains.includes(x.domain) && x.test_type !== 'ping');
        if (!found.length) return '—';
        return found.some(x => x.status === 'OK' || x.status === 'OK_BLOCKED')
          ? '<span class="st-ok">✓</span>' : '<span class="st-err">✗</span>';
      };
      row.discordCell.innerHTML = statusOf(['discord.com', 'gateway.discord.gg']);
      row.ytCell.innerHTML = statusOf(['www.youtube.com', 'youtu.be', 'i.ytimg.com']);
      row.stateDot.className = 'dot ' + (rate >= SCORE_OK ? 'dot-ok' : rate >= SCORE_MID ? 'dot-warn' : 'dot-err');
      row.stateText.textContent = 'готово';
      row.tr.classList.remove('is-current');
      row.tr.classList.remove('st-good', 'st-mid', 'st-bad');
      row.tr.classList.add(rate >= SCORE_OK ? 'st-good' : rate >= SCORE_MID ? 'st-mid' : 'st-bad');
    }
    const rec = this.state.phase2Results && this.state.phase2Results.recommendation;
    if (rec && rec.best_profile) {
      const best = this.state.rows.get(rec.best_profile);
      if (best) best.tr.classList.add('is-best');
    }
  },

  // ── финал ──

  finalizePipeline(mode) {
    this.clearElapsedTimer();
    $('testProgressFill').style.width = '100%';
    $('testCurrentPhase').textContent = 'Готово';
    $('btnStartTest').disabled = false;
    $('testRun').hidden = true;

    const el = $('testSummary');
    let html = '';

    if (mode === 'basic') {
      const p2 = this.state.phase2Results || {};
      const rec = p2.recommendation;
      const custom = p2.custom;
      const naked = p2.naked;

      if (rec) html += this._renderVerdict(rec);
      else html += '<div class="panel"><div class="verdict-title st-warn">Итог не определён</div><div class="verdict-msg">Нет результатов — запустите подбор заново.</div></div>';

      if (custom && custom.summary) {
        const rel = custom.relation === 'better' ? '— обгоняет лучшую'
          : custom.relation === 'worse' ? '— уступает лучшей'
          : custom.relation === 'equal' ? '— равна лучшей' : '';
        const rateTxt = custom.rate != null ? ` (${custom.rate}%)` : '';
        html += `<div class="panel${custom.valid ? '' : ' verdict-panel v-no_bypass'}">
          <div class="panel-title">Личная стратегия «custom»</div>
          <div class="verdict-msg">${escapeHtml(custom.summary)}${rel ? ' ' + rel : ''}${rateTxt}.
          ${custom.valid
            ? 'Если «custom» помечена лучшей в таблице — запускайте её кнопкой выше.'
            : 'Не прошла проверку движком — запускать её не стоит.'}
          ${custom.error && !custom.valid ? `<span class="st-err">${escapeHtml(custom.error)}</span>` : ''}</div>
        </div>`;
      } else if (custom && custom.error) {
        html += `<div class="panel verdict-panel v-no_bypass">
          <div class="panel-title">Личная стратегия не собрана</div>
          <div class="verdict-msg st-err">${escapeHtml(custom.error)}</div>
        </div>`;
      }

      if (naked && naked.net_total) {
        html += `<div class="panel">
          <div class="panel-title">Базовый уровень (без защиты): <span class="${rateClass(naked.network_rate || 0)}">${(naked.network_rate || 0).toFixed(0)}%</span></div>
          <div class="verdict-msg">Столько сервисов доступно вообще без Zapret. Столбец «Без защиты» в таблице — точка отсчёта.</div>
        </div>`;
      }

      if (rec && rec.blocked_domains && rec.blocked_domains.length && rec.verdict !== 'ok') {
        html += `<div class="panel">
          <div class="panel-title">Не пробито ни одной стратегией</div>
          <div class="blocked-chips">${rec.blocked_domains.map(d => `<span class="chip">${escapeHtml(d)}</span>`).join('')}</div>
          <div class="verdict-msg">Если это ваши рабочие домены — добавьте их в «Списки → Домены — обрабатывать».</div>
        </div>`;
      }
    } else {
      const cur = this.state.currentResults;
      const naked = this.state.nakedResults;
      const fa = this.state.fullAnalysisResults || [];
      const rateOf = r => (r.network_rate != null ? r.network_rate : (r.success_rate || 0));
      const best = fa.length ? fa.reduce((a, b) => rateOf(a) > rateOf(b) ? a : b) : null;
      html += `<div class="panel">
        <div class="panel-title">Сравнение</div>
        <table class="check-table"><tbody>
          <tr><td class="check-name">Zapret 1 (текущий)</td><td class="mono">${cur ? rateOf(cur).toFixed(0) + '%' : '—'}</td></tr>
          <tr><td class="check-name">Без защиты</td><td class="mono">${naked ? rateOf(naked).toFixed(0) + '%' : '—'}</td></tr>
          <tr><td class="check-name">Zapret 2, лучшая${best ? ' («' + escapeHtml(best.profile || '') + (best.blob ? ' + ' + escapeHtml(best.blob) : '') + '»)' : ''}</td>
              <td class="mono ${best ? rateClass(rateOf(best)) : ''}">${best ? rateOf(best).toFixed(0) + '%' : '—'}</td></tr>
        </tbody></table>
        <div class="verdict-msg">Подробности каждой комбинации — в таблице стратегий (клик по строке).</div>
      </div>`;
    }

    if (this.state.collectLogs) {
      html += `<div class="panel" style="display:flex;gap:12px;align-items:center">
        <button class="btn btn-primary" id="btnShowCollect">Сохранить отчёт для поддержки</button>
        <span class="meta">ZIP с результатами теста сохранится в папку программы</span>
      </div>`;
    }
    html += `<div><button class="btn" id="btnBackToIntro">Новый подбор</button></div>`;

    el.innerHTML = html;
    el.hidden = false;
    if ($('btnShowCollect')) $('btnShowCollect').addEventListener('click', () => this.showCollectForm());
    $('btnBackToIntro').addEventListener('click', () => this.resetToIntro());
  },

  _renderVerdict(rec) {
    const vm = {
      ok: ['Обход работает', 'dot-ok'],
      partial: ['Обход работает частично', 'dot-warn'],
      no_bypass: ['Обход не сработал', 'dot-err'],
      engine_broken: ['Проблема с движком Zapret', 'dot-err'],
      no_data: ['Нет данных', 'dot-idle'],
    };
    const [title, dotCls] = vm[rec.verdict] || vm.no_data;
    let keys = '';
    if (rec.key_hosts && rec.key_hosts.length) {
      keys = '<div class="key-grid">' + rec.key_hosts.map(k => {
        const ok = k.status === 'OK' || k.status === 'QUIC_OK';
        const label = k.status === 'QUIC_OK' ? 'через QUIC' : ok ? 'доступен' : 'не пробит';
        return `<div class="key-cell ${ok ? 'cell-ok' : 'cell-err'}">
          <span class="dot ${ok ? 'dot-ok' : 'dot-err'}"></span><b>${escapeHtml(k.label)}</b>
          <span class="meta">${escapeHtml(label)}${k.time_ms ? ' · ' + formatTime(k.time_ms) : ''}</span>
        </div>` + (k.note ? `<div class="verdict-msg" style="grid-column:1/-1">${escapeHtml(k.note)}</div>` : '');
      }).join('') + '</div>';
    }

    let actions = '';
    if (rec.verdict === 'no_bypass' || rec.verdict === 'engine_broken') {
      actions = `<button class="btn btn-primary" onclick="location.hash='diagnostics'">Открыть проверку системы</button>
        ${rec.best_profile ? '<span class="meta">лучшая из протестированных: ' + escapeHtml(rec.best_profile) + '</span>' : ''}`;
    } else if (rec.best_profile) {
      actions = `<button class="btn btn-primary" id="btnApplyRec">Запустить: ${escapeHtml(rec.best_profile)}
        (${(rec.best_network_rate || 0).toFixed(0)}%)</button>`;
    }
    if (rec.same_as_naked) {
      actions += '<span class="meta">результат как без защиты — обход не применяется</span>';
    }

    return `<div class="panel verdict-panel v-${rec.verdict || 'no_data'}">
      <div class="verdict-title"><span class="dot ${dotCls}"></span>${escapeHtml(title)}${rec.best_profile && rec.verdict !== 'no_bypass' && rec.verdict !== 'engine_broken' ? ' — лучшая стратегия «' + escapeHtml(rec.best_profile) + '»' : ''}</div>
      <div class="verdict-msg">${escapeHtml(rec.message || '')}</div>
      ${keys}
      <div class="verdict-actions">${actions}</div>
    </div>`;
  },

  bindModals() {
    $('vpnCancelBtn').addEventListener('click', () => {
      $('vpnOverlay').classList.remove('open');
      this.resetToIntro();
    });
    $('retryVpnBtn').addEventListener('click', () => {
      $('vpnOverlay').classList.remove('open');
      $('testRun').hidden = false;
      $('vpnStatus').textContent = 'Проверяю…';
      this.runVpnCheck();
    });
    $('vpnSkipBtn').addEventListener('click', () => {
      this.state.vpnActive = true;
      $('testRun').hidden = false;
      this.runPipeline();
    });
    $('needZ1CancelBtn').addEventListener('click', () => {
      $('needZapret1Overlay').classList.remove('open');
      this.resetToIntro();
    });
    $('checkZapret1Btn').addEventListener('click', () => {
      $('needZapret1Status').textContent = 'Проверка…';
      $('checkZapret1Btn').disabled = true;
      this._startTesterAction({ action: 'check-winws' }, {
        onResult: (d) => {
          $('checkZapret1Btn').disabled = false;
          if (d.running) {
            $('needZapret1Overlay').classList.remove('open');
            $('testRun').hidden = false;
            this.runFullPipelinePhase0();
          } else {
            $('needZapret1Status').textContent = 'winws.exe всё ещё не найден — запустите батник Zapret 1.';
          }
        },
        onError: () => {
          $('checkZapret1Btn').disabled = false;
          $('needZapret1Status').textContent = 'Ошибка связи';
        },
      });
    });
    $('collectClose').addEventListener('click', () => this.closeCollectForm());
    $('collectCancelBtn').addEventListener('click', () => this.closeCollectForm());
    $('collectSubmitBtn').addEventListener('click', () => this.saveReport());
    $('collectBatZone').addEventListener('click', () => $('collectBatInput').click());
    $('collectBatInput').addEventListener('change', (e) => this.handleCollectBat(e));
    const dz = $('collectBatZone');
    dz.addEventListener('dragover', e => e.preventDefault());
    dz.addEventListener('drop', (e) => { e.preventDefault(); this.handleCollectDrop(e); });
  },

  cancelTest() {
    fetch('/api/tester/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'cancel' }),
    }).catch(() => {});
    $('testCurrentPhase').textContent = 'Отмена…';
  },

  resetToIntro() {
    this.clearElapsedTimer();
    $('testRun').hidden = true;
    $('testSummary').hidden = true;
    $('testerIntro').hidden = false;
    $('btnStartTest').disabled = false;
    if (localStorage.getItem('z2_diag_done')) $('diagDoneNote').hidden = false;
  },

  // ── сбор отчёта ──

  showCollectForm() {
    $('collectCity').value = '';
    $('collectIsp').value = '';
    $('collectBatLabel').textContent = 'Файл стратегии Zapret 1 (.bat) — по желанию';
    $('collectBatZone').classList.remove('filed');
    $('collectConsent').checked = false;
    $('collectSubmitBtn').disabled = false;
    $('collectSubmitBtn').textContent = 'Сохранить отчёт';
    this.state.collectBatFile = null;
    $('collectFormOverlay').classList.add('open');
  },

  closeCollectForm() { $('collectFormOverlay').classList.remove('open'); },

  handleCollectBat(e) { this._setCollectFile(e.target.files[0]); },
  handleCollectDrop(e) { this._setCollectFile(e.dataTransfer.files[0]); },
  _setCollectFile(f) {
    if (!f) return;
    this.state.collectBatFile = f;
    $('collectBatLabel').textContent = '✓ ' + f.name;
    $('collectBatZone').classList.add('filed');
  },

  async saveReport() {
    const consent = $('collectConsent').checked;
    if (!consent) { showToast('Отметьте согласие на сбор данных', 'warn'); return; }
    $('collectSubmitBtn').disabled = true;
    $('collectSubmitBtn').textContent = 'Сохранение…';

    const cur = this.state.currentResults;
    const naked = this.state.nakedResults;
    const phase2 = this.state.phase2Results;
    const slim = r => r ? {
      ok_count: r.ok_count, fail_count: r.fail_count, success_rate: r.success_rate,
      total_time_ms: r.total_time_ms, results: r.results, cdn_results: r.cdn_results,
    } : null;

    const body = {
      consent,
      city: $('collectCity').value.trim(),
      isp: $('collectIsp').value.trim(),
      vpn_active: this.state.vpnActive || false,
      zapret1_strategy: '',
      zapret1_cmdline: (cur && cur.zapret1_cmdline) || '',
      phase0_results: cur ? slim(cur) : { skipped: true },
      phase1_results: naked ? slim(naked) : null,
      phase2_results: phase2 ? Object.assign(slim(phase2) || {}, { all_results: phase2.all_results || [] }) : null,
      mode: this.state.advancedTest ? 'full' : 'basic',
    };
    if (this.state.collectBatFile) {
      try {
        body.zapret1_strategy = await this.fileToBase64(this.state.collectBatFile);
        body.zapret1_filename = this.state.collectBatFile.name;
      } catch (e) { /* ignore */ }
    }

    try {
      const r = await apiPost('/export-report', body);
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      try { await apiPost('/stop', {}); } catch (e) { /* ignore */ }
      this.closeCollectForm();
      const fileName = (r.file || '').split('\\').pop() || 'report.zip';
      $('testSummary').insertAdjacentHTML('beforeend',
        `<div class="notice notice-info">Отчёт сохранён: <b class="mono">${escapeHtml(fileName)}</b> в папке программы.</div>`);
      showToast('Отчёт сохранён', 'ok');
    } catch (e) {
      showToast('Ошибка сохранения отчёта: ' + e.message, 'error');
      $('collectSubmitBtn').disabled = false;
      $('collectSubmitBtn').textContent = 'Сохранить отчёт';
    }
  },

  fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(',')[1]);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  },

  addTestLog(msg) {
    const el = $('testLog');
    const ts = new Date().toLocaleTimeString();
    const div = document.createElement('div');
    div.className = 'test-log-entry';
    div.innerHTML = `<span class="ts">${ts}</span>` + escapeHtml(msg);
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
  },

  startElapsedTimer() {
    this.clearElapsedTimer();
    this.state.testStartTime = Date.now();
    this.state.elapsedInterval = setInterval(() => {
      const s = Math.floor((Date.now() - this.state.testStartTime) / 1000);
      $('testElapsed').textContent =
        String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
    }, 1000);
  },

  clearElapsedTimer() {
    if (this.state.elapsedInterval) {
      clearInterval(this.state.elapsedInterval);
      this.state.elapsedInterval = null;
    }
  },
};

// ── boot ──

document.addEventListener('DOMContentLoaded', () => App.init());
