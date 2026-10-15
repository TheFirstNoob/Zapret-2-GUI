// ── глобальный статус (чип в сайдбаре + Главная) ──

const Status = {
  timer: null,
  svcTimer: null,
  last: null,          // /api/status ответ
  svc: null,           // /api/service/status ответ
  _statusBusy: false,  // запрос /status ещё в полёте
  _svcBusy: false,
  _visHooked: false,

  start() {
    this.refresh();
    this.refreshService();
    this._startTimers();
    // Скрытая вкладка/свёрнутое окно (аудит 2026-10): поллинг сервера
    // каждые 4с не нужен, останавливаем; при возврате - мгновенный refresh.
    if (!this._visHooked) {
      this._visHooked = true;
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
          clearInterval(this.timer);
          clearInterval(this.svcTimer);
          this.timer = this.svcTimer = null;
        } else {
          this.refresh();
          this.refreshService();
          this._startTimers();
        }
      });
    }
  },

  _startTimers() {
    clearInterval(this.timer);
    clearInterval(this.svcTimer);
    this.timer = setInterval(() => this.refresh(), 4000);
    this.svcTimer = setInterval(() => this.refreshService(), 9000);
  },

  async refresh() {
    // /api/status дёргает tasklist с таймаутом 6с, а поллинг идёт каждые 4с:
    // без защиты запросы накладывались, а ответы приходили не по порядку -
    // и панель «Обход работает» скакала. Пропускаем тик, если прошлый ещё
    // не вернулся.
    if (this._statusBusy) return;
    this._statusBusy = true;
    try {
      const data = await apiGet('/status');
      this.last = data;
      this.render();
    } catch (e) {
      // Статус неизвестен - НЕ затираем прошлый ответ: иначе одна ошибка
      // мигает «нет связи» поверх рабочего состояния.
      if (!this.last) {
        $('protDot').className = 'dot dot-unknown';
        $('protText').textContent = 'нет связи…';
      }
    } finally {
      this._statusBusy = false;
    }
  },

  async refreshService() {
    if (this._svcBusy) return;
    this._svcBusy = true;
    try {
      try { this.svc = await apiGet('/service/status'); }
      catch (e) { this.svc = null; }
      this.render();
      if (App.currentPage === 'main') MainPage.renderServiceLine();
    } finally {
      this._svcBusy = false;
    }
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
      sub.textContent = (svc && svc.running) ? 'через службу' : 'PID ' + (z2.pid || '-');
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
