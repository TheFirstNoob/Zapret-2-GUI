const AsnPage = {
  _polling: false,
  _bound: false,

  init() {
    if (this._bound) return;
    this._bound = true;
    $('asnScanBtn').addEventListener('click', () => this.scan());
    App.bindHelpToggle('asnHelpBtn', 'asnHelpDetails');
  },

  async scan() {
    if (this._polling || App.testActive) return;
    this._polling = true;
    App.setTestActive(true);
    $('asnScanBtn').disabled = true;
    $('asnIdle').hidden = true;
    $('asnResults').hidden = true;
    $('asnScanning').hidden = false;
    $('asnProgressTitle').textContent = 'Подготовка…';
    $('asnProgressPct').textContent = '0%';
    $('asnProgressFill').style.width = '0%';
    try {
      const r = await apiPost('/asn-scan', {});
      if (r.status !== 'ok') throw new Error(r.message || 'ошибка');
      const deadline = Date.now() + 10 * 60 * 1000;
      let final = null;
      while (!final && Date.now() < deadline) {
        await new Promise(res => setTimeout(res, 700));
        const st = await apiGet('/tester/status');
        if (st.error && !st.running) throw new Error(st.error);
        if (st.progress) {
          $('asnProgressTitle').textContent = st.progress.message || 'Сканирование…';
          const pct = st.progress.percent ?? 0;
          Activity.set('asn', st.progress.message || 'ASN-скан', pct, true);
          $('asnProgressPct').textContent = Math.round(pct) + '%';
          $('asnProgressFill').style.width = Math.min(100, Math.max(0, pct)) + '%';
          $('asnProgressFill').setAttribute('aria-valuenow', Math.min(100, Math.max(0, pct)));
        }
        if (!st.running) final = st.final_result;
      }
      if (!final) throw new Error('скан не завершился вовремя');
      if (final.type === 'asn_scan') {
        this._render(final.probes || [], final.restored || '');
        Activity.done('ASN-скан завершён');
      } else throw new Error('неожиданный результат');
    } catch (e) {
      Activity.fail('ASN-скан: ' + e.message);
      $('asnScanning').hidden = true;
      $('asnResults').hidden = false;
      $('asnResults').innerHTML = `<div class="empty-note st-err">${escapeHtml(e.message)}</div>`;
      showToast('ASN-скан: ' + e.message, 'error');
    }
    this._polling = false;
    App.setTestActive(false);
    $('asnScanBtn').disabled = false;
    $('asnScanning').hidden = true;
  },

  _render(probes, restored) {
    const okN = probes.filter(x => x.status === 'OK').length;
    const detN = probes.filter(x => x.status === 'DETECTED').length;
    const synN = probes.filter(x => x.status === 'SYN DROP').length;
    const rsts = probes.filter(x => x.status === 'TCP RST' || x.status === 'TLS RST').length;
    const errN = probes.length - okN - detN - synN - rsts;

    const metrics = `
      <span class="m-badge neutral">Проб: ${probes.length}</span>
      <span class="m-badge success">✓ Чисто: ${okN}</span>
      <span class="m-badge danger">✕ DETECTED: ${detN}</span>
      <span class="m-badge warning">● SYN DROP: ${synN}</span>
      ${rsts ? `<span class="m-badge warning">RST: ${rsts}</span>` : ''}
      ${errN ? `<span class="m-badge neutral">Прочие: ${errN}</span>` : ''}
      ${restored ? `<span class="metrics-mode">защита восстановлена: ${escapeHtml(restored)}</span>` : ''}`;

    const badgeCls = s => s === 'OK' ? 'clean' : (s === 'DETECTED' ? 'fatal' : (s === 'SYN DROP' ? 'action' : 'neutral'));
    const rows = probes.map(x => `
      <tr>
        <td class="host-name">${escapeHtml(x.id)}</td>
        <td class="mono">${escapeHtml(x.asn)}</td>
        <td>${escapeHtml(x.provider)}</td>
        <td><span class="verdict-badge ${badgeCls(x.status)}">${escapeHtml(x.status)}</span></td>
        <td class="meta">${escapeHtml(x.detail || '')}</td>
      </tr>`).join('');

    let guide = 'Если большинство проб <b>OK</b> и сайты работают - <b>ничего делать не нужно</b>: 100% «OK» не требуется, с моими пресетами доступно ~99% сайтов.';
    if (detN > 0) guide += ` «DETECTED» (${detN}) - stateful DPI режет CDN-класс: лечится кнопками на вкладке «CDN-стабилизация».`;
    if (synN > 0) guide += ` «SYN DROP» (${synN}) - диапазоны режутся целиком или IP списка протухли; десинк против этого не поможет.`;
    guide += ' Мобильная сеть меняет картину от часа к часу: перед выводами прогоните скан повторно с паузой.';

    $('asnResults').innerHTML = `
      <div class="metrics-bar">${metrics}</div>
      <div class="hosts-table-wrap"><table class="hosts-table">
        <thead><tr>
          <th style="width:200px">ID</th>
          <th style="width:120px">ASN</th>
          <th>Провайдер</th>
          <th style="width:130px">Статус</th>
          <th>Детали</th>
        </tr></thead>
        <tbody>${rows || '<tr><td colspan="5"><div class="empty-note">Нет данных</div></td></tr>'}</tbody>
      </table></div>
      <div class="cdn-guide">${guide}</div>`;
    $('asnResults').hidden = false;
  },
};
