import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9362;
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
    // подождать автоскан (заполнит _probeProcesses)
    // имитируем данные скана вручную (сеть может быть разной)
    TesterPage._probeProcesses = [
      { name: 'Discord', pid: 11932, title: '' },
      { name: 'DiscordPTB', pid: 2101, title: '' },
      { name: 'msedge', pid: 21720, title: 'Microsoft Edge' },
      { name: 'WardogsClient', pid: 3333, title: '' },
    ];
    const input = document.getElementById('probeProcInput');
    const box = document.getElementById('probeProcHint');
    const set = v => { input.value = v; TesterPage._hintProbeProcess(); return box.textContent.trim().slice(0, 90); };
    out.exact = set('discord');
    out.pid_ok = set('3333');
    out.pid_miss = set('99999');
    out.fuzzy = set('disc');
    out.miss = set('nope.exe');
    out.empty = set('');
    out.hidden_when_empty = box.hidden;
    out.sugg_click = (() => {
      set('disc');
      const sugg = box.querySelector('.pp-sugg');
      if (!sugg) return 'no sugg';
      sugg.click();
      return input.value;
    })();
    out.hint_visible = !box.hidden;
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({ eval_error: e.message }); }
})()`, returnByValue: true });
console.log(res.result.value);
ws.close(); edge.kill();
await sleep(1000);
try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}