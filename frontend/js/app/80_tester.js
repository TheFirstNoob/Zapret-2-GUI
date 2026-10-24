const TesterPage = {
  state: {
    extendedTest: false, collectLogs: false,
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
      if (this._diagDoneRecently()) $('diagDoneNote').hidden = false;
      this.bindModals();
    }
  },

  // «выполнена» у шага 1 - только если диагностика реально была за сутки
  _diagDoneRecently() {
    const ts = +localStorage.getItem('z2_diag_done') || 0;
    return ts && (Date.now() - ts) < 24 * 60 * 60 * 1000;
  },

  // ── таблица стратегий ──

  _label(key) {
    if (key === '__naked__') return 'Без защиты (базовый уровень)';
    if (key === '__current__') return 'Zapret 1 (текущий)';
    return key;
  },

  _resetTable() {
    // Гасим отложенную очередь _addHostRow: «долётелившие» строки прошлого
    // теста не должны влиться в таблицу нового запуска.
    this._addHostRow.resetQueue();
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
      '<td class="col-rate">-</td><td class="col-mini">-</td><td class="col-mini">-</td><td class="col-rate">0/0</td>';

    const detail = document.createElement('tr');
    detail.className = 'strat-detail';
    detail.hidden = true;
    detail.innerHTML = `<td colspan="6">
      <div class="subtable-header">
        <span>Проверка хостов в стратегии «${escapeHtml(this._label(key))}»</span>
        <span>статус / задержка</span>
      </div>
      <table class="host-table"><tbody></tbody></table></td>`;

    $('stratTbody').appendChild(tr);
    $('stratTbody').appendChild(detail);
    if (key === '__naked__' || key === '__current__') tr.classList.add('row-baseline');

    const toggleDetail = () => { detail.hidden = !detail.hidden; tr.setAttribute('aria-expanded', detail.hidden ? 'false' : 'true'); };
    tr.addEventListener('click', toggleDetail);
    tr.tabIndex = 0;
    tr.setAttribute('aria-expanded', 'false');
    tr.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleDetail(); }
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
      // Предыдущую стратегию закрываем честно: у «голого теста» отдельного
      // сигнала о финише нет - строка висела «тестируется…»
      const prevKey = this.state.currentKey;
      this._finishRow(prevKey);
      if (this._completedSeen) this._completedSeen.add(prevKey);
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
    const fn = function (item) {
      queue.push(item);
      if (!timer) timer = setTimeout(() => {
        const batch = queue; queue = []; timer = null;
        processFn(batch);
      }, delayMs);
    };
    // Полный сброс очереди (новый тест - старые отложенные строки не нужны).
    fn.resetQueue = function () {
      if (timer) { clearTimeout(timer); timer = null; }
      queue = [];
    };
    return fn;
  })(function (batch) { for (const b of batch) TesterPage._addHostImmediate(b); }, 90),

  _addHostImmediate(data) {
    const row = this._rowFor(data.profile);
    const mapKey = (data.domain || '') + '|' + (data.test_type || '');
    const isOk = data.status === 'OK';
    const isPing = data.test_type === 'ping';
    // QUIC-класс (youtube и др.): TCP-проба сторонним клиентом под десинком
    // не показательная - нейтральный серый статус вместо красного креста.
    const isQuirk = !isPing && QUIRK_HOSTS.has(data.domain);
    const isQuicStatus = isQuirk && data.status === 'QUIC';
    // rated/control - бэкендовая категория: live-счётчики «Хосты» считаются
    // только по rated - иначе прыгают (17/17 → 8/8) на финальном network_rate
    const isRated = data.rated === undefined ? (!isPing && !isQuirk) : !!data.rated;
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
      if (!isPing && isRated) row.netTotal++;
    }
    h.ok = isOk;
    // считаем «доступность» и «хосты» вживую (сеть, без пингов - как финальный network_rate);
    // quirk-хосты не входят ни в rate, ни в счётчики
    if (isOk && !wasOk) { row.ok++; if (!isPing && isRated) row.netOk++; }
    if (!isOk && wasOk) { row.ok--; if (!isPing && isRated) row.netOk--; }
    row.hostsCell.innerHTML = row.netOk + '/' + row.netTotal +
      (row.total > row.netTotal
        ? ` <span class="meta">(${row.total})</span>` : '');
    if (row.netTotal) {
      const rate = row.netOk / row.netTotal * 100;
      row.rateCell.innerHTML = `<span class="${rateClass(rate)}">${rate.toFixed(0)}%</span>`;
    }
    h.tr.className = isOk ? 'hrow-ok'
      : data.status === 'QUIC' ? 'hrow-quirk'
      : isPing ? 'hrow-quirk'
      : (data.status === 'TIMEOUT' || data.status === 'BLOCKED' || data.status === 'FAIL'
        ? 'hrow-err' : 'hrow-warn');
    const stIcon = isOk ? '<span class="st-ok">✓</span>'
      : data.status === 'QUIC' ? '<span class="st-quirk">≈ QUIC</span>'
      : isPing ? '<span class="st-quirk">ping</span>'
      : data.status === 'TIMEOUT' || data.status === 'BLOCKED' || data.status === 'FAIL'
        ? '<span class="st-err">✗</span>'
        : '<span class="st-warn">•</span>';
    const cells = h.tr.children;
    cells[0].innerHTML = stIcon;
    cells[2].textContent = data.test_type || '';
    cells[3].textContent = data.status_code || (data.status === 'TCP16_20' ? 'DPI' : '');
    cells[4].textContent = data.time_ms != null ? formatTime(data.time_ms) : '';
    cells[5].textContent = data.error || '';
    row.hosts.set(mapKey, h);
    if (data.domain === 'discord.com' || (data.domain === 'gateway.discord.gg' && !row._discord)) {
      row._discord = true;
      row.discordCell.innerHTML = isOk ? '<span class="st-ok">✓</span>' : '<span class="st-err">✗</span>';
    }
    if (data.domain === 'www.youtube.com' && !row._yt) {
      row._yt = true;
      row.ytCell.innerHTML = isOk ? '<span class="st-ok">✓</span>'
        : data.status === 'QUIC' ? '<span class="st-quirk">QUIC</span>'
        : data.status === 'H3_NONE' ? '<span class="st-warn">•</span>'
        : '<span class="st-err">✗</span>';
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
    this._completedSeen = new Set();
    let started = false;
    let pollActive = true;
    let pollFails = 0;   // подряд идущих сбоев опроса (не роняем прогон сразу)
    const actPage = { cdn_scan: 'cdn', asn_scan: 'asn' }[actionData.action] || 'tester';

    // apiPost, а не сырой fetch: тот несёт AbortSignal.timeout(30с) и ту же
    // обработку ошибки. Раньше без таймаута зависший POST навсегда оставлял
    // started=false, а setInterval ниже крутился вечно, удерживая блокировку
    // всех кнопок проверки (App.setTestActive).
    apiPost('/tester/action', actionData).then(() => {
      started = true;
    }).catch((e) => {
      pollActive = false;
      App.setTestActive(false);
      showToast('Проверку не удалось запустить: ' + (e.message || e), 'error');
      if (onError) onError();
    });

    const pollId = setInterval(() => {
      if (!pollActive) { clearInterval(pollId); return; }
      if (!started) return;
      apiGet('/tester/status').then(state => {
        if (!pollActive) return;
        pollFails = 0;            // успешный ответ - счётчик сбоев сброшен
        if (state.cancelled) {
          frontendLog('poll: cancelled');
          pollActive = false; clearInterval(pollId);
          Activity.done('Отменено');
          $('testCurrentPhase').textContent = 'Тест отменён';
          this.clearElapsedTimer();
          setTimeout(() => this.resetToIntro('отменён пользователем'), 1300);
          return;
        }
        if (state.progress) {
          this._setProgress(startPercent + (state.progress.percent || 0) * scalePercent);
          Activity.set(actPage, state.progress.message || 'Выполняется…',
                       state.progress.percent, true);
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
        // Надёжное закрытие строк: сервер отдаёт список завершённых стратегий;
        // закрываем один раз на стратегию (повторный вызов сворачивал бы
        // раскрытые пользователем списки доменов)
        const seen = this._completedSeen || (this._completedSeen = new Set());
        for (const key of (state.completed || [])) {
          if (!seen.has(key)) {
            seen.add(key);
            this._finishRow(key);
          }
        }
        if (!state.running) {
          // финальная синхронизация: строка последней стратегии могла не
          // получить своё «Стратегия X: N%» (progress перезаписался) -
          // все «тестируется…» закрываем, иначе висят вечно
          for (const [k, row] of this.state.rows) {
            if (row.stateText && row.stateText.textContent === 'тестируется…') {
              this._finishRow(k);
            }
          }
          const fr = state.final_result;
          if (state.error) {
            frontendLog('poll: finished with error: ' + state.error);
            pollActive = false; clearInterval(pollId);
            Activity.fail('Ошибка: ' + state.error);
            this.clearElapsedTimer();
            $('testCurrentPhase').textContent = 'Ошибка: ' + state.error;
            showToast('Тест прерван: ' + state.error, 'error');
            setTimeout(() => this.resetToIntro('ошибка теста'), 2500);
            return;
          }
          if (!fr) {
            frontendLog('poll: finished WITHOUT result (known=' + known + ')');
            pollActive = false; clearInterval(pollId);
            Activity.fail('Тест завершился без результата');
            this.clearElapsedTimer();
            $('testCurrentPhase').textContent = 'Тест завершился без результата';
            showToast('Тест завершился без результата - запустите подбор заново', 'warn');
            setTimeout(() => this.resetToIntro('тест без результата'), 1800);
            return;
          }
          frontendLog('poll: finished OK (type=' + (fr.type || '?') + ')');
          pollActive = false; clearInterval(pollId);
          Activity.done('Готово');
          if (state.all_results && !fr.all_results) fr.all_results = state.all_results;
          if (fr.restored) showToast(fr.restored, /Не удалось|не восстановлен/.test(fr.restored) ? 'warn' : 'ok');
          if (resultType && fr.type === resultType) { if (onResult) onResult(fr); }
          else if (fr.type === 'current_result') { this.state.currentResults = fr; this.runFullPipelinePhase1(); }
          else if (fr.type === 'need_zapret1') {
            this.clearElapsedTimer();
            $('testRun').hidden = true;
            Modal.open('needZapret1Overlay');
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
      }).catch((e) => {
        if (!pollActive) return;
        // Разовый сбой опроса - не повод убивать прогон: серверный тест
        // продолжается сам, и результат мы всё ещё можем увидеть. Терпим
        // несколько подряд (5 = ~2с) и только потом сдаёмся.
        pollFails += 1;
        if (pollFails < 5) return;
        pollActive = false; clearInterval(pollId);
        App.setTestActive(false);
        frontendLog('poll: отказоустойчивость исчерпана, ошибок подряд=' + pollFails
                     + ' err=' + (e && e.message ? e.message : e));
        Activity.fail('Связь с программой потеряна - проверка могла не завершиться');
        showToast('Потеряна связь с программой. Проверка на сервере могла остаться '
                  + 'незавершённой - откройте «Подбор стратегии» заново', 'warn');
        if (onError) onError();
      });
    }, 350);
    return pollId;
  },

  // ── запуск ──

  startTest() {
    frontendLog('btn: Начать подбор (extended=' + $('extendedCheck').checked + ')');
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
          Modal.open('vpnOverlay');
          $('vpnStatus').textContent = '';
        } else {
          this.runPipeline();
        }
      },
      onError: () => this.runPipeline(),
    });
  },

  runPipeline() {
    App.setTestActive(true);
    Modal.close('vpnOverlay');
    $('testerIntro').hidden = true;
    $('testRun').hidden = false;
    $('testCurrentPhase').textContent = 'Подготовка…';
    this._setProgress(0);
    $('testProgressMsg').textContent = '';
    $('btnStartTest').disabled = true;
    // Скелетон: строки известных участников видны сразу («в очереди»),
    // таблица не выглядит замершей до первых результатов.
    const planned = this.state.advancedTest
      ? ['__current__', '__naked__', ...PROFILES]
      : ['__naked__', ...PROFILES];
    planned.forEach(p => this._rowFor(p));
    this.startElapsedTimer();
    if (this.state.advancedTest) this.runFullPipelinePhase0();
    else this.runBasicPhase2();
  },

  _setProgress(pct) {
    const fill = $('testProgressFill');
    const v = Math.min(100, Math.max(0, pct));
    fill.style.width = v + '%';
    fill.setAttribute('aria-valuenow', v);
    // Кот на краю заливки имеет смысл только когда заливка уже видна.
    fill.parentElement.classList.toggle('has-cat', pct >= 5);
  },

  runBasicPhase2() {
    $('testCurrentPhase').textContent = 'Стратегии тестируются по очереди';
    this._startTesterAction(
      { action: 'test_profiles', profiles: PROFILES,
        alt_params: !!($('altParamsCheck') && $('altParamsCheck').checked) },
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
    this._startTesterAction({ action: 'current' }, {
      progressConfig: { startPercent: 0, scalePercent: 0.08 },
      onError: () => { $('testCurrentPhase').textContent = 'Ошибка (Zapret 1)'; this.clearElapsedTimer(); },
    });
  },

  runFullPipelinePhase1() {
    $('testCurrentPhase').textContent = 'Фаза 2 из 4: базовый уровень без защиты';
    this._startTesterAction({ action: 'naked' }, {
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
    $('testCurrentPhase').textContent = 'Фаза 3 из 4: стратегии Zapret 2';
    this._startTesterAction(
      { action: 'test_profiles', profiles: PROFILES,
        alt_params: !!($('altParamsCheck') && $('altParamsCheck').checked) },
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
    this._setProgress(95);
    this.finalizePipeline('full');
  },

  // ── заполнение таблицы финальными числами ──

  _markUntested() {
    // Скелетон-строки, до которых прогон не дошёл (например «custom» не
    // собралась) - переводим из «в очереди» в честное «-».
    for (const row of this.state.rows.values()) {
      if (row.stateText && row.stateText.textContent === 'в очереди') {
        row.stateText.textContent = '-';
        row.stateDot.className = 'dot dot-idle';
      }
    }
  },

  _fillTable(allResults) {
    for (const r of allResults) {
      const key = r.profile || '';
      const row = this._rowFor(key);
      const rate = r.network_rate != null ? r.network_rate : (r.success_rate || 0);
      row.rateCell.innerHTML = `<span class="${rateClass(rate)}">${rate.toFixed(0)}%</span>`;
      if (r.net_ok_count != null) row.hostsCell.textContent = r.net_ok_count + '/' + r.net_total;
      const statusOf = (domains) => {
        const found = (r.results || []).filter(x => domains.includes(x.domain) && x.test_type !== 'ping');
        if (!found.length) return '-';
        if (found.some(x => x.status === 'OK'))
          return '<span class="st-ok">✓</span>';
        // QUIC-класс: подтверждённый QUIC - нейтральный бейдж; H3_NONE - серый
        // маркер вместо красного креста (внешнее ревью 13.10, P2-2).
        if (found.some(x => x.status === 'QUIC')) return '<span class="st-quirk">QUIC</span>';
        if (found.some(x => x.status === 'H3_NONE')) return '<span class="st-warn">•</span>';
        return '<span class="st-err">✗</span>';
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
    App.setTestActive(false);
    this.clearElapsedTimer();
    this._setProgress(100);
    $('testCurrentPhase').textContent = 'Готово';
    $('btnStartTest').disabled = false;
    $('testRun').hidden = true;
    this._markUntested();

    const el = $('testSummary');
    let html = '';

    if (mode === 'basic') {
      const p2 = this.state.phase2Results || {};
      const rec = p2.recommendation;
      const custom = p2.custom;
      const naked = p2.naked;

      if (rec) html += this._renderVerdict(rec);
      else html += '<div class="detail-section"><span class="detail-head st-warn">Итог не определён</span><p class="detail-text">Нет результатов - запустите подбор заново.</p></div>';

      if (custom && custom.summary) {
        const rel = custom.relation === 'better' ? '- обгоняет лучшую'
          : custom.relation === 'worse' ? '- уступает лучшей'
          : custom.relation === 'equal' ? '- равна лучшей' : '';
        const rateTxt = custom.rate != null ? ` (${custom.rate}%)` : '';
        html += `<div class="detail-section">
          <span class="detail-head">Личная стратегия «custom»</span>
          <p class="detail-text">${escapeHtml(custom.summary)}${rel ? ' ' + rel : ''}${rateTxt}.
          ${custom.valid
            ? 'Если «custom» помечена лучшей в таблице - запускайте её кнопкой выше.'
            : 'Не прошла проверку движком - запускать её не стоит.'}
          ${custom.error && !custom.valid ? `<span class="st-err">${escapeHtml(custom.error)}</span>` : ''}</p>
        </div>`;
      } else if (custom && custom.error) {
        html += `<div class="detail-section">
          <span class="detail-head st-err">Личная стратегия не собрана</span>
          <p class="detail-text st-err">${escapeHtml(custom.error)}</p>
        </div>`;
      }

      if (naked && naked.net_total) {
        html += `<div class="detail-section">
          <span class="detail-head">Базовый уровень (без защиты): <span class="${rateClass(naked.network_rate || 0)}">${(naked.network_rate || 0).toFixed(0)}%</span></span>
          <p class="detail-text">Столько сервисов доступно вообще без Zapret. Столбец «Без защиты» в таблице - точка отсчёта.</p>
        </div>`;
      }

      if (rec && rec.blocked_domains && rec.blocked_domains.length && rec.verdict !== 'ok') {
        html += `<div class="detail-section" style="background: var(--err-bg); border-color: var(--err-line);">
          <span class="detail-head" style="color: #f0b7b8;">Не пробито ни одной стратегией (${rec.blocked_domains.length} хост${rec.blocked_domains.length > 1 ? 'а' : ''})</span>
          <p class="detail-text" style="color: #f0c6c6;">Если это ваши рабочие домены - добавьте их в «Списки → Домены - обрабатывать».</p>
          <div class="chip-list">${rec.blocked_domains.map(d => `<span class="fail-domain">${escapeHtml(d)}</span>`).join('')}</div>
        </div>`;
      }
    } else {
      const cur = this.state.currentResults;
      const naked = this.state.nakedResults;
      const fa = this.state.fullAnalysisResults || [];
      const rateOf = r => (r.network_rate != null ? r.network_rate : (r.success_rate || 0));
      const best = fa.length ? fa.reduce((a, b) => rateOf(a) > rateOf(b) ? a : b) : null;
      html += `<div class="detail-section">
        <span class="detail-head">Сравнение</span>
        <table class="check-table"><tbody>
          <tr><td class="check-name">Zapret 1 (текущий)</td><td class="mono">${cur ? rateOf(cur).toFixed(0) + '%' : '-'}</td></tr>
          <tr><td class="check-name">Без защиты</td><td class="mono">${naked ? rateOf(naked).toFixed(0) + '%' : '-'}</td></tr>
          <tr><td class="check-name">Zapret 2, лучшая${best ? ' («' + escapeHtml(best.profile || '') + (best.blob ? ' + ' + escapeHtml(best.blob) : '') + '»)' : ''}</td>
              <td class="mono ${best ? rateClass(rateOf(best)) : ''}">${best ? rateOf(best).toFixed(0) + '%' : '-'}</td></tr>
        </tbody></table>
        <p class="detail-text">Подробности каждой комбинации - в таблице стратегий (клик по строке).</p>
      </div>`;
    }

    if (this.state.collectLogs) {
      html += `<div class="detail-section" style="display:flex;gap:12px;align-items:center">
        <button class="btn btn-primary" id="btnShowCollect">Сохранить отчёт для поддержки</button>
        <span class="meta">ZIP с результатами теста сохранится в папку программы</span>
      </div>`;
    }
    html += `<div class="results-actions"><button class="btn" id="btnBackToIntro">Новый подбор</button></div>`;

    el.innerHTML = html;
    el.hidden = false;
    if ($('btnShowCollect')) $('btnShowCollect').addEventListener('click', () => this.showCollectForm());
    $('btnBackToIntro').addEventListener('click', () => this.resetToIntro('кнопка назад'));
    const recBtn = $('btnApplyRec');
    const bestProfile = (mode === 'basic' && rec && rec.best_profile) ? rec.best_profile : null;
    if (recBtn && bestProfile) {
      recBtn.addEventListener('click', () => MainPage.applyStrategy(bestProfile));
    }
  },

  _renderVerdict(rec) {
    const vm = {
      ok: ['Обход работает', 'badge-ok'],
      partial: ['Частичный обход', 'badge-warn'],
      no_bypass: ['Обход не сработал', 'badge-err'],
      engine_broken: ['Проблема с движком Zapret', 'badge-err'],
      no_data: ['Нет данных', 'badge-mute'],
    };
    const [title, badgeCls] = vm[rec.verdict] || vm.no_data;
    const isBad = rec.verdict === 'no_bypass' || rec.verdict === 'engine_broken';
    let subtitle = escapeHtml(rec.message || '');
    let chips = '';
    if (rec.key_hosts && rec.key_hosts.length) {
      const okN = rec.key_hosts.filter(k => k.status === 'OK' || k.status === 'QUIC_OK').length;
      if (!subtitle) subtitle = `Успешно пробито <b>${okN} из ${rec.key_hosts.length}</b> ключевых сервисов.`;
      chips = '<div class="services-grid">' + rec.key_hosts.map(k => {
        const ok = k.status === 'OK' || k.status === 'QUIC_OK';
        const quic = k.status === 'QUIC_OK';
        const unknown = k.status === 'QUIC_UNKNOWN';
        const mark = ok ? '<span class="mark-ok">✓</span>'
          : unknown ? '<span class="st-warn">•</span>'
          : '<span class="mark-bad">✗</span>';
        const pingTxt = k.time_ms ? formatTime(k.time_ms)
          : (ok ? 'доступен' : unknown ? 'не подтверждён' : 'не пробит');
        return `<div class="service-chip">
          <div class="chip-head">${mark} ${escapeHtml(k.label)}${quic ? ' <span class="st-quirk">QUIC</span>' : ''}</div>
          <div class="chip-ping ${ok || unknown ? '' : 'chip-ping-bad'}">${pingTxt}</div>
          ${k.note ? `<div class="chip-note">${escapeHtml(k.note)}</div>` : ''}
        </div>`;
      }).join('') + '</div>';
    }
    let actions = '';
    if (isBad) {
      actions = `<button class="btn btn-primary hero-btn" onclick="location.hash='diagnostics'">Открыть проверку системы</button>
        ${rec.best_profile ? '<span class="meta">лучшая из протестированных: ' + escapeHtml(rec.best_profile) + '</span>' : ''}`;
    } else if (rec.best_profile) {
      actions = `<button class="btn btn-primary hero-btn" id="btnApplyRec">Запустить: ${escapeHtml(rec.best_profile)}
        (${(rec.best_network_rate || 0).toFixed(0)}%)</button>`;
    }
    if (rec.same_as_naked) {
      actions += '<span class="meta">результат как без защиты - обход не применяется</span>';
    }
    const badgeExtra = rec.best_network_rate != null && rec.verdict !== 'no_data'
      ? ' · ' + rec.best_network_rate.toFixed(0) + '% успеха' : '';
    return `<div class="verdict-hero">
      <div class="verdict-top">
        <div>
          <span class="verdict-badge ${badgeCls}">${escapeHtml(title)}${badgeExtra}</span>
          <div class="verdict-title">${isBad
            ? escapeHtml(title)
            : (rec.best_profile ? 'Рекомендована стратегия «' + escapeHtml(rec.best_profile) + '»' : escapeHtml(title))}</div>
          ${subtitle ? `<div class="verdict-subtitle">${subtitle}</div>` : ''}
        </div>
      </div>
      ${chips}
      ${rec.top3 && rec.top3.length > 1 ? `<div class="detail-section">
        <span class="detail-head">Топ стратегий</span>
        <p class="detail-text">${rec.top3.map((t, i) =>
          `${i + 1}. <b>${escapeHtml(t.name)}</b> - ${t.rate.toFixed(0)}% (${t.net_ok}/${t.net_total})`
        ).join('<br>')}<br><span class="st-quirk">разница в пределах ±1 домена - погрешность прогона, стратегии практически равнозначны</span></p>
      </div>` : ''}
      <div class="verdict-actions">${actions}</div>
    </div>`;
  },

  bindModals() {
    $('vpnCancelBtn').addEventListener('click', () => {
      Modal.close('vpnOverlay');
      this.resetToIntro();
    });
    $('retryVpnBtn').addEventListener('click', () => {
      Modal.close('vpnOverlay');
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
      Modal.close('needZapret1Overlay');
      this.resetToIntro();
    });
    $('checkZapret1Btn').addEventListener('click', () => {
      $('needZapret1Status').textContent = 'Проверка…';
      $('checkZapret1Btn').disabled = true;
      this._startTesterAction({ action: 'check-winws' }, {
        onResult: (d) => {
          $('checkZapret1Btn').disabled = false;
          if (d.running) {
            Modal.close('needZapret1Overlay');
            $('testRun').hidden = false;
            this.runFullPipelinePhase0();
          } else {
            $('needZapret1Status').textContent = 'winws.exe всё ещё не найден - запустите батник Zapret 1.';
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

    // Escape и клик по фону закрывают модалки (как «Отмена»).
    const closeModal = (id, onCancel) => {
      const ov = $(id);
      ov.addEventListener('mousedown', (e) => {
        if (e.target === ov) onCancel();
      });
    };
    closeModal('vpnOverlay', () => $('vpnCancelBtn').click());
    closeModal('needZapret1Overlay', () => $('needZ1CancelBtn').click());
    closeModal('collectFormOverlay', () => this.closeCollectForm());
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if ($('collectFormOverlay').classList.contains('open')) this.closeCollectForm();
      else if ($('vpnOverlay').classList.contains('open')) $('vpnCancelBtn').click();
      else if ($('needZapret1Overlay').classList.contains('open')) $('needZ1CancelBtn').click();
    });
  },

  cancelTest() {
    frontendLog('btn: Отменить тест');
    fetch('/api/tester/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'cancel' }),
    }).catch(() => {});
    $('testCurrentPhase').textContent = 'Отмена…';
  },

  resetToIntro(reason) {
    frontendLog('resetToIntro: ' + (reason || 'без причины (кнопка)'));
    App.setTestActive(false);
    this.clearElapsedTimer();
    $('testRun').hidden = true;
    $('testSummary').hidden = true;
    $('testerIntro').hidden = false;
    $('btnStartTest').disabled = false;
    if (this._diagDoneRecently()) $('diagDoneNote').hidden = false;
  },

  // ── сбор отчёта ──

  showCollectForm() {
    $('collectCity').value = '';
    $('collectIsp').value = '';
    $('collectBatLabel').textContent = 'Файл стратегии Zapret 1 (.bat) - по желанию';
    $('collectBatZone').classList.remove('filed');
    $('collectConsent').checked = false;
    $('collectSubmitBtn').disabled = false;
    $('collectSubmitBtn').textContent = 'Сохранить отчёт';
    this.state.collectBatFile = null;
    Modal.open('collectFormOverlay');
  },

  closeCollectForm() { Modal.close('collectFormOverlay'); },

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
      total_time_ms: r.total_time_ms, results: r.results,
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

  // ── Анализ процесса (game/app network probe) ──────────────
  _probePollTimer: null,
  _probeStarting: false,
  _probeStartAt: 0,
  _probeDuration: 60,
  _probeTimer: null,
  _probeScanned: false,
  _probeProcesses: [],

  _setProbeState(text, cls) {
    const chip = $('probeState');
    if (!chip) return;
    const dot = chip.querySelector('.dot');
    const txt = chip.querySelector('.state-text');
    const map = { idle: ['dot-idle', 'st-mute'], live: ['dot-ok', 'st-ok'], done: ['dot-ok', 'st-ok'], err: ['dot-err', 'st-err'] };
    const [dc, tc] = map[cls] || map.idle;
    dot.className = 'dot ' + dc;
    txt.className = 'state-text ' + tc;
    txt.textContent = text;
  },

  async scanProbeProcesses(quiet) {
    if (quiet && this._probeScanned) return;
    const btn = $('probeScanBtn');
    const statusEl = $('probeStatus');
    if (statusEl) { statusEl.hidden = false; statusEl.textContent = 'Сканирование процессов…'; statusEl.className = 'probe-status'; }
    if (btn) btn.disabled = true;
    try {
      const r = await apiPost('/process-probe/scan', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const sel = $('probeProcSelect');
      sel.innerHTML = '<option value="">- выберите процесс -</option>';
      const groups = {};
      for (const p of (r.processes || [])) {
        if (!groups[p.name]) groups[p.name] = { count: 0, title: p.title || '' };
        groups[p.name].count++;
        if (!groups[p.name].title && p.title) groups[p.name].title = p.title;
      }
      for (const name of Object.keys(groups).sort()) {
        const g = groups[name];
        const suffix = g.count > 1 ? ` (${g.count} процесса)` : '';
        const title = g.title ? ` - ${g.title}` : '';
        const o = document.createElement('option');
        o.value = name;
        o.textContent = name + suffix + title;
        sel.appendChild(o);
      }
      const total = (r.processes || []).length;
      this._probeScanned = true;
      this._probeProcesses = r.processes || [];
      if (statusEl) { statusEl.textContent = `Найдено процессов: ${total}`; statusEl.className = 'probe-status'; }
      if (!quiet) showToast(`Найдено процессов: ${total}`, 'ok');
      this._hintProbeProcess();
    } catch (e) {
      if (statusEl) { statusEl.textContent = 'Ошибка: ' + (e.message || e); statusEl.className = 'probe-status st-err'; }
      if (!quiet) showToast('Сканирование: ' + (e.message || e), 'error');
    }
    if (btn) btn.disabled = false;
  },

  _probeTick() {
    const el = $('probeLiveTimer');
    if (!el) return;
    const s = Math.floor((Date.now() - this._probeStartAt) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2, '0');
    const ss = String(s % 60).padStart(2, '0');
    // total в mm:ss (L6: 120 сек писалось как «00:120»)
    const totalMm = String(Math.floor(this._probeDuration / 60)).padStart(2, '0');
    const totalSs = String(this._probeDuration % 60).padStart(2, '0');
    el.textContent = this._probeDuration > 0
      ? `${mm}:${ss} / ${totalMm}:${totalSs}`
      : `${mm}:${ss} / ∞`;
  },

  // Живая подсказка по ручному вводу процесса: имя/PID из отсканированного
  // списка, ближайшие совпадения по имени, режим ожидания для ещё не запущенных.
  _hintProbeProcess() {
    const box = $('probeProcHint');
    const input = $('probeProcInput');
    if (!box || !input) return;
    const v = (input.value || '').trim();
    if (!v) { box.hidden = true; return; }
    const list = this._probeProcesses || [];
    box.hidden = false;
    box.innerHTML = '';
    const esc = escapeHtml;
    const add = (cls, html) => { box.insertAdjacentHTML('beforeend', `<span class="${cls}">${html}</span>`); };
    const norm = s => s.toLowerCase().replace(/\.exe$/, '');

    if (/^\d+$/.test(v)) {
      const pid = parseInt(v, 10);
      const hit = list.find(p => p.pid === pid);
      if (hit) {
        add('pp-hint-ok', `✓ PID ${pid} - ${esc(hit.name)}${hit.title ? ' · ' + esc(hit.title) : ''}`);
      } else {
        add('pp-hint-err', `PID ${pid} не найден среди процессов с сетью - если процесс ещё не запущен, анализатор дождётся его`);
      }
      return;
    }

    const vn = norm(v);
    const exact = list.filter(p => norm(p.name) === vn);
    if (exact.length) {
      const names = [...new Set(exact.map(p => p.name))];
      add('pp-hint-ok', `✓ найден: ${esc(names.join(', '))} - ${exact.length} процесс${exact.length > 1 ? 'а' : ''} с сетью`);
      return;
    }

    const subs = [...new Set(list.map(p => norm(p.name)).filter(n => n.includes(vn)))].slice(0, 4);
    if (subs.length) {
      add('pp-hint-warn', 'Возможно, вы имели в виду: ');
      subs.forEach(n => {
        const b = document.createElement('span');
        b.className = 'pp-sugg';
        b.textContent = n;
        b.addEventListener('click', () => {
          $('probeProcInput').value = n;
          this._hintProbeProcess();
        });
        box.appendChild(b);
      });
      return;
    }

    if (!list.length) add('pp-hint-mute', 'Список процессов ещё не загружен - нажмите «Сканировать»');
    else add('pp-hint-err', 'не найден в списке - без активных соединений или ещё не запущен (анализатор дождётся его)');
  },

  async startProbe() {
    if (this._probePollTimer || this._probeStarting) return;
    this._probeStarting = true;
    const btn = $('probeStartBtn');
    btn.disabled = true;
    const process = ($('probeProcInput').value || '').trim()
      || ($('probeProcSelect').value || '').trim();
    if (!process) {
      showToast('Впишите имя процесса или PID', 'error');
      btn.disabled = false;
      this._probeStarting = false;
      return;
    }
    const duration = $('probeDurSelect').value || 60;
    try {
      const r = await apiPost('/process-probe/start', { process, duration });
      if (r.status !== 'ok') {
        showToast('Анализ: ' + (r.message || 'ошибка'), 'error');
        btn.disabled = false;
        return;
      }
      $('probeStopBtn').hidden = false;
      $('probeStartBtn').hidden = true;
      $('probeReportBtn').hidden = true;
      $('probeResults').hidden = true;
      $('probeResults').innerHTML = '';
      $('probeIdle').hidden = true;
      $('probeLive').hidden = false;
      $('probeLiveBar').hidden = false;
      $('probeVerdict').hidden = true;
      $('probeStatus').hidden = true;
      $('probeTbody').innerHTML = '<tr><td colspan="4"><div class="empty-note">Наблюдение…</div></td></tr>';
      $('probeLiveTitle').textContent = `Прослушивание сетевого трафика процесса «${process}»`;
      $('probeLiveSub').textContent = 'Пакетов: 0 · Соединений: 0';
      this._probeStartAt = Date.now();
      this._probeDuration = +duration;
      this._probeTick();
      if (this._probeTimer) clearInterval(this._probeTimer);
      this._probeTimer = setInterval(() => this._probeTick(), 1000);
      this._setProbeState('Перехват пакетов', 'live');
      this._probePollTimer = setInterval(() => this.pollProbe(), 2000);
      this.pollProbe();
    } catch (e) {
      showToast('Анализ не запустился: ' + (e.message || e), 'error');
      btn.disabled = false;
    } finally {
      this._probeStarting = false;
    }
  },

  async pollProbe() {
    let r;
    try {
      r = await apiGet('/process-probe/status');
    } catch (e) {
      this._stopProbePolling();
      if (this._probeTimer) { clearInterval(this._probeTimer); this._probeTimer = null; }
      const start = $('probeStartBtn');
      if (start) { start.disabled = false; start.hidden = false; }
      $('probeStopBtn').hidden = true;
      this._setProbeState('Ошибка анализа', 'err');
      showToast('Анализ: ' + (e.message || e), 'error');
      return;
    }
    if (r.status !== 'ok') {
      this._stopProbePolling();
      if (this._probeTimer) { clearInterval(this._probeTimer); this._probeTimer = null; }
      const start = $('probeStartBtn');
      if (start) { start.disabled = false; start.hidden = false; }
      $('probeStopBtn').hidden = true;
      this._setProbeState('Ошибка анализа', 'err');
      showToast('Анализ: ' + (r.message || 'ошибка статуса'), 'error');
      return;
    }
    const st = r.state || {};
    const stEl = $('probeStatus');
    if (st.error) {
      if (stEl) { stEl.hidden = false; stEl.textContent = st.error; stEl.className = 'probe-status st-err'; }
      this._setProbeState('Ошибка анализа', 'err');
    } else if (st.phase && stEl) {
      stEl.hidden = false;
      stEl.textContent = st.phase;
      stEl.className = 'probe-status';
    }
    this.renderProbe(st);
    if (st.phase === 'завершено' || st.error) {
      this._stopProbePolling();
      if (this._probeTimer) { clearInterval(this._probeTimer); this._probeTimer = null; }
      $('probeStartBtn').disabled = false;
      $('probeStartBtn').hidden = false;
      $('probeStopBtn').hidden = true;
      $('probeReportBtn').hidden = false;
      this._setProbeState(st.error ? 'Анализ прерван' : '✓ Анализ завершён', st.error ? 'err' : 'done');
      if (stEl && !st.error) stEl.hidden = true;
      const liveBar = $('probeLiveBar');
      if (liveBar) liveBar.hidden = true;
      if (st.error) showToast('Анализ: ' + st.error, 'error');
    }
  },

  _stopProbePolling() {
    if (this._probePollTimer) {
      clearInterval(this._probePollTimer);
      this._probePollTimer = null;
    }
  },

  async stopProbe() {
    const stop = $('probeStopBtn');
    if (stop) stop.disabled = true;
    this._setProbeState('Останавливается…', 'live');
    const bar = $('probeLiveBar');
    if (bar) bar.hidden = true;  // живая плашка исчезает сразу
    if (this._probeTimer) { clearInterval(this._probeTimer); this._probeTimer = null; }
    try {
      await apiPost('/process-probe/stop', {});
      // Поллинг не гасим: pollProbe дождётся финальной фазы («завершено»),
      // скроет строку фазы и отрисует итог (баг: статус зависал после «Стоп»).
      this.pollProbe();
    } catch (e) {
      showToast('Остановка анализа: ' + (e.message || e), 'error');
      this._setProbeState('Ошибка остановки', 'err');
    } finally {
      if (stop) stop.disabled = false;
    }
  },

  async saveProbeReport() {
    try {
      const r = await apiPost('/process-probe/report', {});
      if (r.status === 'ok' && r.report) {
        const el = $('probeResults');
        el.hidden = false;
        el.innerHTML = '<pre class="probe-report">' + escapeHtml(r.report) + '</pre>';
        showToast('Отчёт сохранён: ' + r.path, 'ok');
      } else {
        showToast('Не удалось сохранить отчёт', 'error');
      }
    } catch (e) {
      showToast('Не удалось сохранить отчёт: ' + (e.message || e), 'error');
    }
  },

  renderProbe(st) {
    // История за окно наблюдения (сервер копит её снимками каждые 2с):
    // показываем итог по каждой цели, включая те, что так и не подключились
    const box = $('probeTbody');
    if (!box) return;
    const hist = st.history || {};
    const dns = st.dns || {};
    const dnsName = (ip) => (dns[ip] ? ` <span class="endpoint-dns">→ ${escapeHtml(dns[ip][0])}</span>` : '');
    const rowsData = Object.entries(hist).map(([k, h]) => {
      // Ключ истории - '<протокол> <ip:port>' (иначе один и тот же endpoint
      // по TCP и UDP схлопывался бы в одну строку, см. process_probe._hist_key).
      const endpoint = k.includes(' ') ? k.slice(k.indexOf(' ') + 1) : k;
      const idx = endpoint.lastIndexOf(':');
      const ip = endpoint.slice(0, idx), port = endpoint.slice(idx + 1);
      const states = h.states || {};
      let status, cls, metric, sev;
      if (h.proto === 'tcp') {
        if ('SynSent' in states && !('Established' in states)) { status = 'Нет ответа (SYN)'; cls = 'syn-sent'; sev = 0; }
        else if ('Established' in states) { status = 'Установлено'; cls = 'established'; sev = 2; }
        else if ('CloseWait' in states) { status = 'Сервер закрыл'; cls = 'neutral'; sev = 1; }
        else { status = h.state || '-'; cls = 'neutral'; sev = 1; }
        metric = `снимков ${h.snapshots || 0}`;
      } else {
        const s = h.sent || 0, r = h.recv || 0;
        if (s > 0 && r === 0) { status = 'Нет ответа (UDP)'; cls = 'syn-sent'; sev = 0; }
        else if (r > 0) { status = 'Диалог'; cls = 'established'; sev = 2; }
        else { status = 'UDP'; cls = 'neutral'; sev = 1; }
        metric = (s || r) ? `${s}→${r}` : `снимков ${h.snapshots || 0}`;
      }
      return { k, ip, port, status, cls, metric, sev, proto: h.proto };
    }).sort((a, b) => a.sev - b.sev || a.k.localeCompare(b.k));
    let rows = '';
    for (const r of rowsData) {
      rows += `<tr>
        <td><span class="proto-badge ${r.proto === 'udp' ? 'udp' : ''}">${r.proto === 'udp' ? 'UDP' : 'TCP'}</span></td>
        <td><span class="endpoint-ip">${escapeHtml(r.ip)}</span><span class="endpoint-dns">:${escapeHtml(r.port)}</span>${dnsName(r.ip)}</td>
        <td><span class="state-badge ${r.cls}"><span class="sdot"></span>${escapeHtml(r.status)}</span></td>
        <td style="text-align:center"><span class="packets-count">${escapeHtml(r.metric)}</span></td>
      </tr>`;
    }
    box.innerHTML = rows || '<tr><td colspan="4"><div class="empty-note">Наблюдение…</div></td></tr>';
    const sub = $('probeLiveSub');
    if (sub) {
      const cap = st.udp_capture || {};
      let txt = `Целей: ${rowsData.length}`;
      if (cap.sent || cap.recv) txt += ` · UDP-пакетов: ${cap.sent || 0}→${cap.recv || 0}`;
      sub.textContent = txt;
    }
    const vd = $('probeVerdict');
    if (vd) {
      if (st.verdict) {
        vd.hidden = false;
        vd.innerHTML = escapeHtml(st.verdict);
      } else {
        vd.hidden = true;
      }
    }
    // Домены: проблемные цели (кнопки «в обход») + все найденные за сессию
    const domBox = $('probeDomains');
    if (domBox) {
      if (!st.verdict || st.phase !== 'завершено') {
        domBox.hidden = true;
      } else {
        const problems = [];
        const seen = [];
        for (const [k, h] of Object.entries(hist)) {
          const states = h.states || {};
          const bad = (h.proto === 'tcp' && 'SynSent' in states && !('Established' in states))
            || (h.proto === 'udp' && (h.sent || 0) > 0 && (h.recv || 0) === 0);
          const endpoint = k.includes(' ') ? k.slice(k.indexOf(' ') + 1) : k;
          const ip = endpoint.slice(0, endpoint.lastIndexOf(':'));
          for (const d of (dns[ip] || [])) {
            if (!seen.includes(d)) seen.push(d);
            if (bad && !problems.includes(d)) problems.push(d);
          }
        }
        domBox.hidden = false;
        let html = '';
        if (problems.length) {
          const gctx = this._gameContext;
          html += '<div class="probe-domains-title">Домены проблемных целей - можно добавить в обход:</div>'
            + problems.map(d => `<div class="probe-domain-row">
                <span class="endpoint-ip">${escapeHtml(d)}</span>
                <button class="btn btn-sm" data-add-domain="${escapeHtml(d)}">В обход</button>
                ${gctx ? `<button class="btn btn-sm" data-add-to-game="${escapeHtml(d)}">В игру: ${escapeHtml(gctx.name)}</button>` : ''}
              </div>`).join('');
        } else if (seen.length) {
          html += '<div class="probe-domains-title">Проблемных доменов нет - все цели отвечали</div>';
        } else {
          html += '<div class="meta">Домены не найдены: приложение могло ходить по IP напрямую '
            + 'или через свой DNS (DoH). Ориентируйтесь на IP:порт - подойдут «Общий IP-обход» '
            + 'или добавление IP-сети.</div>';
        }
        if (seen.length) {
          html += `<div class="probe-domains-title">Домены за сеанс (${seen.length}): `
            + '<button class="btn btn-sm" id="probeDomsCopy">Скопировать</button></div>'
            + `<div class="probe-domain-row"><span class="meta">${seen.map(escapeHtml).join(' · ')}</span></div>`;
        }
        domBox.innerHTML = html;
        domBox.querySelectorAll('[data-add-domain]').forEach(b =>
          b.addEventListener('click', () => ListsPage.addDomainSuggestion(b)));
        domBox.querySelectorAll('[data-add-to-game]').forEach(b =>
          b.addEventListener('click', () => this.addToGame(b)));
        const cp = $('probeDomsCopy');
        if (cp) cp.addEventListener('click', async () => {
          const text = seen.join('\n');
          try {
            await navigator.clipboard.writeText(text);
            showToast('Домены скопированы', 'ok');
          } catch (e) {
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); showToast('Домены скопированы', 'ok'); }
            catch (e2) { showToast('Не удалось скопировать', 'warn'); }
            document.body.removeChild(ta);
          }
        });
      }
    }
  },

  // Добавить найденный в анализе домен прямо в игру (запущенную из её карточки)
  async addToGame(btn) {
    const ctx = this._gameContext;
    if (!ctx) return;
    const domain = btn.dataset.addToGame;
    btn.disabled = true;
    btn.textContent = 'Добавляю…';
    try {
      const r = await apiPost('/games/add-domain',
                              { game_id: ctx.id, domain });
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      showToast(r.message || 'Домен добавлен в игру', 'ok');
      btn.textContent = 'Добавлено';
    } catch (e) {
      showToast('Игра: ' + (e.message || e), 'error');
      btn.disabled = false;
      btn.textContent = 'В игру: ' + ctx.name;
    }
  },
};
