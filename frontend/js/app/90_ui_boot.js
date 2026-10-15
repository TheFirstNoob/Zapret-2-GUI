// ── boot ──

// ── Свои подсказки-поповеры: data-popover / data-popover-title ──────
// Системные title не подходят для длинных текстов: долгая задержка,
// нет переносов, нельзя стилизовать. Здесь: hover/focus, Esc, скролл.
const Popover = {
  _el: null, _anchor: null, _timer: null,

  init() {
    document.addEventListener('mouseover', (e) => {
      const t = e.target.closest && e.target.closest('[data-popover]');
      if (t) this._schedule(t, 140);
    });
    document.addEventListener('mouseout', (e) => {
      const t = e.target.closest && e.target.closest('[data-popover]');
      if (t && t.contains(e.relatedTarget)) return;
      if (t) this._cancel(t);
    });
    document.addEventListener('focusin', (e) => {
      const t = e.target.closest && e.target.closest('[data-popover]');
      if (t) this._schedule(t, 0);
    });
    document.addEventListener('focusout', () => this.hide());
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') this.hide(); });
    window.addEventListener('scroll', () => this.hide(), true);
    window.addEventListener('resize', () => this.hide());
  },

  _schedule(anchor, delay) {
    if (this._anchor === anchor && this._el) return;
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    this._timer = setTimeout(() => { this._timer = null; this.show(anchor); }, delay);
  },

  _cancel(anchor) {
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    if (this._anchor === anchor) this.hide();
  },

  show(anchor) {
    const text = anchor.getAttribute('data-popover');
    if (!text) return;
    this.hide();
    const el = document.createElement('div');
    el.className = 'popover';
    const title = anchor.getAttribute('data-popover-title');
    if (title) {
      const t = document.createElement('div');
      t.className = 'popover-title';
      t.textContent = title;
      el.appendChild(t);
    }
    const body = document.createElement('div');
    body.textContent = text;
    el.appendChild(body);
    document.body.appendChild(el);
    this._el = el;
    this._anchor = anchor;

    const r = anchor.getBoundingClientRect();
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const below = r.top < vh / 2;
    let left = Math.round(r.left + r.width / 2 - w / 2);
    let top = below ? r.bottom + 9 : r.top - h - 9;
    left = Math.max(8, Math.min(left, vw - w - 8));
    top = Math.max(8, Math.min(top, vh - h - 8));
    el.style.left = left + 'px';
    el.style.top = top + 'px';
    el.dataset.placement = below ? 'bottom' : 'top';
    const arrowX = Math.max(14, Math.min(r.left + r.width / 2 - left, w - 14));
    el.style.setProperty('--arrow-x', arrowX + 'px');
    requestAnimationFrame(() => el.classList.add('visible'));
  },

  hide() {
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    if (this._el) { this._el.remove(); this._el = null; }
    this._anchor = null;
  },
};

