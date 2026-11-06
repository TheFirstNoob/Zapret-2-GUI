// ══════════════════════════ ГЛАВНАЯ ══════════════════════════

const MainPage = {
  _busy: false,
  _z2Running: false,
  _z2Strategy: '',
  _loaded: false,
  _runningToggles: null,  // тогглы, с которыми реально запущен обход
  _configLoaded: false,
  _configBusy: false,
  _configLoadWarned: false,

  onShow() {
    if (!this._loaded) {
      this._loaded = true;
      this.populateFakeBlobs();
      this.bind();
      MainPage.renderServiceLine();
    }
    // Конфиг мог не загрузиться при первом показе вкладки (обрыв связи,
    // таймаут, бэкенд перезапускался) - тогда повторяем попытку при
    // следующем открытии, а не один раз на сессию. Пока _configLoaded
    // не взведён, запись настроек заблокирована (_configReady).
    if (!this._configLoaded && !this._configBusy) this.loadConfig();
    if (typeof DnsPanel !== 'undefined') DnsPanel.onShow();
    if (Status.last) this.renderStatus(Status.last);
  },

  bind() {
    $('btnZ2Toggle').addEventListener('click', () => this.toggleZ2());
    $('btnQuickCheck').addEventListener('click', () => {
      location.hash = 'diagnostics';
      // «Проверить работу» должна реально запускать проверку, а не просто
      // переключать вкладку: небольшая задержка - пока страница активируется.
      setTimeout(() => DiagnosticsPage.run(), 150);
    });
    $('btnApplyToggles').addEventListener('click', () => this.restartZapret());
    $('btnRevertToggles').addEventListener('click', () => this._revertToggles());
    $('btnSvcRepair').addEventListener('click', () => this.svcRepair());
    $('btnSvcInstall').addEventListener('click', () => this.svcInstall());
    $('btnSvcStart').addEventListener('click', () => this.svcStart());
    $('btnSvcStop').addEventListener('click', () => this.svcStop());
    $('btnSvcRemove').addEventListener('click', () => this.svcRemove());
    $('updateBannerClose').addEventListener('click', () => { $('updateBanner').hidden = true; });
    $('updateNowBtn').addEventListener('click', () => App._onUpdateBtn());

    ['toggleGameFilter', 'toggleAutoHostlist', 'toggleIpFilter',
      'toggleDiscordVoice', 'toggleDiscordAlt', 'toggleWinws2Debug', 'fakeBlobSelect'].forEach(id => {
      $(id).addEventListener('change', () => this.saveToggles());
    });
    $('btnBlobProbe').addEventListener('click', () => {
      if (this._blobProbing) this._cancelBlobProbe();
      else this.runBlobProbe();
    });
    const gs = $('gamesSearch');
    if (gs) gs.addEventListener('input', () => GamesPage.render());
    // Подвал меню: экспорт/импорт настроек и техинфо (обновления)
    const impFile = $('settingsImportFile');
    if (impFile) impFile.addEventListener('change', () => ListsPage.importSettings(impFile));
    const sideExp = $('sideExport');
    if (sideExp) sideExp.addEventListener('click', () => ListsPage.exportSettings());
    const sideInfo = $('sideInfo');
    if (sideInfo) sideInfo.addEventListener('click', () => AppInfo.open());
    // Статус-чип в подвале меню кликабелен: ведёт на главную
    const protChip = $('protChip');
    if (protChip) {
      const goMain = () => { location.hash = '#main'; };
      protChip.addEventListener('click', goMain);
      protChip.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); goMain(); }
      });
    }
  },

  async loadConfig() {
    if (this._configBusy) return;
    this._configBusy = true;
    try {
      const r = await apiGet('/config');
      const c = r.config || {};
      $('toggleGameFilter').value = c.game_filter_mode || 'off';
      $('toggleAutoHostlist').checked = !!c.autohostlist;
      $('toggleIpFilter').checked = !!c.ipset_catchall;
      $('toggleDiscordVoice').value = c.discord_voice_mode || (c.discord_voice ? 'fake' : 'off');
      $('toggleDiscordAlt').checked = !!c.discord_alt;
      this._updateVoiceHint();
      this._pendingFakeBlob = c.fake_blob || '';
      const fbSel = $('fakeBlobSelect');
      if (fbSel && Array.from(fbSel.options).some(o => o.value === this._pendingFakeBlob)) {
        fbSel.value = this._pendingFakeBlob;
      }
      $('toggleWinws2Debug').checked = !!c.winws2_debug;
      if (c.last_profile) {
        this._savedProfile = c.last_profile;
        const sel = $('strategySelect');
        if ([...sel.options].some(o => o.value === c.last_profile)) sel.value = c.last_profile;
      }
      this._configLoaded = true;
      // Обход уже был запущен до загрузки конфига - снимок тогглов делаем
      // только теперь, когда DOM показывает сохранённые значения.
      if (this._z2Running && !this._runningToggles) {
        this._runningToggles = this._collectToggles();
        this._updateApplyHint();
      }
    } catch (e) {
      // Раньше ошибка молча проглатывалась: DOM оставался в значениях по
      // умолчанию, и следующий же saveToggles / applyStrategy отправлял
      // бэкенду именно их - молча затирая сохранённые настройки
      // (исторический аудит, кандидат 3). Теперь сообщаем пользователю
      // и держим запись закрытой до успешной загрузки (_configReady).
      frontendLog('GET /config failed: ' + (e && e.message));
      if (!this._configLoadWarned) {
        this._configLoadWarned = true;
        showToast('Не удалось загрузить настройки: ' + (e && e.message) +
          ' - запись настроек заблокирована', 'error');
      }
    } finally {
      this._configBusy = false;
    }
  },

  // Запись настроек снимается с DOM, а пока конфиг не загружен, значения
  // на форме - значения по умолчанию из разметки. Сбой GET /config раньше
  // проглатывался, и следующий saveToggles/applyStrategy отправлял бэкенду
  // именно дефолты, молча затирая настройки пользователя
  // (исторический аудит, кандидат 3). Поэтому перед любой записью
  // убеждаемся, что конфиг загружен: если нет - пробуем догрузить сейчас
  // (например, страницу сначала открыли не с «Главной»), и только потом
  // отказываем.
  async _configReady(what) {
    if (!this._configLoaded) await this.loadConfig();
    if (this._configLoaded) return true;
    showToast('Настройки не загружены - ' + what + ' невозможно', 'error');
    frontendLog('config not loaded, blocked: ' + what);
    return false;
  },

  // Список доступных TLS-фейк-блобов (blobs/tls_clienthello_*.bin).
  // Рекомендованные (проверенные, ≤700 байт) - первыми, с меткой ★.
  async populateFakeBlobs() {
    try {
      const r = await apiGet('/fake-blobs');
      const sel = $('fakeBlobSelect');
      if (!sel || this._blobsLoaded) return;
      this._blobsLoaded = true;
      const rec = new Set(r.recommended || []);
      const sizes = r.sizes || {};
      for (const key of r.blobs || []) {
        if (Array.from(sel.options).some(o => o.value === key)) continue;
        const o = document.createElement('option');
        o.value = key;
        const label = key.replace(/_/g, '.');
        const sz = sizes[key] || 0;
        o.textContent = rec.has(key)
          ? `★ ${label} (${sz} B)`
          : (sz > 700 ? `⚠ ${label} (${sz} B) - большой` : `${label} (${sz} B)`);
        sel.appendChild(o);
      }
      sel.value = this._pendingFakeBlob || '';
    } catch (e) { /* список не критичен */ }
  },

  // Перебор TLS-фейк-блобов: короткая батарея на каждом, победитель
  // подставляется в селектор (применение - через «Перезапустить»).
  async runBlobProbe() {
    if (this._blobProbing || App.testActive) return;
    this._blobProbing = true;
    this._blobProbeCancelled = false;
    App.setTestActive(true);
    const btn = $('btnBlobProbe');
    const hint = $('fakeBlobHint');
    // На время подбора кнопка сама становится «Остановить» - без лишней.
    btn.textContent = 'Остановить';
    btn.classList.add('btn-danger-text');
    btn.title = 'Остановить подбор';
    btn.disabled = false;
    hint.textContent = 'Запуск...';
    try {
      const started = await apiPost('/blob-probe', {});
      if (started.status !== 'ok') throw new Error(started.message || 'ошибка');
      const deadline = Date.now() + 6 * 60 * 1000;
      let final = null;
      while (!final && Date.now() < deadline) {
        await new Promise(res => setTimeout(res, 700));
        const st = await apiGet('/tester/status');
        if (st.error) throw new Error(st.error);
        if (st.progress && hint && !this._blobProbeCancelled) {
          hint.textContent = `${st.progress.message || ''} (${st.progress.percent ?? 0}%)`;
          Activity.set('main', 'Подбор блоба: ' + (st.progress.message || ''),
                       st.progress.percent, true);
        }
        if (!st.running) final = st.final_result;
      }
      if (!final) throw new Error('подбор не завершился вовремя');
      if (final.restored) showToast(final.restored, 'ok');
      const results = (final.results || []).filter(x => x.rate >= 0)
        .sort((a, b) => b.rate - a.rate || b.ok - a.ok);
      if (!results.length) throw new Error('нет результатов');
      if (hint) {
        hint.innerHTML = results.map(x =>
          `<div>${x.blob === results[0].blob ? '<b>' : ''}${escapeHtml(x.blob)}: ${x.rate}% (${x.ok}/${x.total})${x.blob === results[0].blob ? '</b>' : ''}</div>`).join('');
      }
      if (this._blobProbeCancelled) {
        // частичный прогон: показываем, но лучший не подставляем
        Activity.done('Подбор остановлен');
        showToast('Подбор остановлен - показаны частичные результаты', 'warn');
      } else {
        const best = results[0];
        const sel = $('fakeBlobSelect');
        Activity.done('Подбор блоба завершён');
        showToast(`Лучший блоб: ${best.blob.replace(/_/g, '.')} (${best.rate}%)`, 'ok');
        const opts = Array.from(sel.options);
        const target = opts.some(o => o.value === best.blob) ? best.blob
                     : ('blob_' + best.blob);
        if (opts.some(o => o.value === target) && sel.value !== target) {
          sel.value = target;
          this.saveToggles();
        }
      }
    } catch (e) {
      if (this._blobProbeCancelled) {
        Activity.done('Подбор остановлен');
        showToast('Подбор остановлен', 'warn');
        if (hint) hint.textContent = '';
      } else {
        Activity.fail('Подбор блоба: ' + e.message);
        showToast('Подбор блоба: ' + e.message, 'error');
        if (hint) hint.textContent = '';
      }
    }
    btn.textContent = 'Подобрать блоба';
    btn.classList.remove('btn-danger-text');
    btn.title = 'Переберёт блобы и поставит лучший';
    btn.disabled = false;
    this._blobProbing = false;
    App.setTestActive(false);
    Status.refresh();
  },

  _cancelBlobProbe() {
    const btn = $('btnBlobProbe');
    btn.disabled = true;
    this._blobProbeCancelled = true;
    apiPost('/tester/action', { action: 'cancel' }).catch(() => {});
    const hint = $('fakeBlobHint');
    if (hint) hint.textContent = 'Останавливаем...';
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
    if (z2.running) {
      badge.className = 'dot ' + (conflict ? 'dot-warn' : 'dot-ok');
      text.className = 'state-text ' + (conflict ? 'st-warn' : 'st-ok');
      text.textContent = conflict
        ? 'Работает (конфликт с Zapret 1)'
        : 'Работает' + (z2.pid ? ' · PID ' + z2.pid : '');
    } else if (z1.running) {
      badge.className = 'dot dot-warn';
      text.className = 'state-text st-warn';
      text.textContent = 'Выключен (работает Zapret 1)';
    } else {
      badge.className = 'dot dot-off';
      text.className = 'state-text st-mute';
      text.textContent = 'Выключен';
    }

    // Отдача пользователю на главной: что сейчас и что делать дальше
    const fb = $('z2Feedback');
    if (fb) {
      if (conflict) {
        fb.textContent = 'Оба обхода запущены одновременно - остановите один из них.';
      } else if (z2.running) {
        fb.textContent = 'Обход работает' + (z2.strategy ? ' («' + z2.strategy + '»)' : '') +
          ' - проверьте, открываются ли нужные сайты.';
      } else if (z1.running) {
        fb.textContent = 'Zapret 1 запущен — остановите его вручную, чтобы запустить Zapret 2.';
      } else {
        fb.textContent = 'Обход выключен: заблокированные сайты не откроются, пока не нажмёте «Запустить».';
      }
    }
    const qc = $('btnQuickCheck');
    if (qc) qc.hidden = !z2.running;

    this._z2Running = z2.running;
    this._z2Strategy = z2.strategy || '';
    // Снимок тогглов запущенного процесса: до loading конфига не снимаем.
    if (!this._z2Running) this._runningToggles = null;
    else if (!this._runningToggles && this._configLoaded) this._runningToggles = this._collectToggles();

    const btn = $('btnZ2Toggle');
    if (!this._busy && !App.testActive) {
      const sel = $('strategySelect');
      const strategyChanged = this._z2Running && sel.value && this._z2Strategy && sel.value !== this._z2Strategy;
      if (!this._z2Running) {
        btn.textContent = 'Запустить';
        btn.classList.add('btn-go');
        btn.classList.remove('btn-stop', 'btn-primary');
      } else if (strategyChanged) {
        // Выбор расходится с запущенной стратегией: кнопка применяет выбор.
        btn.textContent = 'Применить «' + sel.value + '»';
        btn.classList.add('btn-primary');
        btn.classList.remove('btn-go', 'btn-stop');
      } else {
        btn.textContent = 'Остановить';
        btn.classList.add('btn-stop');
        btn.classList.remove('btn-go', 'btn-primary');
      }
      btn.disabled = false;
    } else if (App.testActive) {
      btn.disabled = true;
    }
    const hint = $('strategyApplyHint');
    const selNow = $('strategySelect').value;
    const strategyChangedNow = this._z2Running && selNow && this._z2Strategy && selNow !== this._z2Strategy;
    hint.hidden = !strategyChangedNow;
    if (strategyChangedNow) {
      hint.textContent = 'Запущена «' + this._z2Strategy + '» - нажатие кнопки перезапустит обход с выбранной.';
    }

    $('conflictBanner').hidden = !(z2.running && z1.running);
    // Zapret 1 больше не управляется из GUI: только детект конфликта.

    // перезапуск по изменённым тогглам - только когда что-то изменено и запущено
    this._updateApplyHint();
    this.populateProfiles(d.profiles || []);
  },

  renderServiceLine() {
    const svc = Status.svc;
    if (!svc) return;
    const installed = !!svc.installed;
    const running = !!svc.running;
    $('btnSvcInstall').hidden = installed;
    $('btnSvcStart').hidden = !(installed && !running);
    $('btnSvcStop').hidden = !(installed && running);
    $('btnSvcRemove').hidden = !installed;
    $('svcStatusText').textContent = this._svcBusy ? '…'
      : !installed ? 'не установлена - обход только при открытом приложении'
      : (running ? 'установлена · работает (автозапуск при загрузке)'
                 : 'установлена · остановлена');
    const chip = $('svcState');
    if (chip) {
      const dot = chip.querySelector('.dot');
      const txt = chip.querySelector('.state-text');
      if (this._svcBusy) {
        dot.className = 'dot dot-idle'; txt.textContent = '…'; txt.className = 'state-text st-mute';
      } else if (!installed) {
        dot.className = 'dot dot-off'; txt.textContent = 'не установлена'; txt.className = 'state-text st-mute';
      } else if (running) {
        dot.className = 'dot dot-ok'; txt.textContent = 'работает'; txt.className = 'state-text st-ok';
      } else {
        dot.className = 'dot dot-off'; txt.textContent = 'остановлена'; txt.className = 'state-text st-mute';
      }
    }
  },

  _setSvcBusy(b) {
    this._svcBusy = b;
    ['btnSvcRepair', 'btnSvcInstall', 'btnSvcStart', 'btnSvcStop', 'btnSvcRemove'].forEach(id => {
      $(id).disabled = b;
    });
  },

  async _svcAction(fn, busyText, okText, errText) {
    if (this._svcBusy) return;
    this._setSvcBusy(true);
    $('svcStatusText').textContent = busyText;
    Activity.set('main', busyText);
    try {
      const r = await fn();
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      Activity.done(okText);
      showToast(okText, 'ok');
    } catch (e) {
      Activity.fail(errText + e.message);
      showToast(errText + e.message, 'error');
    }
    this._setSvcBusy(false);
    Status.refreshService();
    Status.refresh();
  },

  async svcInstall() {
    if (this._svcBusy) return;
    if (!await this._configReady('установка службы')) return;
    const t = this._collectToggles();
    const payload = {
      profile: $('strategySelect').value,
      game_filter: t.game_filter_mode, discord_voice_mode: t.discord_voice_mode,
      debug: t.winws2_debug, autohostlist: t.autohostlist,
      ipset_catchall: t.ipset_catchall, discord_alt: t.discord_alt,
    };
    this._svcAction(
      async () => {
        const r = await apiPost('/service/install', payload);
        if (r.status !== 'ok') return r;
        // Текст установки приходит с бэкенда: он честно говорит, если
        // служба создалась, но не запустилась (обхода нет) или не настроен
        // автозапуск при падении (service_manager.install).
        const note = (r.message || '').trim();
        const bad = /не запустилась|не настроен/i.test(note);
        if (note) showToast(note, bad ? 'warn' : 'ok');
        const started = await apiPost('/service/start', payload);
        if (started.status !== 'ok') return started;
        return r;
      },
      'Установка…', 'Служба установлена и запущена - обход работает без программы',
      'Не удалось установить службу: ');
  },

  svcStart() {
    this._svcAction(() => apiPost('/service/start', {}),
      'Запуск…', 'Служба запущена', 'Не удалось запустить службу: ');
  },

  svcStop() {
    this._svcAction(() => apiPost('/service/stop', {}),
      'Остановка…', 'Служба остановлена', 'Не удалось остановить службу: ');
  },

  async svcRemove() {
    const running = !!(Status.svc && Status.svc.running);
    const ok = await Confirm.ask({
      title: 'Удалить службу Zapret 2?',
      text: running
        ? 'Служба сейчас запущена: она будет остановлена, и обход временно прервётся. Автозапуск после перезагрузки отключится.'
        : 'Автозапуск обхода после перезагрузки отключится. Запущенный вручную обход это не затронет.',
      ok: 'Удалить службу',
      danger: true,
    });
    if (!ok) return;
    this._svcAction(async () => {
      if (Status.svc && Status.svc.running) await apiPost('/service/stop', {}).catch(() => {});
      return apiPost('/service/remove', {});
    }, 'Удаление…', 'Служба удалена', 'Не удалось удалить службу: ');
  },

  async svcRepair() {
    this._setSvcBusy(true);
    $('svcStatusText').textContent = 'Выгрузка драйвера…';
    try {
      const r = await apiPost('/service/repair', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const acts = r.actions || [];
      if (r.reboot_required) {
        showToast('Драйвер всё ещё занят: ' + acts.join('; ')
                  + '. Если не отпустит - понадобится перезагрузка.', 'error');
      } else if (r.resolved === false) {
        showToast('Выполнено частично: ' + acts.join('; '), 'warn');
      } else if (acts.length) {
        showToast('Выполнено без перезагрузки: ' + acts.join('; '), 'ok');
      } else {
        showToast('Драйвер в порядке - проблем не найдено', 'ok');
      }
      if (r.zapret1) {
        showToast('Замечание: ' + r.zapret1, 'warn');
      }
    } catch (e) {
      showToast('Не удалось выгрузить драйвер: ' + e.message, 'error');
    }
    this._setSvcBusy(false);
    Status.refreshService();
    Status.refresh();
  },

  _collectToggles() {
    return {
      game_filter_mode: $('toggleGameFilter').value,
      discord_voice: $('toggleDiscordVoice').value !== 'off',
      discord_voice_mode: $('toggleDiscordVoice').value,
      winws2_debug: $('toggleWinws2Debug').checked,
      autohostlist: $('toggleAutoHostlist').checked,
      ipset_catchall: $('toggleIpFilter').checked,
      discord_alt: $('toggleDiscordAlt').checked,
      fake_blob: $('fakeBlobSelect') ? $('fakeBlobSelect').value : '',
    };
  },

  _VOICE_HINTS: {
    off: '',
    fake: 'Стандарт: подмена QUIC-пакетов на голосовых портах Discord',
    udplen: 'Сдвиг длины каждого голосового пакета - если стандарт не берёт голос',
  },

  _updateVoiceHint() {
    const el = $('voiceModeHint');
    if (el) el.textContent = this._VOICE_HINTS[$('toggleDiscordVoice').value] || '';
  },

  async _postConfigOrThrow(payload) {
    const r = await apiPost('/config', payload);
    if (!r || r.status !== 'ok') {
      throw new Error((r && r.message) || 'сервер не сохранил настройки');
    }
    return r;
  },

  async saveToggles() {
    this._updateVoiceHint();
    if (!await this._configReady('сохранение настроек')) return;
    const t = this._collectToggles();
    try {
      const r = await apiPost('/config', t);
      if (r.status !== 'ok') {
        // бэкенд отвечает {"status":"error"} с HTTP 200 (например, неизвестный
        // блоб) - без проверки настройка молча не сохранялась (аудит 2026-10)
        throw new Error(r.message || 'сервер отклонил настройки');
      }
      // Без тоста на каждый чекбокс: факт «есть неприменённые изменения»
      // показывает кнопка «Перезапустить с новыми параметрами».
    } catch (e) {
      showToast('Не удалось сохранить: ' + e.message, 'error');
    }
    this._updateApplyHint();
  },

  _TOGGLE_NAMES: {
    game_filter_mode: 'Игровые порты',
    discord_voice_mode: 'Discord Voice',
    discord_alt: 'Альт-режим Discord',
    autohostlist: 'Авто-список',
    ipset_catchall: 'Общий IP-обход',
    winws2_debug: 'DEBUG-лог',
    fake_blob: 'Блоб фейка',
  },

  _TOGGLE_VALUES: {
    game_filter_mode: { off: 'Выключено', tcp: 'только TCP', udp: 'только UDP', both: 'TCP + UDP' },
    discord_voice_mode: { off: 'Выключено', fake: 'Стандарт', udplen: 'UDP-длина' },
  },

  // Что расходится с запущенным обходом (для плашки «есть неприменённые»)
  _pendingDiff() {
    if (!this._z2Running || !this._runningToggles) return [];
    const cur = this._collectToggles();
    const ref = this._runningToggles;
    const out = [];
    const val = (k, v) => (this._TOGGLE_VALUES[k] || {})[v] || v;
    for (const k of Object.keys(this._TOGGLE_NAMES)) {
      if (k === 'discord_voice_mode') {
        const av = ref.discord_voice_mode || (ref.discord_voice ? 'fake' : 'off');
        const bv = cur.discord_voice_mode || (cur.discord_voice ? 'fake' : 'off');
        if (av !== bv) out.push(`${this._TOGGLE_NAMES[k]}: ${val(k, av)} → ${val(k, bv)}`);
        continue;
      }
      if (['discord_alt', 'autohostlist', 'ipset_catchall', 'winws2_debug'].includes(k)) {
        if (!!ref[k] !== !!cur[k]) {
          out.push(`${this._TOGGLE_NAMES[k]}: ${cur[k] ? 'включить' : 'выключить'}`);
        }
        continue;
      }
      const a = k === 'fake_blob' ? (ref[k] || '') : ref[k];
      const b = k === 'fake_blob' ? (cur[k] || '') : cur[k];
      if (a !== b) {
        const show = (x) => (x || 'как в пресете').replace(/_/g, '.');
        out.push(`${this._TOGGLE_NAMES[k]}: ${show(a)} → ${show(b)}`);
      }
    }
    const sel = $('strategySelect');
    if (sel && sel.value && this._z2Strategy && sel.value !== this._z2Strategy) {
      out.push(`Стратегия: ${this._z2Strategy} → ${sel.value}`);
    }
    return out;
  },

  _updateApplyHint() {
    const btn = $('btnApplyToggles');
    const rev = $('btnRevertToggles');
    const hint = $('applyTogglesHint');
    const diff = $('applyTogglesDiff');
    // Кнопки только когда обход запущен и параметры расходятся с тем,
    // с чем процесс реально стартовал.
    const list = this._pendingDiff();
    const pending = list.length > 0;
    btn.hidden = !pending;
    if (rev) rev.hidden = !pending;
    if (diff) diff.innerHTML = list.map(t => `<span>${escapeHtml(t)}</span>`).join('');
    hint.textContent = pending
      ? 'Есть неприменённые изменения:'
      : (this._z2Running ? '' : '');
  },

  // Вернуть переключатели к состоянию запущенного обхода
  _revertToggles() {
    const ref = this._runningToggles;
    if (!ref) return;
    $('toggleGameFilter').value = ref.game_filter_mode || 'off';
    $('toggleDiscordVoice').value =
      ref.discord_voice_mode || (ref.discord_voice ? 'fake' : 'off');
    $('toggleWinws2Debug').checked = !!ref.winws2_debug;
    $('toggleAutoHostlist').checked = !!ref.autohostlist;
    $('toggleIpFilter').checked = !!ref.ipset_catchall;
    $('toggleDiscordAlt').checked = !!ref.discord_alt;
    const sel = $('fakeBlobSelect');
    if (sel) sel.value = ref.fake_blob || '';
    const st = $('strategySelect');
    if (this._z2Strategy && st && [...st.options].some(o => o.value === this._z2Strategy)) {
      st.value = this._z2Strategy;
    }
    this.saveToggles();
  },

  async toggleZ2() {
    const sel = $('strategySelect');
    if (this._z2Running) {
      // Выбор расходится с запущенной стратегией - кнопка применяет его.
      if (sel.value && this._z2Strategy && sel.value !== this._z2Strategy) {
        return this.applyStrategy(sel.value);
      }
      return this.stop();
    }
    if (!sel.value) { showToast('Выберите стратегию', 'warn'); return; }
    if (!await this._configReady('запуск')) return;
    this._setBusy(true);
    try {
      await this._postConfigOrThrow(Object.assign({ last_profile: sel.value }, this._collectToggles()));
      const r = await apiPost('/start', { profile: sel.value });
      if (r.status === 'ok') {
        this._runningToggles = this._collectToggles();
        showToast('Обход запущен: ' + sel.value, 'ok');
      } else {
        showToast('Не удалось запустить: ' + (r.message || 'ошибка'), 'error');
      }
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
    if (!await this._configReady('перезапуск с новыми параметрами')) return;
    const btn = $('btnApplyToggles');
    btn.disabled = true;
    try {
      await this._postConfigOrThrow(this._collectToggles());
      await apiPost('/stop', {});
      await new Promise(r => setTimeout(r, 1200));
      const r = await apiPost('/start', { profile: strategy });
      if (r.status === 'ok') {
        this._runningToggles = this._collectToggles();
        showToast('Перезапущено: ' + strategy, 'ok');
      } else {
        showToast('Ошибка: ' + r.message, 'error');
      }
    } catch (e) {
      showToast('Ошибка перезапуска: ' + e.message, 'error');
    }
    btn.disabled = false;
    this._updateApplyHint();
    Status.refresh();
  },

  // Запуск стратегии (из вердикта тестера, из тостов списков, с Главной).
  // gotoMain=false - остаться на текущей вкладке.
  async applyStrategy(profile, gotoMain = true) {
    if (!profile || this._busy || App.testActive) return;
    if (!await this._configReady('запуск стратегии')) return;
    this._setBusy(true);
    try {
      const sel = $('strategySelect');
      if (sel && Array.from(sel.options).some(o => o.value === profile)) sel.value = profile;
      await this._postConfigOrThrow(Object.assign({ last_profile: profile }, this._collectToggles()));
      const r = await apiPost('/start', { profile });
      if (r.status === 'ok') {
        this._runningToggles = this._collectToggles();
        showToast('Обход запущен: ' + profile, 'ok');
        if (gotoMain) window.location.hash = 'main';
      } else {
        showToast('Не удалось запустить: ' + (r.message || 'ошибка'), 'error');
      }
    } catch (e) {
      showToast('Ошибка запуска: ' + e.message, 'error');
    }
    this._setBusy(false);
    this._updateApplyHint();
    Status.refresh();
  },

  _setBusy(b) {
    this._busy = b;
    $('btnZ2Toggle').disabled = b;
    ['btnSvcRepair', 'btnSvcInstall', 'btnSvcStart', 'btnSvcStop', 'btnSvcRemove'].forEach(id => {
      $(id).disabled = b;
    });
  },


};
