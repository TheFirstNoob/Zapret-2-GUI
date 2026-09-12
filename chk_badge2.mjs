import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9365;
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
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } };
const send = (method, params) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: APP });
await sleep(9000);
const res = await send('Runtime.evaluate', { expression: `(() => {
  try {
    const out = {};
    // 1. Бейдж на CDN (длинный пункт) — должен быть ПОД именем
    App.setTestActive(true);
    const badge = document.getElementById('testerBadge');
    const link = badge.parentElement;
    const linkRect = link.getBoundingClientRect();
    const badgeRect = badge.getBoundingClientRect();
    out.link = link.dataset.page;
    out.badge_below = badgeRect.top >= linkRect.bottom - 2;
    out.badge_inside = badgeRect.right <= linkRect.right + 1;
    out.link_w = Math.round(linkRect.width);
    out.badge_y = Math.round(badgeRect.top - linkRect.top);
    // 2. Кот в прогресс-барах
    const fill = document.getElementById('cdnProgressFill');
    const af = getComputedStyle(fill, '::after');
    out.cat_display = af.display;
    out.cat_bg = af.backgroundImage.slice(0, 60);
    out.cat_w = af.width;
    App.setTestActive(false);
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({ eval_error: e.message }); }
})()`, returnByValue: true });
console.log(res.result.value);
ws.close(); edge.kill();
await sleep(1000);
try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}