// ── Модалки: фокус, Tab-ловушка, возврат фокуса ─────────────────────
const Modal = {
  _last: null,

  open(id) {
    const ov = $(id);
    if (!ov || ov.classList.contains('open')) return;
    this._last = document.activeElement;
    ov.classList.add('open');
    const f = ov.querySelector('.modal button, .modal input, .modal select, .modal textarea, .modal a[href]');
    if (f) setTimeout(() => f.focus(), 0);
  },

  close(id) {
    const ov = $(id);
    if (!ov || !ov.classList.contains('open')) return;
    ov.classList.remove('open');
    const last = this._last;
    this._last = null;
    if (last && last.focus && document.contains(last)) last.focus();
  },

  _top() {
    const all = document.querySelectorAll('.modal-overlay.open');
    return all.length ? all[all.length - 1] : null;
  },

  init() {
    document.addEventListener('keydown', (e) => {
      const ov = this._top();
      if (!ov || e.key !== 'Tab') return;
      const items = Array.from(ov.querySelectorAll(
        'button:not([disabled]):not([hidden]), [href], input:not([disabled]):not([hidden]), select:not([hidden]), textarea:not([hidden]), [tabindex]:not([tabindex="-1"])'
      )).filter(el => el.offsetParent !== null
                     && window.getComputedStyle(el).visibility !== 'hidden');
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (!ov.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  },
};

// ── Своё подтверждение вместо window.confirm ────────────────────────
const Confirm = {
  _resolve: null,
  _wired: false,

  ask({ title, text, ok = 'Продолжить', danger = false } = {}) {
    return new Promise((resolve) => {
      this._resolve = resolve;
      $('confirmTitle').textContent = title || 'Подтвердите действие';
      $('confirmText').textContent = text || '';
      const btn = $('confirmOk');
      btn.textContent = ok;
      btn.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
      this._wire();
      Modal.open('confirmOverlay');
    });
  },

  _done(val) {
    Modal.close('confirmOverlay');
    const r = this._resolve;
    this._resolve = null;
    if (r) r(val);
  },

  _wire() {
    if (this._wired) return;
    this._wired = true;
    $('confirmOk').addEventListener('click', () => this._done(true));
    $('confirmCancel').addEventListener('click', () => this._done(false));
    $('confirmOverlay').addEventListener('mousedown', (e) => {
      if (e.target.id === 'confirmOverlay') this._done(false);
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && $('confirmOverlay').classList.contains('open')) this._done(false);
    });
  },
};

// ── Плавающий индикатор задач: правый нижний угол, виден на всех вкладках ──
// Жёлтая мигающая точка = выполняется, зелёная = готово, красная = ошибка.
// Клик по плашке открывает вкладку с результатом.
const Activity = {
  _el: null, _text: null, _pct: null, _cancelBtn: null,
  _page: '', _hideTimer: null, _cancelling: false,

  _ensure() {
    if (this._el) return;
    const el = document.createElement('div');
    el.className = 'activity-chip';
    el.hidden = true;
    el.setAttribute('role', 'button');
    el.setAttribute('tabindex', '0');
    el.innerHTML = '<span class="activity-dot"></span>' +
      '<span class="activity-text"></span>' +
      '<span class="activity-pct mono"></span>' +
      '<span class="activity-go" aria-hidden="true">→</span>';
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'activity-cancel';
    cancel.textContent = 'Отменить';
    cancel.hidden = true;
    cancel.addEventListener('click', (e) => { e.stopPropagation(); this._cancel(); });
    el.appendChild(cancel);
    const go = () => { if (this._page) location.hash = '#' + this._page; };
    el.addEventListener('click', go);
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
    document.body.appendChild(el);
    this._el = el;
    this._text = el.querySelector('.activity-text');
    this._pct = el.querySelector('.activity-pct');
    this._cancelBtn = cancel;
  },

  _cancel() {
    if (this._cancelling) return;
    this._cancelling = true;
    this._cancelBtn.disabled = true;
    this._cancelBtn.textContent = 'Отменяем…';
    apiPost('/tester/action', { action: 'cancel' }).catch(() => {});
  },

  set(page, label, pct, cancelable) {
    this._ensure();
    clearTimeout(this._hideTimer);
    this._page = page || '';
    this._el.hidden = false;
    this._el.classList.remove('done', 'fail');
    this._el.classList.add('running');
    this._text.textContent = label || 'Выполняется…';
    this._pct.textContent = (pct != null) ? Math.round(pct) + '%' : '';
    this._cancelling = false;
    this._cancelBtn.hidden = !cancelable;
    this._cancelBtn.disabled = false;
    this._cancelBtn.textContent = 'Отменить';
  },

  done(label) {
    if (!this._el || this._el.hidden) return;
    clearTimeout(this._hideTimer);
    this._el.classList.remove('running', 'fail');
    this._el.classList.add('done');
    this._text.textContent = label || 'Готово';
    this._pct.textContent = '';
    this._hideTimer = setTimeout(() => this.hide(), 3500);
  },

  fail(label) {
    if (!this._el) return;
    this._ensure();
    clearTimeout(this._hideTimer);
    this._el.hidden = false;
    this._el.classList.remove('running', 'done');
    this._el.classList.add('fail');
    this._text.textContent = label || 'Ошибка';
    this._pct.textContent = '';
    this._hideTimer = setTimeout(() => this.hide(), 6000);
  },

  hide() {
    clearTimeout(this._hideTimer);
    if (this._el) this._el.hidden = true;
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());