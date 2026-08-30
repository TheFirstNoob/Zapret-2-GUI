/**
 * Zapret2 Manager — Frontend Application
 * Modular SPA for managing Zapret2 DPI bypass tester.
 */

// ── Global Config & State ──
const APP_TOKEN = window.APP_TOKEN || '__APP_TOKEN__';
const API = window.location.origin;
const SCORE_THRESHOLD = 80;

let PROFILES = [];


// Override fetch to inject token for /api/* requests
const _origFetch = window.fetch;
window.fetch = function(url, opts) {
  opts = opts || {};
  if (typeof url === 'string' && url.startsWith('/api/')) {
    opts.headers = opts.headers || {};
    opts.headers['X-App-Token'] = APP_TOKEN;
  }
  return _origFetch(url, opts);
};

// ── Error Handling ──
window.onerror = function(msg, url, line) {
  console.error('JS ERROR line ' + line + ': ' + msg);
};

// ── Utilities ──
function escapeHtml(s) {
  if (!s) return '';
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

function formatTime(ms) {
  const n = parseFloat(ms) || 0;
  if (n < 1000) return n.toFixed(0) + 'ms';
  return (n / 1000).toFixed(1) + 's';
}

function formatDuration(seconds) {
  if (seconds < 60) return seconds.toFixed(1) + 's';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m + 'm ' + String(s).padStart(2, '0') + 's';
}

function scoreColor(s) {
  return s >= SCORE_THRESHOLD ? 'var(--ok)' : s >= 40 ? 'var(--warn)' : 'var(--err)';
}

function clamp(val, min, max) {
  return Math.min(max, Math.max(min, val));
}

// ── API Helpers ──
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

// ── Toast ──
function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (type ? ' ' + type : '');
  t.style.display = 'block';
  t.style.opacity = '1';
  clearTimeout(t._hide);
  t._hide = setTimeout(() => {
    t.style.opacity = '0';
    setTimeout(() => { t.style.display = 'none'; }, 300);
  }, 3500);
}

// ── Batch Processor for DOM updates ──
function createBatchProcessor(processFn, delayMs) {
  let queue = [];
  let timer = null;
  return function(item) {
    queue.push(item);
    if (!timer) {
      timer = setTimeout(() => {
        const batch = queue;
        queue = [];
        timer = null;
        processFn(batch);
      }, delayMs);
    }
  };
}

// ── App Router ──
const App = {
  currentPage: 'main',
  pages: ['main', 'tester', 'exclude', 'diagnostics'],

  async init() {
    this.bindNav();
    this.handleHash();
    window.addEventListener('hashchange', () => { this.handleHash(); });
    await this.loadVersion();
    await this.loadProfiles();
    TesterPage.init();
    if (this.currentPage === 'main') MainPage.onShow();
    MainPage.startAutoRefresh();
    this.checkUpdate();
  },

  // Non-intrusive update banner (silent on any failure).
  async checkUpdate() {
    try {
      const r = await apiGet('/update-check');
      if (r.available && r.latest) {
        document.getElementById('updateVersion').textContent = r.latest;
        document.getElementById('updateLink').href = r.url || '#';
        document.getElementById('updateMirrorLink').href = r.mirror_url || '#';
        document.getElementById('updateBanner').style.display = 'flex';
      }
    } catch (e) { /* silent */ }
  },

  async loadVersion() {
    try {
      const data = await apiGet('/version');
      const el = document.getElementById('appVersion');
      if (el && data.version) el.textContent = data.version;
    } catch (e) {
      // ignore
    }
  },

  bindNav() {
    document.querySelectorAll('.nav-link').forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const page = link.dataset.page;
        window.location.hash = page;
      });
    });
  },

  handleHash() {
    const hash = window.location.hash.replace('#', '') || 'main';
    if (!this.pages.includes(hash)) {
      showToast('Этот раздел ещё не готов', 'warn');
      window.location.hash = this.currentPage;
      return;
    }
    const prev = this.currentPage;
    this.currentPage = hash;
    this.updateNav();
    this.showPage(hash);
    if (prev !== hash) {
      if (hash === 'main') MainPage.startAutoRefresh();
      else MainPage.stopAutoRefresh();
    }
    if (hash === 'main') MainPage.onShow();
    if (hash === 'exclude') ExcludePage.onShow();
  },

  updateNav() {
    document.querySelectorAll('.nav-link').forEach(link => {
      link.classList.toggle('active', link.dataset.page === this.currentPage);
    });
  },

  showPage(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const el = document.getElementById('page-' + page);
    if (el) el.classList.add('active');

    const titles = { main: 'Главная', tester: 'Подбор стратегии', exclude: 'Списки', diagnostics: 'Проверка системы' };
    document.getElementById('pageTitle').textContent = titles[page] || 'Zapret2';
  },

  async loadProfiles() {
    try {
      const data = await apiGet('/profiles');
      PROFILES = (data.profiles || []).map(p => p.name);
    } catch (e) {
      PROFILES = ['default'];
    }
  }
};



