// ── router ──

const App = {
  currentPage: 'main',
  pages: ['main', 'tester', 'lists', 'contested', 'games', 'diagnostics', 'probe', 'cdn', 'asn'],
  testActive: false,

  // Кнопка «Инструкция и статусы» в info-баннере (единый механизм для всех страниц)
  bindHelpToggle(btnId, detId) {
    const btn = $(btnId);
    if (!btn) return;
    btn.addEventListener('click', () => {
      const det = $(detId);
      const open = !!det && det.hidden;
      if (det) det.hidden = !open;
      btn.classList.toggle('is-open', open);
    });
  },

  // Быстрый старт (туториал): 3 шага для новичка. Показывается, пока
  // пользователь не закроет; факт закрытия хранится в конфиге (tour_done).
  async initTour() {
    const card = $('tourCard');
    if (!card) return;
    try {
      const r = await apiGet('/config');
      if ((r.config || {}).tour_done) return;
      card.hidden = false;
    } catch (e) {
      return;
    }
    $('tourClose').addEventListener('click', async () => {
      card.hidden = true;
      try { await apiPost('/config', { tour_done: true }); } catch (e) { /* ignore */ }
    });
    $('tourStep1').addEventListener('click', () => {
      if (MainPage._z2Running) {
        showToast('Обход уже запущен - переходите к шагу 2', 'ok');
        return;
      }
      $('btnZ2Toggle').click();
    });
    $('tourStep2').addEventListener('click', () => { location.hash = 'diagnostics'; });
    $('tourStep3').addEventListener('click', () => { location.hash = 'tester'; });
  },

  // Честное уведомление «что делает программа и какие данные» - один раз
  // (флаг notice_done в конфиге; закрывается крестиком или «Понятно»).
  async initNotice() {
    const card = $('noticeCard');
    if (!card) return;
    try {
      const r = await apiGet('/config');
      if ((r.config || {}).notice_done) return;
      card.hidden = false;
    } catch (e) {
      return;
    }
    const dismiss = async () => {
      card.hidden = true;
      try { await apiPost('/config', { notice_done: true }); } catch (e) { /* ignore */ }
    };
    $('noticeClose').addEventListener('click', dismiss);
    $('noticeOk').addEventListener('click', dismiss);
  },

  // Фоновая проверка списков при старте: только уведомление (чистит юзер -
  // кнопкой в «Списках»), чтобы дубли из блокнота не путали со временем.
  async checkListsHealth() {
    try {
      const r = await apiGet('/lists/health');
      if (r.status !== 'ok') return;
      const bits = [];
      if (r.total_dups) bits.push(`дубли: ${r.total_dups}`);
      if (r.total_cross) bits.push(`повторы между вашими списками: ${r.total_cross}`);
      if (r.total_redundant) bits.push(`повторы: ${r.total_redundant}`);
      if (r.total_conflicts) bits.push(`конфликты: ${r.total_conflicts}`);
      if (bits.length) {
        showToast('Списки: ' + bits.join(', ') + ' - вкладка «Списки» → «Проверить»', 'warn');
      }
    } catch (e) { /* фоновая проверка не должна мешать запуску */ }
  },

  // Идёт проверка (стратегии/CDN/ASN/blob/диагностика): обходом управляет
  // тестер - блокируем ручной запуск/остановку, службу и другие кнопки
  // проверок, показываем мигающую точку на вкладке-источнике.
  setTestActive(active) {
    if (this.testActive === active) return;
    this.testActive = active;
    const badge = $('testerBadge');
    if (badge) {
      badge.hidden = !active;
      // Точка «идёт проверка» - на странице-источнике, а не всегда на «Подборе»
      if (active) {
        const link = document.querySelector(`.nav-link[data-page="${this.currentPage}"]`);
        if (link && link !== badge.parentElement) link.appendChild(badge);
      }
    }
    // Кнопки всех проверок - взаимоисключающие (бэкенд дублирует 409-ом).
    ['btnStartTest', 'cdnScanBtn', 'asnScanBtn', 'btnBlobProbe', 'diagRunBtn', 'btnDiagCheck']
      .forEach(id => { const el = $(id); if (el) el.disabled = active; });
    // Отдельный тост «идёт проверка» больше не нужен: задачу показывает
    // плавающая плашка внизу справа, а кнопки видно отключёнными.
    if (Status.last) MainPage.renderStatus(Status.last);
  },

  async init() {
    Popover.init();
    Modal.init();
    this.bindNav();
    this.bindProbeButtons();
    this.handleHash();
    window.addEventListener('hashchange', () => this.handleHash());
    this.loadVersion();
    this.checkUpdate();
    this.initTour();
    this.initNotice();
    this.checkListsHealth();
    try {
      const data = await apiGet('/profiles');
      PROFILES = (data.profiles || []).map(p => p.name);
    } catch (e) { PROFILES = ['default']; }
    Status.start();
    if (this.currentPage === 'main') MainPage.onShow();
  },

bindProbeButtons() {
    const scan = $('probeScanBtn');
    const start = $('probeStartBtn');
    const stop = $('probeStopBtn');
    if (scan) scan.addEventListener('click', () => TesterPage.scanProbeProcesses());
    const procInput = $('probeProcInput');
    if (procInput) {
      let t = null;
      procInput.addEventListener('input', () => {
        clearTimeout(t);
        t = setTimeout(() => TesterPage._hintProbeProcess(), 250);
      });
    }
    const sel = $('probeProcSelect');
    if (sel) sel.addEventListener('change', () => {
      $('probeProcInput').value = sel.value;
      TesterPage._hintProbeProcess();
    });
if (start) start.addEventListener('click', () => TesterPage.startProbe());
    if (stop) stop.addEventListener('click', () => TesterPage.stopProbe());
    const report = $('probeReportBtn');
    if (report) report.addEventListener('click', () => TesterPage.saveProbeReport());
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
    frontendLog('nav: hash=' + hash);
    document.querySelectorAll('.nav-link').forEach(l =>
      l.classList.toggle('active', l.dataset.page === hash));
    const expert = $('expertNav');
    if (expert) {
      const cur = document.querySelector('.nav-link.active');
      if (cur && expert.contains(cur)) expert.open = true;
    }
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    $('page-' + hash).classList.add('active');
    // Смена вкладки - наверх: скролл не должен переезжать между страницами
    const content = document.querySelector('.content');
    if (content) content.scrollTop = 0;
    const titles = { main: 'Главная', tester: 'Подбор стратегии', lists: 'Списки', contested: 'Спорные домены', games: 'Игровые блокировки', diagnostics: 'Проверка системы', probe: 'Анализ приложения', cdn: 'CDN-стабилизация', asn: 'ASN-скан' };
    $('pageTitle').textContent = titles[hash];
    if (hash === 'main') MainPage.onShow();
    if (hash === 'lists') ListsPage.onShow();
    if (hash === 'contested') ListsPage.onShow();
    if (hash === 'games') GamesPage.onShow();
    if (hash === 'cdn') CdnStab.init();
    if (hash === 'asn') AsnPage.init();
    if (hash === 'diagnostics') DiagnosticsPage.onShow();
    if (hash === 'tester') TesterPage.onShow();
    // Список процессов заполняем сами при открытии вкладки - ручная
    // кнопка «Сканировать» не нужна, интерфейс не дублирует действия.
    if (hash === 'probe' && !TesterPage._probePollTimer && !TesterPage._probeStarting) {
      TesterPage.scanProbeProcesses(true);
    }
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
        this._updateTag = r.tag || r.latest.replace(' ', '-');
        $('updateBanner').hidden = false;
      }
    } catch (e) { /* silent */ }
  },

  // Обновление из программы (0.8): скачать → бэкап → применить (portable/lite)
  // или подготовить замену EXE → предложит перезапуск; после - проверка службы
  async runUpdate() {
    const btn = $('updateNowBtn');
    const bar = $('updateProgress');
    const fill = $('updateProgressFill');
    const phase = $('updatePhase');
    const hideProgress = () => {
      if (bar) bar.hidden = true;
      if (phase) phase.hidden = true;
    };
    btn.disabled = true;
    btn.textContent = 'Обновление…';
    if (bar) { bar.hidden = false; if (fill) fill.style.width = '0%'; }
    if (phase) phase.hidden = false;
    try {
      const started = await apiPost('/update/start', {});
      if (started.status !== 'ok') {
        hideProgress();
        showToast('Обновление не запустилось: ' + (started.message || 'ошибка'),
          'error');
        btn.disabled = false;
        btn.textContent = 'Обновить сейчас';
        return;
      }
      const pollId = setInterval(async () => {
        try {
          const st = await apiGet('/update/status');
          if (fill) fill.style.width = (st.percent || 0) + '%';
          if (phase) phase.textContent = st.phase || '';
          btn.textContent = `${st.phase || '…'} ${st.percent ? st.percent + '%' : ''}`.trim();
          if (st.running) return;
          clearInterval(pollId);
          if (st.error) {
            hideProgress();
            showToast('Обновление не удалось: ' + st.error, 'error');
            btn.disabled = false;
            btn.textContent = 'Повторить обновление';
            return;
          }
          const res = st.result || {};
          // Баннер НЕ скрываем заранее: при ошибке на нём живёт кнопка
          // «Повторить обновление», а при service_mismatch - «Переустановить
          // службу» (аудит 2026-10: кнопка пряталась вместе с баннером).
          // update_bat (exe) и restart_bat (portable) - оба автозапуском:
          // «как в стиме»: файлы применены, прога закрывается и стартует сама.
          if (res.update_bat || res.restart_bat) {
            if (fill) fill.style.width = '100%';
            if (phase) phase.textContent = 'Применено - перезапуск…';
            btn.disabled = true;
            btn.textContent = 'Перезапуск…';
            try {
              const ap = await apiPost('/update/apply', {});
              if (ap.status !== 'ok') throw new Error(ap.message || 'ошибка');
              $('updateBanner').hidden = true;
              showToast(ap.message || 'Программа перезапускается', 'ok');
              Activity.set('main', 'Обновление: программа перезапускается');
            } catch (e) {
              hideProgress();
              showToast('Обновление скачано, но перезапуск не выполнен: '
                        + (e.message || e), 'error');
              btn.disabled = false;
              btn.textContent = 'Повторить обновление';
            }
            return;
          }
          if (res.service_mismatch) {
            hideProgress();
            showToast('Обновление проверено по подписи и применено. Служба стоит на старой конфигурации - переустановите её кнопкой ниже', 'warn');
            btn.disabled = false;
            btn.textContent = 'Переустановить службу';
            this._updateStage = 'service';
          } else {
            hideProgress();
            $('updateBanner').hidden = true;
            showToast('Обновление проверено по подписи и применено - перезапустите программу', 'ok');
            setTimeout(() => { location.reload(); }, 1500);
          }
        } catch (e) {
          clearInterval(pollId);
          hideProgress();
          btn.disabled = false;
          btn.textContent = 'Повторить';
        }
      }, 1000);
    } catch (e) {
      hideProgress();
      showToast('Обновление не запустилось: ' + (e.message || e), 'error');
      btn.disabled = false;
      btn.textContent = 'Обновить сейчас';
    }
  },

  _onUpdateBtn() {
    if (this._updateStage === 'service') {
      const btn = $('updateNowBtn');
      btn.disabled = true;
      btn.textContent = 'Переустановка службы…';
      apiPost('/service/install', {}).then(r => {
        if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
        showToast('Служба переустановлена - перезапустите программу', 'ok');
        setTimeout(() => { location.reload(); }, 1500);
      }).catch(e => {
        showToast('Ошибка переустановки: ' + (e.message || e), 'error');
        btn.disabled = false;
        btn.textContent = 'Повторить переустановку';
      });
      return;
    }
    this.runUpdate();
  },
};
