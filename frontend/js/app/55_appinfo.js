// ── О программе: обновления и техническая информация (подвал меню) ──
const AppInfo = {
  _wired: false,

  async open() {
    try {
      const r = await apiGet('/app-info');
      const i = r.info || {};
      const buildLabel = i.build === 'exe' ? 'EXE (onefile)'
        : i.build === 'portable' ? 'portable (Python)'
        : i.build === 'source' ? 'из исходников (Python)'
        : (i.frozen ? 'EXE (onefile)' : 'portable (Python)');
      const rows = [
        `Версия: <b>${escapeHtml(i.version || '?')}</b>`,
        `Сборка: ${buildLabel}`,
        `Папка: <span class="meta">${escapeHtml(i.path || '')}</span>`,
      ];
      if (i.exe_sha256) {
        rows.push(`SHA256 exe: <span class="meta">${escapeHtml(i.exe_sha256)}</span>`);
      }
      if (i.update_key) {
        rows.push(`Ключ подписи обновлений: <b>${escapeHtml(i.update_key)}</b>`);
      }
      $('appInfoBody').innerHTML = rows.join('<br>');
      $('appInfoStatus').textContent = '';
      Modal.open('appInfoOverlay');
      this._wire();
    } catch (e) {
      showToast('Не удалось получить сведения: ' + (e.message || e), 'error');
    }
  },

  close() { Modal.close('appInfoOverlay'); },

  _wire() {
    if (this._wired) return;
    this._wired = true;
    $('appInfoClose').addEventListener('click', () => this.close());
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && $('appInfoOverlay').classList.contains('open')) this.close();
    });
    $('appInfoOverlay').addEventListener('click', (ev) => {
      if (ev.target.id === 'appInfoOverlay') this.close();
    });
    $('appInfoCheck').addEventListener('click', async () => {
      const st = $('appInfoStatus');
      st.textContent = 'Проверяю…';
      try {
        const r = await apiGet('/update-check?force=1');
        if (r.error) throw new Error(r.error);
        if (r.available) {
          st.innerHTML = `Доступна версия <b>${escapeHtml(r.latest || '')}</b> - смотрите баннер вверху страницы.`;
          $('updateVersion').textContent = r.latest || '';
          $('updateLink').href = r.url || '#';
          $('updateMirrorLink').href = r.mirror_url || '#';
          App._updateTag = r.tag || '';
          $('updateBanner').hidden = false;
        } else {
          st.textContent = `Установлена последняя версия (${r.current || ''})`;
        }
      } catch (e) {
        st.textContent = 'Ошибка проверки: ' + (e.message || e);
      }
    });
  },
};