// ── Main Page ──
const MainPage = {
  timer: null,

  onShow() {
    this.refresh();
    this.loadZ1Config();
    this.loadToggles();
    this.refreshServiceStatus();
  },

  async loadToggles() {
    try {
      const r = await apiGet('/config');
      const c = r.config || {};
      const gf = document.getElementById('toggleGameFilter');
      const dv = document.getElementById('toggleDiscordVoice');
      const db = document.getElementById('toggleWinws2Debug');
      const ah = document.getElementById('toggleAutoHostlist');
      const ipf = document.getElementById('toggleIpFilter');
      if (gf && c.game_filter_mode) gf.value = c.game_filter_mode;
      if (dv) dv.checked = !!c.discord_voice;
      if (db) db.checked = !!c.winws2_debug;
      if (ah) ah.checked = !!c.autohostlist;
      if (ipf) ipf.checked = !!c.ipset_catchall;
    } catch (e) { /* ignore */ }
  },

  async refresh() {
    try {
      const data = await apiGet('/status');
      this.updateZ2(data.zapret);
      this.updateZ1(data.zapret1);
      this.updateConflict(data.zapret, data.zapret1);
      this.populateProfiles(data.profiles || []);
    } catch (e) {
      document.getElementById('z2StatusBadge').textContent = '❌ ошибка';
      document.getElementById('z1StatusBadge').textContent = '❌ ошибка';
    }
  },

  async loadZ1Config() {
    try {
      const r = await apiGet('/config');
      const dir = (r.config && r.config.zapret1_dir) || '';
      document.getElementById('z1DirPath').value = dir || '';
      if (dir) this.scanZ1Strategies();
    } catch (e) { /* ignore */ }
  },

  async saveZ1Dir() {
    const dir = document.getElementById('z1DirPath').value.trim();
    if (!dir) { showToast('Введите путь к папке Zapret 1', 'warning'); return; }
    const el = document.getElementById('z1Result');
    el.textContent = '⏳ Сохранение...';
    el.className = '';
    try {
      const r = await apiPost('/zapret1/save-dir', { path: dir });
      if (r.status === 'ok') {
        el.textContent = '✅ ' + (r.message || 'OK');
        await this.scanZ1Strategies();
        const sel = document.getElementById('z1StrategySelect');
        if (sel.dataset.saved) {
          el.textContent = '✅ Сохранённая стратегия: ' + sel.dataset.saved + '.bat';
        }
      } else {
        el.textContent = '❌ ' + (r.message || 'Ошибка');
        el.className = 'launch-err';
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
      el.className = 'launch-err';
    }
  },

  async scanZ1Strategies() {
    const sel = document.getElementById('z1StrategySelect');
    sel.disabled = true;
    sel.innerHTML = '<option value="">⏳ сканирование...</option>';
    try {
      const r = await apiGet('/zapret1/strategies');
      sel.innerHTML = '';
      const strs = r.strategies || [];
      if (strs.length === 0) {
        sel.innerHTML = '<option value="">— нет стратегий —</option>';
        sel.disabled = true;
        return;
      }
      sel.disabled = false;
      // Load saved strategy
      let saved = '';
      try {
        const cr = await apiGet('/config');
        saved = (cr.config && cr.config.zapret1_last_strategy) || '';
      } catch (e) { /* ignore */ }
      let found = false;
      for (const s of strs) {
        const opt = document.createElement('option');
        opt.value = s.name;
        opt.textContent = s.name + '.bat';
        if (s.name === saved) { opt.selected = true; found = true; }
        sel.appendChild(opt);
      }
      if (found) sel.dataset.saved = saved;
    } catch (e) {
      sel.innerHTML = '<option value="">— ошибка сканирования —</option>';
      sel.disabled = true;
    }
  },

  updateZ2(z) {
    const badge = document.getElementById('z2StatusBadge');
    if (z.running) {
      badge.innerHTML = '<span class="status-dot status-dot-ok"></span> Запущен («' + escapeHtml(z.strategy || '?') + '»)';
      document.getElementById('z2Card').className = 'card main-card z2-running';
    } else {
      badge.innerHTML = '<span class="status-dot status-dot-off"></span> Остановлен';
      document.getElementById('z2Card').className = 'card main-card';
    }
    document.getElementById('z2Pid').textContent = z.pid || '—';
    if (!this._serviceBusy) {
      document.getElementById('btnZ2Start').disabled = z.running;
      document.getElementById('btnZ2Stop').disabled = !z.running;
    }
    this._z2Running = z.running;
    this._z2Strategy = z.strategy || '';
    this._updateApplyButton();
    this._updateUptime(z.running);
  },

  _updateUptime(running) {
    document.getElementById('z2Uptime').textContent = running ? '✅ работает' : '—';
  },

  _updateApplyButton() {
    const btn = document.getElementById('btnApplyToggles');
    if (btn) btn.style.display = this._z2Running ? '' : 'none';
  },

  updateZ1(z1) {
    const badge = document.getElementById('z1StatusBadge');
    const dir = document.getElementById('z1DirPath').value.trim();
    if (z1.running) {
      badge.innerHTML = '<span class="status-dot status-dot-ok"></span> Запущен';
      document.getElementById('z1Card').className = 'card main-card z1-running';
    } else {
      badge.innerHTML = '<span class="status-dot status-dot-off"></span> Остановлен';
      document.getElementById('z1Card').className = 'card main-card';
    }
    document.getElementById('z1Pid').textContent = z1.running && z1.pid ? z1.pid : '—';
    document.getElementById('btnZ1Start').disabled = z1.running;
    document.getElementById('btnZ1Stop').disabled = !z1.running;
    // Show hint if path not set
    const sel = document.getElementById('z1StrategySelect');
    if (!dir && !z1.running) {
      sel.innerHTML = '<option value="">— укажите путь к Zapret 1 —</option>';
      sel.disabled = true;
    }
    // Block toggles when Zapret 1 is running (settings only apply to Zapret 2)
    const overlay = document.getElementById('togglesOverlay');
    if (overlay) {
      overlay.classList.toggle('show', z1.running);
    }
  },

  updateConflict(z2, z1) {
    const el = document.getElementById('conflictInline');
    if (z2.running && z1.running) {
      el.style.display = 'block';
    } else {
      el.style.display = 'none';
    }
  },

  populateProfiles(profiles) {
    const sel = document.getElementById('strategySelect');
    if (sel.options.length > 1) return;
    for (const p of profiles) {
      const opt = document.createElement('option');
      opt.value = p;
      opt.textContent = p;
      sel.appendChild(opt);
    }
    apiGet('/config').then(r => {
      const saved = (r.config && r.config.last_profile) || '';
      if (saved && profiles.includes(saved)) {
        sel.value = saved;
        sel.options[0].disabled = true;
      }
    }).catch(() => {});
    sel.addEventListener('change', () => {
      const val = sel.value;
      if (val) apiPost('/config', { last_profile: val }).catch(() => {});
    });
  },

  async startSelected() {
    const profile = document.getElementById('strategySelect').value;
    if (!profile) { showToast('Выберите стратегию', 'warning'); return; }
    // Save current toggles before start
    const gf = document.getElementById('toggleGameFilter').value;
    const dv = document.getElementById('toggleDiscordVoice').checked;
    const db = document.getElementById('toggleWinws2Debug').checked;
    const ah = document.getElementById('toggleAutoHostlist').checked;
    const ipf = document.getElementById('toggleIpFilter').checked;
    await apiPost('/config', { game_filter_mode: gf, discord_voice: dv, winws2_debug: db, autohostlist: ah, ipset_catchall: ipf });
    const el = document.getElementById('startResult');
    el.textContent = '⏳ Запуск...';
    el.className = '';
    this._setServiceBusy(true);
    try {
      const r = await apiPost('/start', { profile });
      if (r.status === 'ok') {
        showToast('Zapret 2 запущен: ' + profile, 'ok');
        el.textContent = '✅ ' + (r.message || 'OK');
      } else {
        showToast('Ошибка: ' + (r.message || ''), 'error');
        el.textContent = '❌ ' + (r.message || 'Ошибка');
        el.className = 'launch-err';
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
      el.className = 'launch-err';
    }
    this._setServiceBusy(false);
    this.refresh();
  },

  async stop() {
    const el = document.getElementById('startResult');
    el.textContent = 'Остановка...';
    this._setServiceBusy(true);
    try {
      const r = await apiPost('/stop', {});
      if (r.status === 'ok') {
        showToast('Zapret 2 остановлен', 'ok');
        el.textContent = '✅ Остановлен';
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
    }
    this._setServiceBusy(false);
    this.refresh();
  },

  async startZ1() {
    const sel = document.getElementById('z1StrategySelect');
    const strategy = sel.value;
    if (!strategy) { showToast('Выберите стратегию Zapret 1', 'warning'); return; }
    const el = document.getElementById('z1Result');
    el.textContent = '⏳ Запуск Zapret 1...';
    el.className = '';
    try {
      const r = await apiPost('/zapret1/start', { strategy });
      if (r.status === 'ok') {
        showToast('Zapret 1 запущен: ' + strategy + '.bat', 'ok');
        el.textContent = '✅ ' + (r.message || 'OK');
      } else {
        el.textContent = '❌ ' + (r.message || 'Ошибка');
        el.className = 'launch-err';
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
      el.className = 'launch-err';
    }
    this.refresh();
  },

  async stopZ1() {
    const el = document.getElementById('z1Result');
    el.textContent = '⏳ Остановка Zapret 1...';
    el.className = '';
    try {
      const r = await apiPost('/zapret1/stop', {});
      if (r.status === 'ok') {
        showToast('Zapret 1 остановлен', 'ok');
        el.textContent = '✅ ' + (r.message || 'OK');
      } else {
        el.textContent = '❌ ' + (r.message || 'Ошибка');
        el.className = 'launch-err';
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
      el.className = 'launch-err';
    }
    this.refresh();
  },

  async restartZapret() {
    const strategy = this._z2Strategy;
    if (!strategy) { showToast('Нет запущенной стратегии', 'warning'); return; }
    const el = document.getElementById('applyTogglesResult');
    const btn = document.getElementById('btnApplyToggles');
    btn.disabled = true;
    el.textContent = '⏳ Сохранение...';
    try {
      const gf = document.getElementById('toggleGameFilter').value;
      const dv = document.getElementById('toggleDiscordVoice').checked;
      const db = document.getElementById('toggleWinws2Debug').checked;
      const ah = document.getElementById('toggleAutoHostlist').checked;
      const ipf = document.getElementById('toggleIpFilter').checked;
      await apiPost('/config', { game_filter_mode: gf, discord_voice: dv, winws2_debug: db, autohostlist: ah, ipset_catchall: ipf });
      el.textContent = '⏹ Остановка...';
      await apiPost('/stop', {});
      await new Promise(r => setTimeout(r, 1000));
      el.textContent = '▶ Перезапуск...';
      const r = await apiPost('/start', { profile: strategy });
      if (r.status === 'ok') {
        showToast('Перезапущено: ' + strategy, 'ok');
        el.textContent = '✅ Готово';
      } else {
        el.textContent = '❌ ' + (r.message || 'Ошибка');
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
    } finally {
      btn.disabled = false;
    }
  },

  // ── Service Management ──
  _serviceBusy: false,

  _setServiceBusy(busy) {
    this._serviceBusy = busy;
    document.getElementById('btnSvcInstall').disabled = busy;
    document.getElementById('btnSvcRemove').disabled = busy;
    if (busy) {
      document.getElementById('btnZ2Start').disabled = true;
      document.getElementById('btnZ2Stop').disabled = true;
    }
  },

  async refreshServiceStatus() {
    try {
      const r = await apiGet('/service/status');
      const el = document.getElementById('serviceStatus');
      document.getElementById('btnSvcInstall').style.display = r.installed ? 'none' : '';
      document.getElementById('btnSvcRemove').style.display = r.installed ? '' : 'none';
      if (r.installed) {
        el.textContent = r.running ? '✅ служба запущена' : '⏹ служба остановлена';
      } else {
        el.textContent = '';
      }
    } catch (e) { /* ignore */ }
  },

  async installService() {
    const profile = document.getElementById('strategySelect').value;
    if (!profile) { showToast('Выберите стратегию', 'warning'); return; }
    const gf = document.getElementById('toggleGameFilter').value;
    const dv = document.getElementById('toggleDiscordVoice').checked;
    const db = document.getElementById('toggleWinws2Debug').checked;
    const ah = document.getElementById('toggleAutoHostlist').checked;
    const ipf = document.getElementById('toggleIpFilter').checked;
    this._setServiceBusy(true);
    document.getElementById('serviceStatus').textContent = '⏳ Установка...';
    try {
      const r = await apiPost('/service/install', { profile, game_filter: gf, discord_voice: dv, debug: db, autohostlist: ah, ipset_catchall: ipf });
      showToast(r.message || 'Готово', r.status === 'ok' ? 'ok' : 'error');
      this.refreshServiceStatus();
    } catch (e) {
      showToast('Ошибка: ' + e.message, 'error');
    }
    this._setServiceBusy(false);
    this.refresh();
  },

  async removeService() {
    this._setServiceBusy(true);
    document.getElementById('serviceStatus').textContent = '⏳ Удаление...';
    try {
      const r = await apiPost('/service/remove', {});
      showToast(r.message || 'Готово', r.status === 'ok' ? 'ok' : 'error');
      this.refreshServiceStatus();
    } catch (e) {
      showToast('Ошибка: ' + e.message, 'error');
    }
    this._setServiceBusy(false);
    this.refresh();
  },

  startAutoRefresh() {
    this.stopAutoRefresh();
    this.timer = setInterval(() => {
      this.refresh();
      this.refreshServiceStatus();
    }, 5000);
    this.refreshServiceStatus();
  },

  stopAutoRefresh() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
  }
};


// ── Exclude Page ──
const ExcludePage = {
  async onShow() {
    await this.loadExclude();
    await this.loadInclude();
    await this.loadIpsetExclude();
  },

  async loadExclude() {
    try {
      const r = await apiGet('/exclude-list');
      document.getElementById('excludeTextarea').value = r.content || '';
    } catch (e) { /* ignore */ }
  },

  async loadInclude() {
    try {
      const r = await apiGet('/include-list');
      document.getElementById('includeTextarea').value = r.content || '';
    } catch (e) { /* ignore */ }
  },

  async loadIpsetExclude() {
    try {
      const r = await apiGet('/ipset-exclude-list');
      document.getElementById('ipsetExcludeTextarea').value = r.content || '';
    } catch (e) { /* ignore */ }
  },

  async saveExclude() {
    const content = document.getElementById('excludeTextarea').value;
    const el = document.getElementById('excludeSaveResult');
    el.textContent = '⏳ Сохранение...';
    try {
      const r = await apiPost('/exclude-list', { content });
      if (r.status === 'ok') {
        el.textContent = '✅ ' + (r.message || 'OK');
      } else {
        el.textContent = '❌ ' + (r.message || 'Ошибка');
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
    }
  },

  async saveInclude() {
    const content = document.getElementById('includeTextarea').value;
    const el = document.getElementById('includeSaveResult');
    el.textContent = '⏳ Сохранение...';
    try {
      const r = await apiPost('/include-list', { content });
      if (r.status === 'ok') {
        el.textContent = '✅ ' + (r.message || 'OK');
      } else {
        el.textContent = '❌ ' + (r.message || 'Ошибка');
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
    }
  },

  async saveIpsetExclude() {
    const content = document.getElementById('ipsetExcludeTextarea').value;
    const el = document.getElementById('ipsetExcludeSaveResult');
    el.textContent = '⏳ Сохранение...';
    try {
      const r = await apiPost('/ipset-exclude-list', { content });
      if (r.status === 'ok') {
        el.textContent = '✅ ' + (r.message || 'OK');
      } else {
        el.textContent = '❌ ' + (r.message || 'Ошибка');
      }
    } catch (e) {
      el.textContent = '❌ ' + e.message;
    }
  }
};


// ── Tester Page ──
const TesterPage = {
  state: {
    cdnTest: false,
    advancedTest: false,
    collectLogs: false,
    collectFormData: null,
    collectBatFile: null,
    currentResults: null,
    nakedResults: null,
    phase2Results: null,
    fullAnalysisResults: null,
    testStartTime: 0,
    elapsedInterval: null,
    ws: null,
    vpnActive: false,
    liveTableSort: { key: null, dir: 1 },
  },

  init() {
    // bind file input
  },

  // ── UI Helpers ──
  getStatusIcon(status) {
    switch (status) {
      case 'OK': case 'OK_BLOCKED': return '✅';
      case 'PARTIAL': return '🟡';
      case 'TCP16_20': return '🧪';
      case 'DPI_DROP': return '⚠️';
      case 'SSL_ERROR': return '🔒';
      case 'TIMEOUT': return '⏱️';
      case 'BLOCKED': return '🚫';
      case 'FAIL': return '❌';
      case 'ERROR': return '❓';
      default: return '⚪';
    }
  },

  getRowClass(status) {
    switch (status) {
      case 'OK': case 'OK_BLOCKED': return 'test-row-ok';
      case 'PARTIAL': case 'SSL_ERROR': return 'test-row-partial';
      case 'TCP16_20': return 'test-row-tcp1620';
      case 'DPI_DROP': return 'test-row-dpi_drop';
      case 'TIMEOUT': return 'test-row-timeout';
      case 'BLOCKED': case 'ERROR': case 'FAIL': return 'test-row-fail';
      default: return '';
    }
  },

  getStatusDescription(status) {
    switch (status) {
      case 'OK': return 'Соединение установлено, ответ получен';
      case 'BLOCKED': return 'Соединение сброшено или заблокировано DPI';
      case 'TIMEOUT': return 'Превышен интервал ожидания (DPI/сеть)';
      case 'ERROR': return 'Ошибка curl/TLS (подробности в колонке Ошибка)';
      case 'FAIL': return 'Ping не проходит';
      case 'TCP16_20': return 'DPI режет соединение с большим payload';
      default: return '';
    }
  },

  getCodeDescription(code) {
    const map = {
      '200': 'OK — запрос успешен',
      '204': 'No Content',
      '301': 'Moved Permanently — постоянный редирект',
      '302': 'Found — временный редирект',
      '303': 'See Other',
      '307': 'Temporary Redirect — временный редирект',
      '308': 'Permanent Redirect',
      '400': 'Bad Request',
      '401': 'Unauthorized',
      '403': 'Forbidden — доступ запрещён (не всегда DPI)',
      '404': 'Not Found',
      '405': 'Method Not Allowed',
      '418': "I'm a teapot — сервер шутит/защищается",
      '429': 'Too Many Requests',
      '451': 'Unavailable For Legal Reasons — блок по закону',
      '498': 'Invalid Token — защита от ботов/CDN',
      '500': 'Internal Server Error',
      '502': 'Bad Gateway',
      '503': 'Service Unavailable',
      '504': 'Gateway Timeout',
      '520': 'Web Server Returned Unknown Error — Cloudflare',
      '521': 'Web Server Is Down — Cloudflare',
      '522': 'Connection Timed Out — Cloudflare',
      '523': 'Origin Is Unreachable — Cloudflare',
      '524': 'A Timeout Occurred — Cloudflare',
      '—': 'Нет кода (ping/tls)',
      '⚠ DPI': 'DPI обнаружен по TCP 16-20',
    };
    return map[String(code)] || '';
  },

  getTestTypeBadge(type) {
    if (!type) return '<span class="badge badge-type-default">—</span>';
    if (type === 'https') return '<span class="badge badge-type-https">https</span>';
    if (type.startsWith('chunk')) return '<span class="badge badge-type-chunk">' + escapeHtml(type) + '</span>';
    if (type === 'tcp1620') return '<span class="badge badge-type-tcp1620">tcp1620</span>';
    if (type.startsWith('tls')) return '<span class="badge badge-type-tls">' + escapeHtml(type) + '</span>';
    if (type === 'ping') return '<span class="badge badge-type-ping">ping</span>';
    return '<span class="badge badge-type-default">' + escapeHtml(type) + '</span>';
  },

  formatTimeColored(ms) {
    const msNum = parseFloat(ms) || 0;
    const label = formatTime(ms);
    let cls = 'time-ok';
    if (msNum < 100) cls = 'time-fast';
    else if (msNum > 2000) cls = 'time-too-slow';
    else if (msNum > 500) cls = 'time-slow';
    return '<span class="time-ms ' + cls + '">' + label + '</span>';
  },

  updatePhaseIndicator(step, advanced) {
    const el = document.getElementById('testPhaseIndicator');
    if (!el) return;
    const labels = advanced
      ? ['Zapret 1', 'Naked', 'Zapret 2', 'Анализ', 'Отчёт']
      : ['Тест', 'Отчёт'];
    const total = advanced ? 5 : 2;
    let html = '';
    for (let i = 0; i < total; i++) {
      const done = i < step;
      const active = i === step;
      const dotCls = active ? 'active' : (done ? 'done' : '');
      const labelCls = active ? 'active' : '';
      html += '<div class="phase-step"><div class="phase-dot ' + dotCls + '">' + (done ? '✓' : (i + 1)) + '</div><div class="phase-label ' + labelCls + '">' + labels[i] + '</div></div>';
      if (i < total - 1) html += '<div class="phase-line ' + (done ? 'done' : '') + '"></div>';
    }
    el.innerHTML = html;
  },

  addTestLog(msg) {
    const el = document.getElementById('testLog');
    if (!el) return;
    el.classList.add('open');
    const ts = new Date().toLocaleTimeString();
    el.innerHTML += '<div class="test-log-entry"><span class="ts">' + ts + '</span>' + escapeHtml(msg) + '</div>';
    el.scrollTop = el.scrollHeight;
  },

  clearTestLog() {
    const el = document.getElementById('testLog');
    if (el) { el.innerHTML = ''; el.classList.remove('open'); }
  },

  startElapsedTimer() {
    this.state.testStartTime = Date.now();
    this.clearElapsedTimer();
    this.state.elapsedInterval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - this.state.testStartTime) / 1000);
      document.getElementById('testElapsed').textContent =
        String(Math.floor(elapsed / 60)).padStart(2, '0') + ':' + String(elapsed % 60).padStart(2, '0');
    }, 1000);
  },

  clearElapsedTimer() {
    if (this.state.elapsedInterval) {
      clearInterval(this.state.elapsedInterval);
      this.state.elapsedInterval = null;
    }
  },

  resetTestUI() {
    document.getElementById('testerIntro').style.display = 'none';
    document.getElementById('testProgress').style.display = 'block';
    document.getElementById('testLiveResults').style.display = 'block';
    document.getElementById('testSummary').style.display = 'none';
    document.getElementById('testResults').innerHTML = '';
    document.getElementById('testResultsBody').innerHTML = '';
    document.getElementById('testProgressFill').style.width = '0%';
    document.getElementById('testProgressText').textContent = 'Запуск...';
    document.getElementById('testCurrentInfo').textContent = '';
    document.getElementById('testElapsed').textContent = '00:00';
    this.clearTestLog();
  },

  // ── Collection Form ──
  showCollectForm() {
    document.getElementById('collectCity').value = '';
    document.getElementById('collectIsp').value = '';
    document.getElementById('collectBatName').style.display = 'none';
    document.getElementById('collectConsent').checked = false;
    document.getElementById('collectSubmitBtn').disabled = false;
    document.getElementById('collectSubmitBtn').textContent = '💾 Сохранить';
    document.getElementById('collectSubmitBtn').onclick = () => this.saveReport();
    document.getElementById('collectFormTitle').textContent = '💾 Сохранить отчёт';
    document.getElementById('collectFormDesc').textContent = 'Укажите данные для сохранения ZIP-отчёта с результатами теста.';
    this.state.collectBatFile = null;
    document.getElementById('collectFormOverlay').classList.add('open');
  },

  closeCollectForm() {
    document.getElementById('collectFormOverlay').classList.remove('open');
  },

  handleCollectBat(e) {
    const f = e.target.files[0];
    if (!f) return;
    this.state.collectBatFile = f;
    document.getElementById('collectBatName').textContent = '✓ ' + f.name;
    document.getElementById('collectBatName').style.display = 'block';
  },

  handleCollectDrop(e) {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (!f) return;
    this.state.collectBatFile = f;
    document.getElementById('collectBatName').textContent = '✓ ' + f.name;
    document.getElementById('collectBatName').style.display = 'block';
  },

  // ── VPN Check ──
  runVpnCheck() {
    const pollId = this._startTesterAction(
      { action: 'check_vpn' },
      {
        onResult: (final) => {
          clearInterval(pollId);
          this.state.vpnActive = final.vpn_active || false;
          if (final.vpn_active) {
            document.getElementById('vpnDetails').textContent = final.details || '';
            document.getElementById('vpnOverlay').classList.add('open');
            document.getElementById('vpnStatus').textContent = '';
          } else {
            this.runPipeline();
          }
        },
        onError: () => { this.runPipeline(); },
      }
    );
  },

  retryVpnCheck() {
    document.getElementById('vpnOverlay').classList.remove('open');
    document.getElementById('vpnStatus').textContent = 'Проверка...';
    this.runVpnCheck();
  },

  cancelVpnCheck() {
    document.getElementById('vpnOverlay').classList.remove('open');
    document.getElementById('btnStartTest').disabled = false;
    document.getElementById('testerIntro').style.display = 'block';
    document.getElementById('testResults').innerHTML = '';
    this.clearElapsedTimer();
  },

  // ── Pipeline dispatcher ──
  runPipeline() {
    this.resetTestUI();
    if (this.state.advancedTest) {
      this.runFullPipelinePhase0();
    } else {
      this.runBasicPhase2();
    }
  },

  skipVpnCheck() {
    document.getElementById('vpnOverlay').classList.remove('open');
    document.getElementById('vpnStatus').textContent = '';
    this.state.vpnActive = true;
    this.runPipeline();
  },

  // ── Entry Point ──
  startTest() {
    this.state.cdnTest = document.getElementById('cdnCheck').checked;
    this.state.advancedTest = document.getElementById('extendedCheck').checked;
    this.state.collectLogs = document.getElementById('logCheck').checked;
    this.resetAllState();
    this.runVpnCheck();
  },

  resetAllState() {
    this.state.currentResults = null;
    this.state.nakedResults = null;
    this.state.phase2Results = null;
    this.state.fullAnalysisResults = null;
    this.state.collectFormData = null;
    this.state.collectBatFile = null;
  },

  // ── Polling helper (replaces WebSocket) ──
  _startTesterAction(actionData, callbacks) {
    const { resultType, onResult, progressConfig, onError, onCancel, onIntermediate } = callbacks || {};
    const { startPercent = 0, scalePercent = 1, textTemplate = '' } = progressConfig || {};
    let knownResults = 0;
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
      if (!started) return; // wait for action to be acknowledged

      fetch('/api/tester/status', { headers: { 'X-App-Token': APP_TOKEN } })
        .then(r => { if (!r.ok) throw Error('HTTP ' + r.status); return r.json(); })
        .then(state => {
          if (!pollActive) return;
          if (state.cancelled) {
            pollActive = false; clearInterval(pollId);
            document.getElementById('testProgressText').textContent = onCancel || 'Отменено';
            this.clearElapsedTimer(); return;
          }
          // progress
          if (state.progress) {
            document.getElementById('testProgressFill').style.width = (startPercent + (state.progress.percent || 0) * scalePercent) + '%';
            if (textTemplate && state.progress.message) {
              document.getElementById('testProgressText').textContent = textTemplate.replace('{msg}', state.progress.message);
            }
          }
          // new results
          while (knownResults < (state.results || []).length) {
            const item = state.results[knownResults++];
            if (!item) continue;
            const type = item.type || '';
            if (type === 'test_result' || (item.domain && item.status)) {
              this.addTestResultRow(item);
            } else if (type === 'intermediate') {
              if (onIntermediate) { onIntermediate(item); }
              else {
                const lbl = item.profile + (item.blob ? ' + ' + item.blob : '');
                const scVal = item.success_rate != null ? item.success_rate : 0;
                const sc = scVal >= 80 ? 'OK' : scVal >= 40 ? 'WARN' : 'FAIL';
                this.addTestLog(lbl + ' score=' + scVal.toFixed(0) + ' ' + sc + (item.error ? ' ERROR: ' + item.error : ''));
              }
            }
          }
          if (state.progress && state.progress.current !== undefined) {
            document.getElementById('testCurrentInfo').textContent = (state.progress.current || '?') + '/' + (state.progress.total || '?');
          }
          // completion
          if (!state.running) {
            const fr = state.final_result;
            if (state.error) {
              pollActive = false; clearInterval(pollId);
              document.getElementById('testProgressText').textContent = 'Ошибка: ' + state.error;
              this.clearElapsedTimer(); return;
            }
            if (!fr) { return; } // race: thread hasn't set running=true yet, keep polling
            pollActive = false; clearInterval(pollId);
            // Server sends per-profile results in a separate field; merge so
            // finalizePipeline can render the comparison table (previously
            // lost → the results screen was empty, only "return" was visible).
            if (state.all_results && !fr.all_results) {
              fr.all_results = state.all_results;
            }
            if (fr.restored) {
              showToast(fr.restored, fr.restored.indexOf('Не удалось') === 0 || fr.restored.indexOf('не восстановлен') >= 0 ? 'warn' : 'ok');
            }
            if (resultType && fr.type === resultType) { if (onResult) onResult(fr); }
            else if (fr.type === 'current_result') { this.state.currentResults = fr; this.runFullPipelinePhase1(); }
            else if (fr.type === 'naked_result') { if (onResult) onResult(fr); }
            else if (fr.type === 'need_zapret1') {
              this.clearElapsedTimer();
              document.getElementById('testProgress').style.display = 'none';
              document.getElementById('testLiveResults').style.display = 'none';
              document.getElementById('needZapret1Overlay').classList.add('open');
              document.getElementById('needZapret1Status').textContent = '';
            } else if (fr.type === 'check_result') { if (onResult) onResult(fr); }
            else if (fr.type === 'final') {
              this.showFullAnalysisTable(fr.all_results);
              this.state.fullAnalysisResults = fr.all_results;
              this.state.phase2Results = { full_analysis: this.state.fullAnalysisResults, fuzz: [] };
              this.showComparison();
              document.getElementById('testProgressFill').style.width = '95%';
              document.getElementById('testProgressText').textContent = 'Фаза 4/4: формирование отчёта...';
              this.finalizePipeline('full');
            } else if (onResult) onResult(fr);
          }
        })
        .catch(() => {
          if (pollActive && knownResults === 0) {
            pollActive = false; clearInterval(pollId);
            if (onError) onError();
          }
        });
    }, 300);
    return pollId;
  },

  // ── Pipeline Phase 0: Current / Zapret 1 ──
  runFullPipelinePhase0() {
    this.clearTestLog();
    this.resetTestUI();
    this.updatePhaseIndicator(0, true);
    this.startElapsedTimer();
    document.getElementById('testProgressText').textContent = 'Фаза 1/4: Zapret 1 (ваша текущая защита)...';

    this._startTesterAction(
      { action: 'current', skip_cdn: !this.state.cdnTest },
      {
        progressConfig: { startPercent: 0, scalePercent: 0.08, textTemplate: 'Фаза 1/4: Zapret 1 - {msg}' },
        onCancel: 'Отменено',
        onError: () => {
          document.getElementById('testProgressText').textContent = 'Ошибка (Zapret 1)';
          this.clearElapsedTimer();
        },
      }
    );
  },

  checkZapret1Again() {
    document.getElementById('needZapret1Status').textContent = 'Проверка...';
    document.getElementById('checkZapret1Btn').disabled = true;
    this._startTesterAction(
      { action: 'check-winws' },
      {
        onResult: (d) => {
          document.getElementById('checkZapret1Btn').disabled = false;
          if (d.running) {
            document.getElementById('needZapret1Overlay').classList.remove('open');
            document.getElementById('testProgress').style.display = 'block';
            document.getElementById('testLiveResults').style.display = 'block';
            this.runFullPipelinePhase0();
          } else {
            document.getElementById('needZapret1Status').textContent = 'winws.exe всё ещё не обнаружен. Запустите батник и нажмите Продолжить.';
          }
        },
        onError: () => {
          document.getElementById('checkZapret1Btn').disabled = false;
          document.getElementById('needZapret1Status').textContent = 'Ошибка связи';
        },
      }
    );
  },

  cancelNeedZapret1() {
    document.getElementById('needZapret1Overlay').classList.remove('open');
    document.getElementById('testResultsBody').innerHTML = '';
    this.clearElapsedTimer();
    this.resetToIntro();
  },

  skipNeedZapret1() {
    document.getElementById('needZapret1Overlay').classList.remove('open');
    this.resetTestUI();
    this.startElapsedTimer();
    this.state.currentResults = null;
    this.runFullPipelinePhase1();
  },

  // ── Phase 1: Naked ──
  runFullPipelinePhase1() {
    document.getElementById('testProgressFill').style.width = '8%';
    document.getElementById('testProgressText').textContent = 'Фаза 2/4: остановка защиты (naked)...';
    this.updatePhaseIndicator(1, true);

    this._startTesterAction(
      { action: 'naked', skip_cdn: !this.state.cdnTest },
      {
        resultType: 'naked_result',
        progressConfig: { startPercent: 8, scalePercent: 0.07, textTemplate: 'Фаза 2/4: naked - {msg}' },
        onResult: (d) => { this.state.nakedResults = d; this.runFullPipelinePhase2(); },
        onCancel: 'Отменено',
        onError: () => {
          document.getElementById('testProgressText').textContent = 'Ошибка (naked)';
          this.clearElapsedTimer();
        },
      }
    );
  },

  // ── Phase 2: Zapret 2 Quick Test ──
  runBasicPhase2() {
    this.clearTestLog();
    this.resetTestUI();
    this.updatePhaseIndicator(0, false);
    this.startElapsedTimer();
    document.getElementById('testProgressText').textContent = 'Тест всех стратегий Zapret 2...';

    this._startTesterAction(
      { action: 'test_profiles', profiles: PROFILES, skip_cdn: !this.state.cdnTest },
      {
        resultType: 'result',
        progressConfig: { startPercent: 0, scalePercent: 1, textTemplate: '{msg}' },
        onResult: (d) => { this.state.phase2Results = d; this.finalizePipeline('basic'); },
        onCancel: 'Отменено',
        onError: () => {
          document.getElementById('testProgressText').textContent = 'Ошибка теста';
          this.clearElapsedTimer();
        },
      }
    );
  },

  runFullPipelinePhase2() {
    document.getElementById('testProgressFill').style.width = '15%';
    document.getElementById('testProgressText').textContent = 'Фаза 3/4: быстрый тест с Zapret 2...';
    this.updatePhaseIndicator(2, true);

    this._startTesterAction(
      { action: 'test_profiles', profiles: PROFILES, skip_cdn: !this.state.cdnTest },
      {
        resultType: 'result',
        progressConfig: { startPercent: 15, scalePercent: 0.1, textTemplate: 'Фаза 3/4: {msg}' },
        onResult: (d) => { this.state.phase2Results = d; this.runFullPipelinePhase3(); },
        onCancel: 'Отменено',
        onError: () => {
          document.getElementById('testProgressText').textContent = 'Ошибка теста';
          this.clearElapsedTimer();
        },
      }
    );
  },

  // ── Phase 3: Full Analysis ──
  runFullPipelinePhase3() {
    if (!PROFILES.length) {
      document.getElementById('testProgressText').textContent = 'Нет профилей для анализа';
      this.clearElapsedTimer();
      return;
    }
    document.getElementById('testProgressFill').style.width = '25%';
    document.getElementById('testProgressText').textContent = 'Фаза 4/4: полный анализ профилей...';
    this.updatePhaseIndicator(3, true);

    this._startTesterAction(
      { action: 'full_analysis', profiles: PROFILES },
      {
        progressConfig: { startPercent: 25, scalePercent: 0.35, textTemplate: 'Фаза 4/4: {msg}' },
        onIntermediate: (item) => {
          const lbl = item.profile + (item.blob ? ' + ' + item.blob : '');
          const scVal = item.success_rate != null ? item.success_rate : 0;
          const sc = scVal >= 80 ? 'OK' : scVal >= 40 ? 'WARN' : 'FAIL';
          this.addTestLog(lbl + ' score=' + scVal.toFixed(0) + ' ' + sc + (item.error ? ' ERROR: ' + item.error : ''));
        },
        onCancel: 'Отменено',
        onError: () => {
          document.getElementById('testProgressText').textContent = 'Ошибка анализа';
          this.clearElapsedTimer();
        },
      }
    );
  },

  // ── Live Results Table ──
  addTestResultRow: createBatchProcessor(function(batch) {
    for (const data of batch) {
      TesterPage._addResultRowImmediate(data);
    }
  }, 80),

  _addResultRowImmediate(data) {
    const tbody = document.getElementById('testResultsBody');
    const rowKey = (data.domain || '') + '|' + (data.test_type || '');
    const safeKey = rowKey.replace(/[^a-zA-Z0-9_-]/g, '_');
    const existing = document.getElementById('tr-' + safeKey);

    const code = data.status_code || (data.status === 'TCP16_20' || data.status === 'DPI_DROP' ? '⚠ DPI' : '—');
    const statusDesc = this.getStatusDescription(data.status);
    const codeDesc = this.getCodeDescription(code);

    if (existing) {
      existing.className = this.getRowClass(data.status) + (data.alias ? ' row-alias' : '');
      existing.dataset.domain = data.domain || '';
      existing.dataset.status = data.status || '';
      existing.dataset.time = data.time_ms != null ? String(data.time_ms) : '0';
      const cells = existing.querySelectorAll('td');
      if (cells.length >= 6) {
        cells[0].innerHTML = `<span title="${escapeHtml(statusDesc)}">${this.getStatusIcon(data.status)}</span>`;
        cells[3].innerHTML = `<span title="${escapeHtml(codeDesc)}">${escapeHtml(String(code))}</span>`;
        cells[4].innerHTML = data.time_ms != null ? this.formatTimeColored(data.time_ms) : '<span class="time-ms" style="color:var(--text-secondary)">...</span>';
        cells[5].textContent = data.error || '';
      }
      return;
    }

    const tr = document.createElement('tr');
    tr.id = 'tr-' + safeKey;
    tr.className = this.getRowClass(data.status) + (data.alias ? ' row-alias' : '');
    tr.dataset.domain = data.domain || '';
    tr.dataset.status = data.status || '';
    tr.dataset.time = data.time_ms != null ? String(data.time_ms) : '0';
    tr.innerHTML = `
      <td style="text-align:center;font-size:16px" title="${escapeHtml(statusDesc)}">${this.getStatusIcon(data.status)}</td>
      <td style="font-weight:500">${escapeHtml(data.domain)}${data.alias ? ' <span class="badge badge-alias">al.</span>' : ''}${data.cdn_provider ? ' <span class="badge badge-cdn">' + escapeHtml(data.cdn_provider) + '</span>' : ''}</td>
      <td>${this.getTestTypeBadge(data.test_type)}</td>
      <td style="font-size:12px" title="${escapeHtml(codeDesc)}">${escapeHtml(String(code))}</td>
      <td>${data.time_ms != null ? this.formatTimeColored(data.time_ms) : '<span class="time-ms" style="color:var(--text-secondary)">...</span>'}</td>
      <td><div class="cell-error">${escapeHtml(data.error || '')}</div></td>
    `;
    tbody.appendChild(tr);
  },

  sortLiveTable(key, colIdx) {
    const tbody = document.getElementById('testResultsBody');
    if (!tbody) return;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    if (!rows.length) return;

    const sort = this.state.liveTableSort;
    if (sort.key === key) sort.dir = -sort.dir;
    else { sort.key = key; sort.dir = 1; }

    const dir = sort.dir;
    rows.sort((a, b) => {
      let av, bv;
      if (key === 'domain') { av = a.dataset.domain || ''; bv = b.dataset.domain || ''; return av.localeCompare(bv) * dir; }
      if (key === 'status') { av = a.dataset.status || ''; bv = b.dataset.status || ''; return av.localeCompare(bv) * dir; }
      if (key === 'time') { av = parseFloat(a.dataset.time || '0'); bv = parseFloat(b.dataset.time || '0'); return (av - bv) * dir; }
      return 0;
    });
    rows.forEach(r => tbody.appendChild(r));

    const table = tbody.closest('table');
    if (table) {
      table.querySelectorAll('th').forEach(th => th.classList.remove('sorted-asc', 'sorted-desc'));
      const ths = table.querySelectorAll('th');
      if (ths[colIdx]) ths[colIdx].classList.add(dir === 1 ? 'sorted-asc' : 'sorted-desc');
    }
  },

  // ── Result Grid (tiles) ──
  renderResultGrid(results) {
    if (!results || !results.length) return '';
    const domainMap = {};
    for (const r of results) {
      if (!r.results) continue;
      for (const rr of r.results) {
        if (rr.test_type === 'ping') continue;
        const key = rr.domain;
        if (!domainMap[key]) domainMap[key] = { domain: key, results: [], bestStatus: '', bestTime: Infinity, testTypes: new Set() };
        domainMap[key].results.push(rr);
        domainMap[key].testTypes.add(rr.test_type || '?');
        if (rr.time_ms != null && rr.time_ms < domainMap[key].bestTime) domainMap[key].bestTime = rr.time_ms;
        const rank = { 'OK': 5, 'PARTIAL': 4, 'SSL_ERROR': 4, 'TCP16_20': 3, 'DPI_DROP': 3, 'TIMEOUT': 2, 'BLOCKED': 1, 'ERROR': 1, 'FAIL': 1 };
        const cur = domainMap[key].bestStatus || '';
        if (!cur || (rank[rr.status] || 0) > (rank[cur] || 0)) domainMap[key].bestStatus = rr.status;
      }
    }

    const domainIcons = {
      'youtube.com': '▶', 'discord.com': '💬', 'googlevideo.com': '📺',
      'discordapp.net': '💬', 'ea.com': '🎮', 'steampowered.com': '🕹',
      'reddit.com': '📱', 'google.com': '🔍', 'gateway.discord.gg': '💬',
      'youtu.be': '▶', 'github.com': '🐙', 'xbox.com': '🎮',
      'playstation.com': '🎮', 'origin.com': '🎮', 'epicgames.com': '🎮',
      'steamcommunity.com': '🕹'
    };

    function tileClass(status) {
      if (status === 'OK' || status === 'OK_BLOCKED') return 'status-ok';
      if (status === 'PARTIAL' || status === 'SSL_ERROR') return 'status-partial';
      if (status === 'TCP16_20' || status === 'DPI_DROP') return 'status-dpi';
      if (status === 'TIMEOUT' || status === 'BLOCKED' || status === 'FAIL' || status === 'ERROR') return 'status-fail';
      return 'status-unknown';
    }

    function tileStatusText(status) {
      if (status === 'OK' || status === 'OK_BLOCKED') return '✓ Доступен';
      if (status === 'PARTIAL') return '⚠ Частично';
      if (status === 'SSL_ERROR') return '🔒 SSL';
      if (status === 'TCP16_20' || status === 'DPI_DROP') return '✗ DPI';
      if (status === 'TIMEOUT') return '⏱ Таймаут';
      if (status === 'BLOCKED' || status === 'FAIL') return '✗ Блокировка';
      if (status === 'ERROR') return '✗ Ошибка';
      return '?';
    }

    const tiles = Object.values(domainMap).map((d, i) => {
      const cls = tileClass(d.bestStatus);
      const icon = domainIcons[d.domain] || '🌐';
      const time = d.bestTime < Infinity ? this.formatTimeColored(d.bestTime) : '';
      const badges = Array.from(d.testTypes).map(t => this.getTestTypeBadge(t)).join('');
      return `<div class="result-tile ${cls}" style="animation-delay:${i * 50}ms">
        <div class="tile-icon">${icon}</div>
        <div class="tile-domain">${escapeHtml(d.domain)}</div>
        <div class="tile-status">${tileStatusText(d.bestStatus)}</div>
        ${time ? '<div class="tile-time">' + time + '</div>' : ''}
        <div class="tile-badges">${badges}</div>
      </div>`;
    }).join('');

    return '<div class="result-grid">' + tiles + '</div>';
  },

  // ── Summary & Comparison ──
  showComparison() {
    const cur = this.state.currentResults;
    const naked = this.state.nakedResults;
    const fullAnalysis = this.state.fullAnalysisResults;

    let zapret2Score = 0;
    let zapret2BestProfile = '';
    const rateOf = r => (r.network_rate != null ? r.network_rate : (r.success_rate || 0));
    if (fullAnalysis && fullAnalysis.length > 0) {
      const best = fullAnalysis.reduce((a, b) => rateOf(a) > rateOf(b) ? a : b);
      zapret2Score = rateOf(best);
      zapret2BestProfile = best.profile || '';
    } else if (this.state.phase2Results && this.state.phase2Results.network_rate != null) {
      zapret2Score = this.state.phase2Results.network_rate || 0;
      zapret2BestProfile = this.state.phase2Results.profile || '';
    }

    function okText(r) { if (!r) return '—'; const o = r.ok_count || 0; const t = o + (r.fail_count || 0); return o + '/' + t + ' OK'; }
    function weighted(r) { return r ? (r.success_rate || 0) : 0; }

    const curS = weighted(cur);
    const nakedS = weighted(naked);
    const improvementNaked = nakedS > 0 ? ((zapret2Score - nakedS) / nakedS * 100).toFixed(0) : '∞';
    const improvementCur = curS > 0 ? ((zapret2Score - curS) / curS * 100).toFixed(0) : (cur && !cur.skipped ? '∞' : '—');
    const impNakedPositive = improvementNaked === '∞' || parseFloat(improvementNaked) >= 0;
    const impCurPositive = improvementCur === '—' || improvementCur === '∞' || parseFloat(improvementCur) >= 0;

    const html = `<div class="card accent">
      <h3>📊 Сравнение: Zapret 1 → Naked → Zapret 2</h3>
      <div class="comparison-grid">
        <div class="comparison-card">
          <div class="label">Текущий Zapret</div>
          <div class="score" style="color:${scoreColor(curS)}">${curS.toFixed(2)}</div>
          <div class="cmp-bar-wrap"><div class="cmp-bar-fill" data-target="${(curS * 100).toFixed(0)}" style="width:0%;background:${scoreColor(curS)}"></div></div>
          <div class="ok-text">${okText(cur)}</div>
        </div>
        <div class="comparison-card">
          <div class="label">Naked (без защиты)</div>
          <div class="score" style="color:${scoreColor(nakedS)}">${nakedS.toFixed(2)}</div>
          <div class="cmp-bar-wrap"><div class="cmp-bar-fill" data-target="${(nakedS * 100).toFixed(0)}" style="width:0%;background:${scoreColor(nakedS)}"></div></div>
          <div class="ok-text">${okText(naked)}</div>
        </div>
        <div class="comparison-card">
          <div class="label">Zapret 2 (лучший)</div>
          <div class="score" style="color:${scoreColor(zapret2Score)}">${zapret2Score.toFixed(2)}</div>
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">${zapret2BestProfile ? escapeHtml(zapret2BestProfile) : '—'}</div>
          <div class="cmp-bar-wrap"><div class="cmp-bar-fill" data-target="${(zapret2Score * 100).toFixed(0)}" style="width:0%;background:${scoreColor(zapret2Score)}"></div></div>
          <div class="cmp-arrow ${impNakedPositive ? 'pos' : 'neg'}">${impNakedPositive ? '↑' : '↓'} ${improvementNaked}% vs naked</div>
          <div class="cmp-arrow ${impCurPositive ? 'pos' : 'neg'}">${improvementCur === '—' ? '— нет данных Zapret 1' : (impCurPositive ? '↑ ' : '↓ ') + improvementCur + '% vs Zapret 1'}</div>
        </div>
      </div>
    </div>`;

    // Quick-test details: show all 3 default profiles if available
    const quickResults = this.state.phase2Results && this.state.phase2Results.all_results;
    if (quickResults && quickResults.length) {
      const rows = quickResults.map(r => {
        const rate = r.network_rate != null ? r.network_rate : (r.success_rate || 0);
        const ws = rate.toFixed(0);
        const isBest = r.profile === zapret2BestProfile;
        return `<tr class="${isBest ? 'score-row-good' : ''}">
          <td>${escapeHtml(r.profile || '')}${isBest ? ' <span class="badge badge-safe">best</span>' : ''}</td>
          <td style="color:${scoreColor(rate)};font-weight:700">${ws}</td>
          <td>${r.net_ok_count != null ? r.net_ok_count + '/' + r.net_total : (r.ok_count || 0) + '/' + ((r.ok_count || 0) + (r.fail_count || 0))}</td>
          <td>${r.provider_hop ? 'hop ' + escapeHtml(String(r.provider_hop)) : '—'}</td>
        </tr>`;
      }).join('');
      html += `
      <div class="card">
        <h3>🔬 Результаты быстрого теста</h3>
        <p style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">Протестированы 8 стратегий. Лучшая выбрана автоматически.</p>
        <div class="table-wrapper">
          <table class="live-table analysis-table">
            <thead><tr><th>Профиль</th><th>Доступность</th><th>OK</th><th>Hop</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
    }

    const container = document.getElementById('testResults');
    container.innerHTML = html + container.innerHTML;
    requestAnimationFrame(() => {
      container.querySelectorAll('.cmp-bar-fill[data-target]').forEach(bar => {
        bar.style.width = clamp(parseFloat(bar.dataset.target), 0, 100) + '%';
      });
    });
  },

  showFullAnalysisTable(allResults) {
    if (!allResults || !allResults.length) return;
    const container = document.getElementById('testResults');
    const rows = allResults.map((r, i) => {
      const rate = r.network_rate != null ? r.network_rate : (r.success_rate || 0);
      const ws = rate.toFixed(0);
      let medal = '';
      if (i === 0) medal = 'medal-gold';
      else if (i === 1) medal = 'medal-silver';
      else if (i === 2) medal = 'medal-bronze';
      let scoreRow = '';
      if (rate >= 80) scoreRow = 'score-row-good';
      else if (rate >= 40) scoreRow = 'score-row-mid';
      else scoreRow = 'score-row-bad';
      return `<tr class="${medal} ${scoreRow}">
        <td>${escapeHtml(r.profile)}</td>
        <td>${r.blob ? escapeHtml(r.blob) : '—'}</td>
        <td style="color:${scoreColor(rate)};font-weight:700">${ws}</td>
        <td>${r.net_ok_count != null ? r.net_ok_count + '/' + r.net_total : (r.ok_count || 0) + '/' + ((r.ok_count || 0) + (r.fail_count || 0))}</td>
        <td>${r.provider_hop ? escapeHtml(String(r.provider_hop)) : '—'}</td>
      </tr>`;
    }).join('');

    container.innerHTML += `
      <div class="card">
        <h3>🔬 Результаты полного анализа</h3>
        <div class="table-wrapper">
          <table class="live-table analysis-table">
            <thead>
              <tr>
                <th>Профиль</th>
                <th>Blob</th>
                <th>Доступность</th>
                <th>OK</th>
                <th>Hop</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
  },

  _renderTop3(results) {
    if (!results || results.length < 3) return '';
    const rate = r => (r.network_rate != null ? r.network_rate : (r.success_rate || 0));
    const sorted = [...results].sort((a, b) => rate(b) - rate(a));
    const top3 = sorted.slice(0, 3);
    const rows = top3.map((r, i) => {
      const labels = ['🥇', '🥈', '🥉'];
      const ws = (r.network_rate != null ? r.network_rate : (r.success_rate || 0)).toFixed(0);
      return `<tr>
        <td style="font-size:18px;text-align:center">${labels[i]}</td>
        <td><strong>${escapeHtml(r.profile || '')}</strong>${r.blob ? ' + ' + escapeHtml(r.blob) : ''}</td>
        <td style="color:${scoreColor(r.network_rate != null ? r.network_rate : (r.success_rate || 0))};font-weight:700">${ws}</td>
        <td>${r.net_ok_count != null ? r.net_ok_count + '/' + r.net_total : (r.ok_count || 0) + '/' + ((r.ok_count || 0) + (r.fail_count || 0))}</td>
      </tr>`;
    }).join('');
    return `<div class="card">
      <h3>🏆 Топ 3 рекомендуемых стратегии</h3>
      <div class="table-wrapper">
        <table class="live-table analysis-table">
          <thead><tr><th style="width:40px"></th><th>Профиль</th><th>Score</th><th>OK</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p style="font-size:12px;color:var(--text-secondary);margin-top:8px">Рекомендуется выбрать стратегию с наибольшим score. Если score одинаков — предпочтительнее с большим OK.</p>
    </div>`;
  },

  // ── Finalize ──
  finalizePipeline(mode) {
    document.getElementById('testProgressFill').style.width = '100%';
    document.getElementById('testProgressText').textContent = 'Готово!';
    const step = mode === 'basic' ? 1 : 4;
    this.updatePhaseIndicator(step, mode !== 'basic');

    this.clearElapsedTimer();
    document.getElementById('btnStartTest').disabled = false;

    let html = '';
    const phase2 = this.state.phase2Results;

    if (mode === 'basic') {
      const allResults = phase2 && phase2.all_results;
      const rec = phase2 && phase2.recommendation;
      const naked = phase2 && phase2.naked;

      // ── Verdict card (top) ──
      if (rec) {
        const vmeta = {
          ok:            { icon: '✅', title: 'Работает', cls: 'verdict-ok' },
          partial:       { icon: '⚠️', title: 'Частично', cls: 'verdict-partial' },
          no_bypass:     { icon: '❌', title: 'Не пробито', cls: 'verdict-fail' },
          engine_broken: { icon: '🔧', title: 'Проблема с движком', cls: 'verdict-fail' },
          no_data:       { icon: '➖', title: 'Нет данных', cls: 'verdict-neutral' },
        };
        const vm = vmeta[rec.verdict] || vmeta.no_data;
        let keyHtml = '';
        if (rec.key_hosts && rec.key_hosts.length) {
          keyHtml = '<div class="key-hosts">' + rec.key_hosts.map(k => {
            const isQuirk = k.status === 'QUIC_OK';
            const ok = k.status === 'OK' || isQuirk;
            const t = k.time_ms ? this.formatTimeColored(k.time_ms) : '';
            const note = k.note || ((k.domain === 'www.youtube.com' && !ok)
              ? 'известный TLS-прикол: в браузере YouTube работает через QUIC' : '');
            return `<div class="key-host ${ok ? 'key-host-ok' : 'key-host-fail'}">
              <span class="kh-icon">${ok ? '✅' : '❌'}</span>
              <span class="kh-label">${escapeHtml(k.label)}</span>
              <span class="kh-status">${ok ? (isQuirk ? 'работает (QUIC)' : 'доступен') : 'не пробит'}</span>
              ${t ? '<span class="kh-time">' + t + '</span>' : ''}${note ? '<div class="kh-note">' + escapeHtml(note) + '</div>' : ''}</div>`;
          }).join('') + '</div>';
        }
        html += `<div class="card ${vm.cls}">
          <h3>${vm.icon} Итог теста: ${vm.title}${rec.best_profile ? ' — лучшая: <b>' + escapeHtml(rec.best_profile) + '</b>' : ''}</h3>
          <p class="verdict-message">${escapeHtml(rec.message || '')}</p>
          ${keyHtml}
          <div class="verdict-actions" style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
            ${rec.best_profile ? `<button class="btn btn-primary" onclick="TesterPage.applyRecommended()">🚀 Запустить: ${escapeHtml(rec.best_profile)}</button>` : ''}
            ${(rec.verdict === 'no_bypass' || rec.verdict === 'engine_broken') ? `<button class="btn btn-secondary" onclick="location.hash='#diagnostics'">🔍 Проверить систему</button>` : ''}
            ${rec.same_as_naked ? `<span style="font-size:12px;color:var(--warn);align-self:center">результат совпадает с голым тестом</span>` : ''}
          </div>
        </div>`;
      }

      // ── Personal strategy card (aggregated segments) — INFO ONLY, no run button:
//    the primary action lives in the verdict card (best profile).  If custom
//    is the best, the verdict button already points at it.
      const custom = phase2 && phase2.custom;
      if (custom && custom.summary && custom.valid) {
        const src = custom.sources || {};
        const chips = Object.keys(src).map(f =>
          `<span class="badge" style="margin-right:6px">${escapeHtml(f)} ← ${escapeHtml(src[f])}</span>`).join('');
        const rel = custom.relation === 'better' ? 'обгоняет лучшую'
          : custom.relation === 'worse' ? 'уступает лучшей'
          : (custom.rate != null ? 'равна лучшей' : '');
        const isBest = rec && rec.best_profile === 'custom';
        html += `<div class="card verdict-partial">
          <h3>🧬 Личная стратегия «custom»${rel ? ` <span style="font-size:12px;color:var(--warn)">(${rel}${custom.rate != null ? ', ' + custom.rate + '%' : ''})</span>` : ''}</h3>
          <p style="font-size:14px;margin:8px 0">${escapeHtml(custom.summary)}</p>
          <div style="margin:6px 0 12px">${chips}</div>
          ${isBest ? '<p style="font-size:12px;color:var(--text-secondary);margin:0">Запуск — кнопкой выше (лучшая стратегия).</p>' : ''}
        </div>`;
      }

      // ── Results table ──
      if (allResults && allResults.length) {
        const bestProfile = rec && rec.best_profile;
        html += '<div class="card"><h3>📊 Результаты теста</h3><div class="table-wrapper"><table class="live-table analysis-table"><thead><tr><th>Профиль</th><th>Доступность</th><th>OK</th><th>Пинги</th><th>Hop</th></tr></thead><tbody>';
        for (const r of allResults) {
          const ws = r.network_rate != null ? r.network_rate.toFixed(0) : '0';
          const isBest = r.profile === bestProfile;
          const cls = parseFloat(ws) >= 70 ? 'score-row-good' : parseFloat(ws) >= 40 ? 'score-row-mid' : 'score-row-bad';
          const okTxt = r.net_ok_count != null ? r.net_ok_count + '/' + r.net_total : (r.ok_count || 0) + '/' + ((r.ok_count || 0) + (r.fail_count || 0));
          const pings = (r.ping_ok_count != null ? r.ping_ok_count : 0) + '/' + (r.ping_total != null ? r.ping_total : 0);
          html += `<tr class="${cls}"><td>${escapeHtml(r.profile || '')}${isBest ? ' <span class="badge badge-safe">best</span>' : ''}</td><td style="color:${scoreColor(r.network_rate != null ? r.network_rate : 0)};font-weight:700">${ws}%</td><td>${okTxt}</td><td>${pings}</td><td>${r.provider_hop ? 'hop ' + escapeHtml(String(r.provider_hop)) : '—'}</td></tr>`;
        }
        html += '</tbody></table></div>';
        if (bestProfile) {
          html += `<p style="margin-top:10px;font-size:14px">Рекомендуемая стратегия: <strong>${escapeHtml(bestProfile)}</strong></p>`;
        }
        html += '</div>';
      }

      // ── Blocked domains (nothing bypassed them) ──
      if (rec && rec.blocked_domains && rec.blocked_domains.length && rec.verdict !== 'ok') {
        html += '<div class="card"><h3>🚫 Не пробито ни одной стратегией</h3><div class="blocked-list">' +
          rec.blocked_domains.map(d => `<span class="blocked-chip">${escapeHtml(d)}</span>`).join('') +
          '</div></div>';
      }

      // ── Naked baseline note ──
      if (naked && naked.net_total) {
        html += `<div class="card"><h3>🌐 Базовый уровень (без защиты)</h3><p style="font-size:13px;color:var(--text-secondary);margin:0">Доступно без zapret: <b>${naked.net_ok_count}/${naked.net_total}</b> (${(naked.network_rate || 0).toFixed(0)}%). Если стратегии дают тот же результат — обход не применяется.</p></div>`;
      }

      // ── Domain grid + Top 3 ──
      html += '<div class="card"><h3>🔍 Результаты по доменам (лучшая стратегия)</h3>' + this.renderResultGrid(allResults) + '</div>';
      html += this._renderTop3(allResults);
    } else {
      // Advanced mode: showComparison + showFullAnalysisTable already ran inside Phase 3 handler
      html = document.getElementById('testResults').innerHTML;
      // Top 3 from full analysis
      const fa = this.state.fullAnalysisResults;
      if (fa && fa.length >= 3) {
        html += this._renderTop3(fa);
      }
    }

    // Save report button
    if (this.state.collectLogs) {
      html += `<div class="card" style="text-align:center;padding:16px">
        <button class="btn btn-primary" onclick="TesterPage.showCollectForm()">💾 Сохранить отчёт</button>
        <p style="font-size:11px;color:var(--text-secondary);margin-top:8px">Сохранит ZIP-архив с результатами теста для отправки <strong>TheFirstNoob</strong></p>
      </div>`;
    }

    html += `<div class="card" style="text-align:center;padding:16px">
      <button class="btn btn-secondary" onclick="TesterPage.resetToIntro()">← Вернуться к тестеру</button>
    </div>`;

    document.getElementById('testProgress').style.display = 'none';
    document.getElementById('testLiveResults').style.display = 'none';
    document.getElementById('testSummary').style.display = 'none';
    document.getElementById('testResults').innerHTML = html;
  },

  // ── Export Report (triggered by button) ──
  async saveReport() {
    const city = document.getElementById('collectCity').value.trim();
    const isp = document.getElementById('collectIsp').value.trim();
    const consent = document.getElementById('collectConsent').checked;
    if (!consent) { showToast('Отметьте согласие на сбор данных', 'warning'); return; }

    document.getElementById('collectSubmitBtn').disabled = true;
    document.getElementById('collectSubmitBtn').textContent = '⏳ Сохранение...';

    const cur = this.state.currentResults;
    const naked = this.state.nakedResults;
    const phase2 = this.state.phase2Results;

    const body = {
      consent, city, isp,
      vpn_active: this.state.vpnActive || false,
      zapret1_strategy: '',
      zapret1_cmdline: (cur && cur.zapret1_cmdline) || '',
      phase0_results: cur ? { ok_count: cur.ok_count, fail_count: cur.fail_count, success_rate: cur.success_rate, success_rate: cur.success_rate, total_time_ms: cur.total_time_ms, results: cur.results, cdn_results: cur.cdn_results } : { skipped: true },
      phase1_results: naked ? { ok_count: naked.ok_count, fail_count: naked.fail_count, success_rate: naked.success_rate, success_rate: naked.success_rate, total_time_ms: naked.total_time_ms, results: naked.results, cdn_results: naked.cdn_results } : null,
      phase2_results: phase2 ? (phase2.full_analysis ? { full_analysis: phase2.full_analysis || [], best: phase2.full_analysis && phase2.full_analysis.length ? { profile: phase2.full_analysis[0].profile, success_rate: phase2.full_analysis[0].success_rate, success_rate: phase2.full_analysis[0].success_rate, ok_count: phase2.full_analysis[0].ok_count, fail_count: phase2.full_analysis[0].fail_count, provider_hop: phase2.full_analysis[0].provider_hop, provider_ip: phase2.full_analysis[0].provider_ip, results: phase2.full_analysis[0].results } : null } : { profile: phase2.profile, ok_count: phase2.ok_count, fail_count: phase2.fail_count, success_rate: phase2.success_rate, success_rate: phase2.success_rate, total_time_ms: phase2.total_time_ms, provider_hop: phase2.provider_hop, provider_ip: phase2.provider_ip, results: phase2.results, cdn_results: phase2.cdn_results, all_results: phase2.all_results || [] }) : null,
      mode: this.state.advancedTest ? 'full' : 'basic',
    };

    if (this.state.collectBatFile) {
      try { const b64 = await this.fileToBase64(this.state.collectBatFile); body.zapret1_strategy = b64; body.zapret1_filename = this.state.collectBatFile.name; } catch (e) {}
    }

    try {
      const r = await fetch('/api/export-report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json();
      if (d.status === 'ok') {
        try { await fetch('/api/stop', { method: 'POST' }); } catch (e) {}
        this.closeCollectForm();
        const fileName = (d.file || '').split('\\').pop() || 'report.zip';
        document.getElementById('testResults').innerHTML =
          `<div class="card ok" style="text-align:center;padding:28px">
            <div style="font-size:42px;margin-bottom:14px">✅</div>
            <h2 style="margin-bottom:10px">Спасибо за тестирование!</h2>
            <p style="color:var(--text-secondary);font-size:14px;margin-bottom:16px">Файл <code>${escapeHtml(fileName)}</code> сохранён в папке программы.</p>
            <button class="btn btn-secondary mt-2" onclick="TesterPage.resetToIntro()">← Вернуться к тестеру</button>
          </div>`;
      } else {
        throw new Error(d.message || 'Ошибка');
      }
    } catch (e) {
      showToast('Ошибка: ' + e.message, 'error');
      document.getElementById('collectSubmitBtn').disabled = false;
      document.getElementById('collectSubmitBtn').textContent = '💾 Сохранить';
    }
  },

  fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const b64 = reader.result.split(',')[1];
        resolve(b64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  },

  cancelTest() {
    fetch('/api/tester/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'cancel' }),
    }).catch(() => {});
    document.getElementById('testProgressText').textContent = 'Отменено';
    this.clearElapsedTimer();
    setTimeout(() => this.resetToIntro(), 1500);
  },

  async applyRecommended() {
    const rec = this.state.phase2Results && this.state.phase2Results.recommendation;
    const profile = rec && rec.best_profile;
    if (!profile) { showToast('Нет рекомендации', 'warn'); return; }
    try {
      const r = await apiPost('/start', { profile });
      if (r.status === 'ok') showToast('Запущена стратегия: ' + profile, 'ok');
      else showToast(r.message || 'Ошибка запуска', 'error');
    } catch (e) {
      showToast('Ошибка: ' + e.message, 'error');
    }
  },

  async applyCustom() {
    try {
      const r = await apiPost('/start', { profile: 'custom' });
      if (r.status === 'ok') showToast('Запущена личная стратегия: custom', 'ok');
      else showToast(r.message || 'Ошибка запуска', 'error');
    } catch (e) {
      showToast('Ошибка: ' + e.message, 'error');
    }
  },

  resetToIntro() {
    document.getElementById('testerIntro').style.display = 'block';
    document.getElementById('testProgress').style.display = 'none';
    document.getElementById('testLiveResults').style.display = 'none';
    document.getElementById('testSummary').style.display = 'none';
    document.getElementById('testResults').innerHTML = '';
    document.getElementById('testResultsBody').innerHTML = '';
    document.getElementById('btnStartTest').disabled = false;
    this.clearElapsedTimer();
  }
};

// ── Diagnostics Page ──
const DiagnosticsPage = {
  lastReportText: '',

  async run() {
    const btn = document.getElementById('diagRunBtn');
    const results = document.getElementById('diagResults');
    const summary = document.getElementById('diagSummary');
    const copyBtn = document.getElementById('diagCopyBtn');
    copyBtn.style.display = 'none';
    btn.disabled = true;
    btn.textContent = 'Проверяю...';
    const diagMsg = document.getElementById('diagResults');
    const t0 = Date.now();
    diagMsg.innerHTML = '<p style="color:var(--text-secondary)">⏳ Выполняется проверка... <b id="diagTimer">0</b> сек</p>';
    const timerId = setInterval(() => {
      const el = document.getElementById('diagTimer');
      if (el) el.textContent = Math.round((Date.now() - t0) / 1000);
    }, 1000);
    summary.innerHTML = '';
    try {
      const r = await apiPost('/diagnose', {});
      if (r.status !== 'ok' || !r.report) throw new Error(r.message || 'ошибка');
      clearInterval(timerId);
      this.render(r.report);
    } catch (e) {
      clearInterval(timerId);
      results.innerHTML = `<p style="color:#e74c3c">Ошибка диагностики: ${escapeHtml(String(e.message || e))}</p>`;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Запустить проверку';
    }
  },

  render(report) {
    const icons = { ok: '✅', warn: '⚠️', fail: '❌', skip: '➖' };
    const colors = { ok: 'var(--ok, #2ecc71)', warn: 'var(--warn, #f39c12)', fail: 'var(--fail, #e74c3c)', skip: 'var(--text-secondary, #888)' };
    const s = report.summary || {};
    const sEl = document.getElementById('diagSummary');
    sEl.innerHTML =
      `<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:14px;">` +
      `<span>✅ OK: <b>${s.ok || 0}</b></span>` +
      `<span>⚠️ Внимание: <b>${s.warn || 0}</b></span>` +
      `<span>❌ Ошибки: <b>${s.fail || 0}</b></span>` +
      `<span style="color:var(--text-secondary)">(${report.elapsed_sec} сек, ${escapeHtml(report.timestamp || '')})</span></div>`;

    const rows = (report.checks || []).map(c => (
      `<div style="display:flex;gap:10px;align-items:flex-start;padding:9px 4px;border-bottom:1px solid var(--border, #333);">` +
      `<span style="font-size:16px">${icons[c.status] || '❓'}</span>` +
      `<div style="flex:1"><b style="font-size:13px">${escapeHtml(c.name)}</b>` +
      (c.detail ? `<div style="color:var(--text-secondary);font-size:12px;margin-top:2px;">${escapeHtml(c.detail)}</div>` : '') +
      `</div></div>`
    )).join('');
    document.getElementById('diagResults').innerHTML = rows || '<p>Нет результатов</p>';

    // Cross-link: failures detected → offer the strategy picker
    if ((s.fail || 0) > 0) {
      document.getElementById('diagResults').innerHTML += `
        <div class="card" style="margin-top:12px;padding:14px">
          <p style="font-size:13px;color:var(--text-secondary);margin:0 0 10px">
            Найдены проблемы. Если нужно подобрать стратегию, которая лучше всего работает на вашем интернете — запустите тест.
          </p>
          <button class="btn btn-primary" onclick="location.hash='#tester'">▶ Подбор стратегии</button>
        </div>`;
    }

    this.lastReportText = report.report_text || '';
    if (this.lastReportText) document.getElementById('diagCopyBtn').style.display = '';
  },

  async copyReport() {
    if (!this.lastReportText) return;
    try {
      await navigator.clipboard.writeText(this.lastReportText);
      showToast('Отчёт скопирован в буфер', 'ok');
    } catch (e) {
      // fallback for non-secure contexts
      const ta = document.createElement('textarea');
      ta.value = this.lastReportText;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); showToast('Отчёт скопирован', 'ok'); }
      catch (e2) { showToast('Не удалось скопировать — выделите текст вручную', 'warn'); }
      document.body.removeChild(ta);
    }
  }
};

// ── Initialize App ──
document.addEventListener('DOMContentLoaded', async () => {
  await App.init();
});
