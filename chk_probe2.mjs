import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9361;
const APP = 'http://127.0.0.1:18888/?token=dump#probe';
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
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } };
const send = (method, params) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: APP });
await sleep(9000);
const res = await send('Runtime.evaluate', { expression: `(() => {
  try {
    const out = {};
    out.idle_visible = !document.getElementById('probeIdle').hidden;
    out.badge_text = document.getElementById('probeState').textContent.trim();
    out.probe_grids = document.querySelectorAll('.probe-grid').length;
    // simulate live state
    TesterPage.renderProbe({
      tcp: { '151.101.66.132:443': { state: 'Established', n: 14 },
             '142.250.186.206:443': { state: 'SynSent', n: 3 },
             '1.2.3.4:443': { state: 'TimeWait', n: 2 } },
      udp: { '162.159.130.233:50001': 42 },
      udp_capture: { '10.0.0.5:50000': 7 },
      dns: { '151.101.66.132': ['discord.com'], '162.159.130.233': ['openai.com'] },
      verdict: 'Соединения к discord.com установлены; SYN_SENT — возможная блокировка IP.'
    });
    out.live_rows = document.querySelectorAll('#probeTbody tr').length;
    out.rows_hidden = document.getElementById('probeLive').hidden;
    out.first_row = document.querySelector('#probeTbody tr').textContent.trim().slice(0, 80);
    out.sub = document.getElementById('probeLiveSub').textContent;
    out.verdict = !document.getElementById('probeVerdict').hidden;
    // badge state
    TesterPage._setProbeState('● Перехват пакетов', 'live');
    out.badge_live = document.getElementById('probeState').textContent.trim();
    out.badge_cls = document.getElementById('probeState').className;
    TesterPage._setProbeState('✓ Анализ завершён', 'done');
    out.badge_done = document.getElementById('probeState').textContent.trim();
    // scan count on button (fake scan response)
    document.getElementById('probeScanBtn').textContent = '🔄 42';
    out.scan_btn = document.getElementById('probeScanBtn').textContent;
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({ eval_error: e.message }); }
})()`, returnByValue: true });
console.log(res.result.value);
ws.close(); edge.kill();
await sleep(1000);
try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}