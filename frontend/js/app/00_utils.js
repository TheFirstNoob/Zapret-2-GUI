/**
 * Zapret2 Manager - frontend.
 * Vanilla JS, single script. Backend contract: /api/* polling.
 */

'use strict';

const APP_TOKEN = window.APP_TOKEN || '__APP_TOKEN__';
const SCORE_OK = 80;
const SCORE_MID = 40;

// QUIC-класс хостов (синхронно с core.tester QUIC_QUIRK_DOMAINS):
// браузер идёт через QUIC, TCP-проба curl-ом под десинком не показательная -
// вне «доступности» и нейтральный серый статус вместо красного креста.
const QUIRK_HOSTS = new Set([
  'www.youtube.com', 'youtu.be', 'i.ytimg.com',
  'redirector.googlevideo.com', 'storage.googleapis.com',
]);

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
  frontendLog('JS ERROR line ' + line + ': ' + msg);
};

// Необработанные отклонённые промисы (аудит 2026-10): раньше молчали -
// хвосты вида «ответ после отмены» тонули в консоли без следа на сервере.
window.addEventListener('unhandledrejection', function (ev) {
  const r = ev && ev.reason;
  const msg = (r && (r.message || r)) || 'unknown';
  console.error('JS REJECTION: ' + msg);
  frontendLog('JS REJECTION: ' + msg);
});

// fire-and-forget лог ошибок на сервер (виден в probe_debug.log).
// Флаги (аудит 2026-10): дубль в 5с отбрасывается, кап 30 сообщений/мин -
// иначе битый поллинг заливал сервер сотнями одинаковых строк.
const _feLogSeen = new Map();
let _feLogSent = 0;
let _feLogWindow = 0;
function frontendLog(msg) {
  try {
    const now = Date.now();
    if (now - _feLogWindow > 60000) {
      _feLogWindow = now; _feLogSent = 0; _feLogSeen.clear();
    }
    const key = String(msg).slice(0, 200);
    if (_feLogSent >= 30) return;
    if (now - (_feLogSeen.get(key) || 0) < 5000) return;
    _feLogSeen.set(key, now);
    _feLogSent++;
    fetch('/api/frontend-log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ msg: key })
    }).catch(() => {});
  } catch (e) { /* noop */ }
}

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

// Локальный backend может задуматься (запуск winws2, sc query) - но не навсегда.
const API_TIMEOUT_MS = 30000;

async function apiGet(path) {
  const r = await fetch('/api' + path, { signal: AbortSignal.timeout(API_TIMEOUT_MS) });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch('/api' + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
    signal: AbortSignal.timeout(API_TIMEOUT_MS),
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

let _toastTimer = null, _toastHideTimer = null;
function showToast(msg, type, action) {
  const t = $('toast');
  // action: {label, onClick} - кнопка внутри тоста (например «Перезапустить сейчас»)
  t.textContent = '';
  const span = document.createElement('span');
  span.textContent = msg;
  t.appendChild(span);
  if (action && action.label) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-sm';
    btn.textContent = action.label;
    btn.addEventListener('click', () => { hideToast(); action.onClick(); });
    t.appendChild(btn);
  }
  t.className = 'toast' + (type ? ' ' + type : '');
  t.hidden = false;
  clearTimeout(_toastHideTimer);
  requestAnimationFrame(() => { t.style.opacity = '1'; });
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(hideToast, 3600);
}

function hideToast() {
  const t = $('toast');
  t.style.opacity = '0';
  clearTimeout(_toastHideTimer);
  _toastHideTimer = setTimeout(() => { t.hidden = true; }, 250);
}

function rateClass(v) {
  return v >= SCORE_OK ? 'st-ok' : v >= SCORE_MID ? 'st-warn' : 'st-err';
}
