import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9360;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-chk-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--remote-debugging-port=' + PORT, '--user-data-dir=' + profileDir, '--window-size=1280,840', 'about:blank'], { stdio: 'ignore' });

for (let i = 0; i < 60; i++) {
  try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); if (r.ok) break; } catch {}
  await sleep(250);
}
const r = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent('http://127.0.0.1:18888/?token=dump')}`, { method: 'PUT' });
const tab = await r.json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise(res => ws.onopen = res);
let id = 0; const pend = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } };
const send = (method, params) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:18888/?token=dump' });
await sleep(9000);

const res = await send('Runtime.evaluate', { expression: `(async () => {
  try {
    const out = {};
    // 1. BlobSelect
    const trigger = document.getElementById('fakeBlobBtn');
    const select = document.getElementById('fakeBlobSelect');
    out.dropdown_trigger_w = Math.round(trigger.getBoundingClientRect().width);
    out.select_hidden = select.hidden;
    trigger.click();
    const menu = document.getElementById('fakeBlobMenu');
    out.menu_open = !menu.hidden;
    out.menu_items = menu.querySelectorAll('.dropdown-item').length;
    out.menu_w = Math.round(menu.getBoundingClientRect().width);
    menu.querySelector('.dropdown-item').click();
    out.menu_closed = menu.hidden;
    // 2. Р‘РµР№РґР¶
    App.setTestActive(true);
    out.badge_page = document.getElementById('testerBadge').parentElement.dataset.page;
    App.setTestActive(false);
    // 3. РџРёР»СЋР»СЏ z2 + PID
    out.pill = document.getElementById('z2State').textContent.trim();
    // 4. Р”РёР°РіРЅРѕСЃС‚РёРєР° render
    DiagnosticsPage.render({
      summary: { ok: 10, fail: 5, warn: 1 }, elapsed_sec: 39, report_text: 'x',
      checks: [{ name: 'РџСЂР°РІР° Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°', detail: 'РµСЃС‚СЊ', status: 'ok' },
               { name: 'РљР°РЅР°СЂРµР№РєР°', detail: 'РЅРµ РѕС‚РІРµС‡Р°РµС‚', status: 'fail' }]
    });
    out.diag_badges = document.querySelectorAll('#diagSummary .badge').length;
    out.diag_rows = document.querySelectorAll('.diag-row').length;
    out.diag_rec = !document.getElementById('diagRecommend').hidden;
    // 5. РЎРїРёСЃРєРё
    location.hash = 'lists';
    await new Promise(res2 => setTimeout(res2, 1500));
    const ta = document.getElementById('domIncTextarea');
    ta.value = 'amazonaws.com\\nРІ\\nmore';
    ListsPage.validate('domInc');
    out.lists_err_status = document.getElementById('domIncValid').textContent.trim();
    out.lists_bad_line = !!document.querySelector('#domIncNums .bad-line');
    out.lists_btn_disabled = document.querySelector('[data-save="domInc"]').disabled;
    ta.value = 'amazonaws.com\\nnewdomain.ru';
    ListsPage.validate('domInc');
    out.lists_dirty = document.getElementById('domIncValid').className;
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({ eval_error: e.message }); }
})()`, returnByValue: true, awaitPromise: true });
console.log(res.result.value);
ws.close(); edge.kill();
await sleep(1000);
try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}
