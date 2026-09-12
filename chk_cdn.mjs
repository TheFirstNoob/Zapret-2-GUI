import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9364;
const APP = 'http://127.0.0.1:18888/?token=dump#cdn';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'edge-chk-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', '--remote-debugging-port=' + PORT, '--user-data-dir=' + profileDir, '--window-size=1280,840', 'about:blank'], { stdio: 'ignore' });

for (let i = 0; i < 60; i++) {
  try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); if (r.ok) break; } catch {}
  await sleep(250);
}
const r = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(APP)}`, { method: 'PUT' });
const tab = await r.json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise(res => ws.onopen = res);
let id = 0; const pend = new Map();
const errors = [];
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); }
  else if (m.method === 'Runtime.exceptionThrown') errors.push('EXC: ' + (m.params.exceptionDetails?.exception?.description || '').slice(0, 150));
};
const send = (method, params) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: APP });
await sleep(9000);

const res = await send('Runtime.evaluate', { expression: `(() => {
  try {
    const out = {};
    out.idle = !document.getElementById('cdnIdle').hidden;
    out.scanning_hidden = document.getElementById('cdnScanning').hidden;
    out.results_hidden = document.getElementById('cdnResults').hidden;
    // help toggle
    document.getElementById('cdnHelpBtn').click();
    out.help_open = !document.getElementById('cdnHelpDetails').hidden;
    out.help_items = document.querySelectorAll('#cdnHelpDetails .help-item').length;
    out.help_legend = document.querySelectorAll('#cdnHelpDetails .lh-row').length;
    // render fake results
    CdnStab._render({
      ipset_mode: false,
      verdicts: [
        { domain: 'cdn.eso.org', provider: 'CDN77', alive: 'A', dpi: 'DET', naked: 'B', verdict: 'fix', ipset: 'чинит', ips: ['1.2.3.4'] },
        { domain: 'status.moow.info', provider: 'Contabo', alive: 'B', dpi: 'DET', naked: 'A', verdict: 'hard', ipset: 'ломает', ips: ['5.6.7.8'] },
        { domain: 'justice.gov', provider: 'Cloudflare', alive: 'A', dpi: 'ok', naked: 'A', verdict: 'ok', ipset: '', ips: [] },
        { domain: 'img.wzstats.gg', provider: 'Cloudflare', alive: 'B', dpi: '—', naked: 'B', verdict: 'dead', ipset: '', ips: [] },
      ],
    });
    out.results_visible = !document.getElementById('cdnResults').hidden;
    out.banner = !!document.querySelector('.rec-banner');
    out.rec_title = document.querySelector('.rec-title')?.textContent;
    out.metrics = document.querySelectorAll('.metrics-bar .m-badge').length;
    out.rows = document.querySelectorAll('.hosts-table tbody tr').length;
    out.badges = Array.from(document.querySelectorAll('.verdict-badge')).map(b => b.textContent.trim());
    out.actions = document.querySelectorAll('[data-cdn-act]').length;
    out.apply_all = !!document.getElementById('cdnApplyAll');
    out.guide = !!document.querySelector('.cdn-guide');
    // asn render
    AsnPage._render([
      { id: 'R1', asn: 'AS24940', provider: 'Hetzner', status: 'OK', detail: '32KB ok' },
      { id: 'R2', asn: 'AS14061', provider: 'DigitalOcean', status: 'DETECTED', detail: 'cut at 16KB' },
      { id: 'R3', asn: 'AS16276', provider: 'OVH', status: 'SYN DROP', detail: '' },
    ], 'служба запущена');
    out.asn_rows = document.querySelectorAll('#asnResults .hosts-table tbody tr').length;
    out.asn_metrics = document.querySelectorAll('#asnResults .m-badge').length;
    out.asn_restored = document.querySelector('#asnResults .metrics-mode')?.textContent || '';
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({ eval_error: e.message }); }
})()`, returnByValue: true });
console.log(res.result.value);
console.log('ERRORS:', JSON.stringify(errors.slice(0, 5)));
ws.close(); edge.kill();
await sleep(1000);
try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}