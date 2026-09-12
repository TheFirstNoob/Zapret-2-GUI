import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9363;
const APP = 'http://127.0.0.1:18888/?token=dump';
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
  else if (m.method === 'Runtime.exceptionThrown') {
    errors.push('EXC: ' + (m.params.exceptionDetails?.text || '') + ' ' + (m.params.exceptionDetails?.exception?.description || '').slice(0, 200));
  } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    errors.push('CONSOLE: ' + m.params.args.map(a => a.value || a.description || '').join(' ').slice(0, 200));
  }
};
const send = (method, params) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('Page.enable');
await send('Runtime.enable');
await send('Page.navigate', { url: APP });
await sleep(9000);
const res = await send('Runtime.evaluate', { expression: `(async () => {
  const out = {};
  out.title = document.title;
  out.pageActive = document.querySelector('.page.active')?.id;
  // click nav to lists
  const link = document.querySelector('[data-page="lists"]');
  link.click();
  await new Promise(r2 => setTimeout(r2, 300)); out.afterClick = document.querySelector('.page.active')?.id;
  out.navActive = document.querySelector('.nav-link.active')?.dataset.page;
  return JSON.stringify(out);
})()`, returnByValue: true, awaitPromise: true });
console.log(res.result.value);
await sleep(1500);
console.log('ERRORS:', JSON.stringify(errors.slice(0, 8)));
ws.close(); edge.kill();
await sleep(1000);
try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}
