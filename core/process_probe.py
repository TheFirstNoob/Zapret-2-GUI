"""process_probe.py — анализ сетевых соединений процесса (игры/приложения).

Собирает для выбранного процесса: TCP endpoints (Get-NetTCPConnection),
UDP connected (Get-NetUDPEndpoint), UDP-захват через pktmon (pkt-size 64 —
только заголовки, без раздувания логов), DNS-маппинг (Get-DnsClientCache).
Агрегация уникальных IP:port + state + частота. Вердикт по паттернам
(STRATEGY_TRIALS 2026-09-11: SynSent = возможный IP-блок, десинк бессилен).
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import core.utils as utils

# RemoteSigned (а не Bypass): скрипты — read-only Get-* cmdlets, политика их не
# трогает, а флаг Bypass — классический эвристический паттерн для AV/EDR.
# Проверено 2026-09-12: вывод идентичен Bypass на всех вызовах _ps/_ps_json.
PS_BASE = ["powershell", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-Command"]

_PRIVATE_RE = re.compile(
    r"^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|127\.|0\.|169\.254\.|224\.|239\.|255\.)")


def _ps(script: str) -> str:
    r = subprocess.run(PS_BASE + [script], capture_output=True, text=True,
                       encoding="oem", errors="replace", timeout=25,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    return (r.stdout or "").strip()


def _ps_json(script: str) -> list:
    out = _ps(script)
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]


def _non_empty(ra: str) -> bool:
    return bool(ra and ra not in ("0.0.0.0", "::", "::1", "127.0.0.1"))


def list_processes() -> list[dict]:
    """Процессы с активными сетевыми соединениями: [{name, pid}]."""
    script = (
        "$c = Get-NetTCPConnection -ErrorAction SilentlyContinue | "
        "Where-Object { $_.RemoteAddress -and $_.RemoteAddress -ne '0.0.0.0' "
        "-and $_.RemoteAddress -ne '::' } | ForEach-Object { $_.OwningProcess }; "
        "$u = Get-NetUDPEndpoint -ErrorAction SilentlyContinue | "
        "Where-Object { $_.RemoteAddress -and $_.RemoteAddress -ne '0.0.0.0' "
        "-and $_.RemoteAddress -ne '::' } | ForEach-Object { $_.OwningProcess }; "
        "$pids = @($c + $u) | Sort-Object -Unique; "
        "if (-not $pids) { '[]'; exit }; "
        "Get-Process -Id $pids -ErrorAction SilentlyContinue | "
        "Select-Object ProcessName,Id,MainWindowTitle | Sort-Object ProcessName | "
        "ConvertTo-Json -Compress"
    )
    out: list[dict] = []
    for item in _ps_json(script):
        name = str(item.get("ProcessName") or "").strip()
        pid = item.get("Id")
        title = str(item.get("MainWindowTitle") or "").strip()
        if name and pid is not None:
            out.append({"name": name, "pid": int(pid), "title": title})
    # дедуп по (name,pid)
    seen = set()
    uniq = []
    for p in out:
        k = (p["name"], p["pid"])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def _tcp_snapshot(pids: list[int]) -> dict:
    ps = ",".join(str(p) for p in pids)
    script = (
        f"$pids = @({ps}); "
        "Get-NetTCPConnection -ErrorAction SilentlyContinue | "
        "Where-Object { $pids -contains $_.OwningProcess } | "
        "Select-Object @{n='ra';e={[string]$_.RemoteAddress}},"
        "@{n='rp';e={$_.RemotePort}},@{n='st';e={[string]$_.State}} | "
        "ConvertTo-Json -Compress"
    )
    tcp: dict[str, dict] = {}
    for item in _ps_json(script):
        ra = str(item.get("ra") or "")
        if not _non_empty(ra):
            continue
        port = item.get("rp")
        state = str(item.get("st") or "?")
        key = f"{ra}:{port}"
        tcp[key] = {"state": state, "n": tcp.get(key, {}).get("n", 0) + 1}
    return tcp


def _udp_snapshot(pids: list[int]) -> dict:
    ps = ",".join(str(p) for p in pids)
    script = (
        f"$pids = @({ps}); "
        "Get-NetUDPEndpoint -ErrorAction SilentlyContinue | "
        "Where-Object { $pids -contains $_.OwningProcess } | "
        "Select-Object RemoteAddress,RemotePort | "
        "ConvertTo-Json -Compress"
    )
    udp: dict[str, int] = {}
    for item in _ps_json(script):
        ra = str(item.get("RemoteAddress") or "")
        if not _non_empty(ra):
            continue
        key = f"{ra}:{item.get('RemotePort')}"
        udp[key] = udp.get(key, 0) + 1
    return udp


def _udp_ports(pids: list[int]) -> list[int]:
    ps = ",".join(str(p) for p in pids)
    script = (
        f"$pids = @({ps}); "
        "Get-NetUDPEndpoint -ErrorAction SilentlyContinue | "
        "Where-Object { $pids -contains $_.OwningProcess } | "
        "Select-Object -ExpandProperty LocalPort | Sort-Object -Unique"
    )
    ports: list[int] = []
    for line in _ps(script).splitlines():
        line = line.strip()
        if line.isdigit():
            ports.append(int(line))
    return ports


def _dns_map(remote_ips: set[str]) -> dict[str, list[str]]:
    script = (
        "Get-DnsClientCache -ErrorAction SilentlyContinue | "
        "Select-Object Entry,Data | ConvertTo-Json -Compress"
    )
    cache: dict[str, list[str]] = {}
    for item in _ps_json(script):
        data = str(item.get("Data") or "")
        entry = str(item.get("Entry") or "")
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", data) and data in remote_ips:
            cache.setdefault(data, [])
            if entry not in cache[data]:
                cache[data].append(entry)
    return cache


def _run_pktmon(pids: list[int], etl: Path, txt: Path) -> Optional[dict]:
    """UDP-захват через pktmon (headers only). Возвращает {ip:port: count}.

    Без известных UDP-портов процесса захват НЕ запускается: pktmon не умеет
    фильтровать по PID, и без фильтра ловится весь UDP-трафик машины
    (браузер, Discord и т.д.) — шум и раздутый ETL."""
    utils.run_quiet(["pktmon", "stop"])
    utils.run_quiet(["pktmon", "filter", "remove"])
    if etl.exists():
        try:
            etl.unlink()
        except OSError:
            pass
    ports = _udp_ports(pids)
    if not ports:
        # нет связанных UDP-сокетов — фильтровать было бы нечем (ALL UDP =
        # мусор со всей машины); TCP-наблюдение snapshot'ами этого покрывает
        return None
    if ports:
        for p in ports:
            utils.run_quiet(["pktmon", "filter", "add", f"gp{p}", "-t", "UDP", "-p", str(p)])
    else:
        utils.run_quiet(["pktmon", "filter", "add", "gp", "-t", "UDP"])
    utils.run_quiet(["pktmon", "start", "--capture", "--pkt-size", "64",
                     "--file-name", str(etl)])
    if not etl.exists():
        utils.run_quiet(["pktmon", "filter", "remove"])
        return None
    return {"ports": ports, "etl": etl, "txt": txt}


def _finish_pktmon(handle: dict) -> dict:
    """Остановка захвата и парсинг remote IP:port + направления пакетов.

    Направление определяется по порту НАШЕГО сокета (source.port in ports
    = исходящий к серверу, destination.port in ports = входящий ответ) —
    это позволяет вердикту отличить «шлём, но не получаем» (UDP глушится)
    от нормального диалога."""
    etl = Path(handle["etl"])
    txt = Path(handle["txt"])
    ports = handle["ports"]
    utils.run_quiet(["pktmon", "stop"])
    utils.run_quiet(["pktmon", "etl2txt", str(etl), "-o", str(txt)])
    utils.run_quiet(["pktmon", "filter", "remove"])
    result: dict[str, int] = {}
    sent = 0
    recv = 0
    try:
        if txt.exists():
            for line in txt.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.search(
                    r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d+) > "
                    r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d+)", line)
                if not m:
                    continue
                a, ap, b, bp = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
                if ports and ap not in ports and bp not in ports:
                    continue
                for ip, port in ((a, ap), (b, bp)):
                    if not _PRIVATE_RE.match(ip):
                        key = f"{ip}:{port}"
                        result[key] = result.get(key, 0) + 1
                # у исходящих НАШ порт в источнике, у входящих — в приёмнике
                if ap in ports:
                    sent += 1
                elif bp in ports:
                    recv += 1
    finally:
        for f in (etl, txt):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
    return {"ips": result, "sent": sent, "recv": recv}


def _verdict(tcp: dict, udp: dict, udp_capture: dict, ipv6: bool, no_conn: bool,
             dns: Optional[dict] = None) -> str:
    if no_conn:
        return ("Нет соединений — включите анализ и воспроизведите проблему "
                "(зайдите в игру/попробуйте обновление) во время наблюдения.")
    dns = dns or {}
    parts = []
    if ipv6:
        parts.append("обнаружен IPv6 — обход работает только по IPv4")
    def _name(ip: str) -> str:
        doms = dns.get(ip)
        return f"{ip} ({', '.join(doms[:2])})" if doms else ip
    syn = [k for k, v in tcp.items() if v["state"] == "SynSent"]
    est = [k for k, v in tcp.items() if v["state"] == "Established"]
    if syn:
        hint = ("SynSent к " + ", ".join(_name(k.rsplit(":", 1)[0]) for k in syn[:3])
                + " — SYN не получает ответа (возможен IP-блок провайдера). "
                "Десинк SYN-дроп не лечит — попробуйте WARP.")
        if est:
            hint += " Часть соединений работает (Established)."
        parts.append(hint)
    elif est:
        parts.append("Соединения устанавливаются — сеть работает, проблема, "
                     "вероятно, на стороне приложения/сервиса.")
    if udp_capture:
        sent = udp_capture.get("sent", 0)
        recv = udp_capture.get("recv", 0)
        if sent and not recv:
            parts.append(f"UDP: отправлено {sent} пакетов, входящих 0 — UDP-трафик "
                         "к серверу глушится (ТСПУ). Десинк бессилен — WARP.")
        elif sent and recv:
            parts.append(f"UDP-диалог: отправлено {sent}, получено {recv}.")
    return " ".join(parts) if parts else "Соединения не обнаружены."


class ProcessProbe:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._state: dict = {}

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, process: str, duration: int = 60, wait_sec: int = 120) -> tuple[bool, str]:
        """Запуск анализа. process — имя процесса (маска) или числовой PID.
        Если процесс ещё не запущен — ждём появления до wait_sec секунд
        (захват «с нуля»: пользователь запускает игру после старта анализа)."""
        if self.running:
            return False, "Анализ уже запущен"
        if duration < 5:
            duration = 30
        self._thread = threading.Thread(
            target=self._run, args=(process, duration, wait_sec), daemon=True)
        self._stop_flag.clear()
        with self._lock:
            self._state = {"process": process, "elapsed": 0,
                           "duration": duration, "tcp": {}, "udp": {},
                           "udp_capture": None, "dns": {}, "verdict": "",
                           "error": "", "phase": "старт"}
        self._thread.start()
        return True, "Анализ запущен"

    def _find_pids(self, spec: str) -> list[int]:
        """spec: имя-маска ('WardogsClient') или числовой PID."""
        if spec.strip().isdigit():
            return [int(spec.strip())]
        script = (f"Get-Process | Where-Object {{ $_.ProcessName -like '*{spec}*' }} "
                  "| Select-Object -ExpandProperty Id | ConvertTo-Json -Compress")
        data = _ps_json(script)
        return [int(p) for p in data]

    def _run(self, spec: str, duration: int, wait_sec: int) -> None:
        pids = self._find_pids(spec)
        waited = 0
        if not pids and wait_sec > 0:
            with self._lock:
                self._state.update({"phase": f"ожидание процесса '{spec}'... "
                                            f"(запустите игру)"})
            while not pids and waited < wait_sec and not self._stop_flag.is_set():
                time.sleep(3)
                waited += 3
                pids = self._find_pids(spec)
        if not pids:
            with self._lock:
                self._state.update({"error": f"Процесс '{spec}' не найден",
                                    "phase": "завершено"})
            return
        etl = Path(utils.get_temp_dir()) / "zapret2_probe.etl"
        txt = Path(utils.get_temp_dir()) / "zapret2_probe.txt"
        handle: Optional[dict] = None
        ipv6 = False
        start = time.time()
        try:
            handle = _run_pktmon(pids, etl, txt)
            while time.time() - start < duration and not self._stop_flag.is_set():
                tcp = _tcp_snapshot(pids)
                udp = _udp_snapshot(pids)
                if any(":" in k.split(":", 1)[0] for k in list(tcp) + list(udp)):
                    ipv6 = True
                elapsed = int(time.time() - start)
                with self._lock:
                    self._state.update({"tcp": tcp, "udp": udp, "elapsed": elapsed,
                                        "ipv6": ipv6, "phase": "наблюдение"})
                time.sleep(2)
            udp_capture = _finish_pktmon(handle) if handle else {}
            cap_ips = (udp_capture or {}).get("ips", {})
            remote_ips = {k.rsplit(":", 1)[0] for k in
                          list(self._state.get("tcp", {})) +
                          list(self._state.get("udp", {})) + list(cap_ips)}
            dns = _dns_map(remote_ips) if remote_ips else {}
            no_conn = not self._state.get("tcp") and not self._state.get("udp") \
                and not cap_ips
            verdict = _verdict(self._state.get("tcp", {}),
                               self._state.get("udp", {}), udp_capture,
                               self._state.get("ipv6", False), no_conn, dns)
            with self._lock:
                self._state.update({"udp_capture": cap_ips, "dns": dns,
                                    "verdict": verdict, "phase": "завершено",
                                    "elapsed": int(time.time() - start)})
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._state.update({"error": str(e), "phase": "завершено"})
        finally:
            utils.run_quiet(["pktmon", "stop"])
            utils.run_quiet(["pktmon", "filter", "remove"])

    def stop(self) -> dict:
        self._stop_flag.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=20)
        return self.get_status()

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def report_text(self) -> str:
        s = self.get_status()
        lines = [
            f"=== Анализ процесса: {s.get('process', '?')} ===",
            f"Фаза: {s.get('phase', '?')}  (прошло {s.get('elapsed', 0)} сек)",
            f"IPv6: {'ДА' if s.get('ipv6') else 'нет'}",
        ]
        if s.get("error"):
            lines.append(f"Ошибка: {s['error']}")
        lines.append("")
        lines.append("--- TCP ---")
        tcp = s.get("tcp", {})
        if not tcp:
            lines.append("(нет)")
        for k, v in sorted(tcp.items(), key=lambda kv: -kv[1]["n"]):
            mark = "  <-- SYN без ответа (возможен IP-блок)" if v["state"] == "SynSent" else ""
            lines.append(f"{k:<24} {v['state']:<12} x{v['n']}{mark}")
        lines.append("")
        lines.append("--- UDP (system) ---")
        udp = s.get("udp", {})
        if not udp:
            lines.append("(нет)")
        for k, v in sorted(udp.items(), key=lambda kv: -kv[1]):
            lines.append(f"{k:<24} x{v}")
        cap = s.get("udp_capture") or {}
        if cap:
            lines.append("")
            lines.append("--- UDP (из захвата pktmon) ---")
            for k, v in sorted(cap.items(), key=lambda kv: -kv[1]):
                lines.append(f"{k:<24} пакетов {v}")
        dns = s.get("dns", {})
        if dns:
            lines.append("")
            lines.append("--- Домены (DNS-кэш) ---")
            for ip, doms in dns.items():
                lines.append(f"{ip:<20} -> {', '.join(doms)}")
        lines.append("")
        lines.append("--- Вердикт ---")
        lines.append(s.get("verdict", ""))
        return "\n".join(lines)

    def save_report(self) -> Path:
        path = utils.get_temp_dir() / "zapret2_process_probe.txt"
        path.write_text(self.report_text(), encoding="utf-8")
        return path