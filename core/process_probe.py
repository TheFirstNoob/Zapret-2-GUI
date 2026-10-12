"""process_probe.py - анализ сетевых соединений процесса (игры/приложения).

Собирает для выбранного процесса: TCP endpoints (Get-NetTCPConnection),
UDP connected (Get-NetUDPEndpoint), UDP-захват через pktmon (pkt-size 64 -
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
from core.applog import log as _applog

# RemoteSigned (а не Bypass): скрипты - read-only Get-* cmdlets, политика их
# не трогает, а Bypass - классический эвристический паттерн для AV/EDR.
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


def _dns_cache_entries() -> dict[str, list[str]]:
    """Сырой DNS-кэш Windows: {ip: [имена]} (A и AAAA, без фильтрации).

    Вызывается периодически во время захвата: записи с коротким TTL иначе
    протухают к концу сессии, и домены проблемных целей остаются не найдены.
    """
    script = (
        "Get-DnsClientCache -ErrorAction SilentlyContinue | "
        "Select-Object Entry,Data | ConvertTo-Json -Compress"
    )
    cache: dict[str, list[str]] = {}
    ip4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
    for item in _ps_json(script):
        data = str(item.get("Data") or "").strip()
        entry = str(item.get("Entry") or "").strip()
        if not entry or not data:
            continue
        if not (ip4.match(data) or ":" in data):
            continue
        cache.setdefault(data, [])
        if entry not in cache[data]:
            cache[data].append(entry)
    return cache


def _run_pktmon(pids: list[int], etl: Path, txt: Path) -> Optional[dict]:
    """UDP-захват через pktmon (только заголовки). Возвращает {ip:port: count}.

    Без известных UDP-портов процесса захват НЕ запускается: pktmon не фильтрует
    по PID, и без фильтра ловится весь UDP машины (браузер, Discord) - шум и
    раздутый ETL."""
    utils.run_quiet(["pktmon", "stop"])
    utils.run_quiet(["pktmon", "filter", "remove"])
    if etl.exists():
        try:
            etl.unlink()
        except OSError:
            pass
    ports = _udp_ports(pids)
    if not ports:
        # нет связанных UDP-сокетов - фильтровать было бы нечем (ALL UDP =
        # мусор со всей машины); TCP-наблюдение snapshot'ами этого покрывает
        return None
    if ports:
        for p in ports:
            utils.run_quiet(["pktmon", "filter", "add", f"gp{p}", "-t", "UDP", "-p", str(p)])
    else:
        utils.run_quiet(["pktmon", "filter", "add", "gp", "-t", "UDP"])
    utils.run_quiet(["pktmon", "start", "--capture", "--pkt-size", "64",
                     "--file-name", str(etl)])
    # ETL создаёт служба pktmon, и на загруженной машине файл появляется не
    # мгновенно после возврата start. Проверка «exists сразу» отдавала None,
    # и UDP-захват отключался на всю сессию молча. Ждём короткий срок.
    if not _wait_for_file(etl, timeout=3.0):
        utils.run_quiet(["pktmon", "filter", "remove"])
        return None
    return {"ports": ports, "etl": etl, "txt": txt}


def _wait_for_file(path: Path, timeout: float = 3.0,
                   step: float = 0.15) -> bool:
    """True, если файл появился за отведённое время. Не грузит CPU."""
    deadline = time.time() + timeout
    while True:
        try:
            if path.exists():
                return True
        except OSError:
            return False
        if time.time() >= deadline:
            return False
        time.sleep(step)


def _read_pktmon_txt(txt: Path) -> str:
    """pktmon etl2txt пишет UTF-16 (иногда UTF-8) - читаем оба варианта."""
    raw = txt.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-16", errors="replace")


_PRIVATE_V6 = ("::", "::1", "fe80:", "fc", "fd", "ff")


def _is_private(addr: str) -> bool:
    """Свой/служебный адрес - в «удалённые цели» он не попадает.

    IPv4 - по прежнему префиксному регулярному выражению (100.64/10 и прочие
    «особые» блоки там намеренно не отсекаются). IPv6 добавлен отдельно:
    unspecified, loopback, link-local fe80::/10, ULA fc00::/7, ff00::/8.
    """
    a = addr.strip().strip("[]").lower()
    if ":" in a:
        return any(a == p or a.startswith(p) for p in _PRIVATE_V6)
    return bool(_PRIVATE_RE.match(a))


# Конец строки etl2txt: адрес и порт. pktmon печатает IPv4 как "a.b.c.d.port",
# IPv6 - как "[2001:db8::1]:port" либо "2001:db8::1.port"; адрес отделён от
# порта точкой или двоеточием с ПОСЛЕДНИМ числовым сегментом.
_EP_RE = re.compile(r"([\[\]0-9a-fA-F:.]+?)[.:](\d{1,5})\s*$")


def _split_endpoint(chunk: str) -> tuple[Optional[str], int]:
    """'a.b.c.d.443' / '[2001:db8::1]:443' -> (ip, port). (None, 0), если не
    разобрали - важно, чтобы в счётчики не попал мусор из заголовков etl2txt."""
    import ipaddress
    m = _EP_RE.search(chunk.strip())
    if not m:
        return None, 0
    addr = m.group(1).strip("[]")
    port = int(m.group(2))
    if not 0 < port <= 65535:
        return None, 0
    try:
        ipaddress.ip_address(addr)
    except ValueError:
        return None, 0
    return addr, port


def _parse_pktmon_txt(txt: Path, ports: list[int]) -> dict:
    """Разбор etl2txt: {ips: {remote: {sent, recv}}, sent, recv}.

    Направление - по НАШЕМУ порту сокета (source.port in ports = исходящий к
    серверу, destination.port in ports = входящий ответ) - это позволяет
    вердикту отличить «шлём, но не получаем» (UDP глушится) от диалога.

    Адреса берутся в обеих версиях: прежняя регулярка понимала только IPv4,
    хотя флаг ipv6 ставится по снимкам сокетов - для процесса, который говорит
    только по IPv6, «UDP-захват» выходил пустым и вердикт молчал."""
    ips: dict[str, dict[str, int]] = {}
    sent = 0
    recv = 0
    if not txt.exists():
        return {"ips": ips, "sent": sent, "recv": recv}
    # Пара endpoint'ов ищем регуляркой с якорем ": UDP": на Wi-Fi каждая
    # строка etl2txt начинается с MAC-пары "B4-... > 26-..." - старый
    # partition(">") рвал строку по MAC-разделителю, и ВСЕ UDP-пакеты
    # отбрасывались (sent/recv всегда 0 при живом захвате; аудит 2026-10-10).
    pair_re = re.compile(r"(\S+)\s*>\s*(\S+):\s*UDP")
    for line in _read_pktmon_txt(txt).splitlines():
        if ": UDP" not in line:
            continue
        m = pair_re.search(line)
        if not m:
            continue
        a, ap = _split_endpoint(m.group(1))
        b, bp = _split_endpoint(m.group(2))
        if a is None or b is None:
            continue
        if ports and ap not in ports and bp not in ports:
            continue
        if ap in ports and not _is_private(b):
            ips.setdefault(f"{b}:{bp}", {"sent": 0, "recv": 0})["sent"] += 1
            sent += 1
        elif bp in ports and not _is_private(a):
            ips.setdefault(f"{a}:{ap}", {"sent": 0, "recv": 0})["recv"] += 1
            recv += 1
    return {"ips": ips, "sent": sent, "recv": recv}


def _etl2txt(etl: Path, txt: Path, timeout: int = 120) -> tuple[bool, str]:
    """pktmon etl2txt с явным таймаутом и проверкой результата.

    run_quiet глотает всё, включая таймаут, поэтому обрыв не был виден: если
    etl2txt убивали на дефолтных 30 с, txt оставался частичным, recv считался
    заниженным, и вердикт объявлял «UDP глушится, нужен WARP» там, где данные
    просто не успели разобрать. Возвращаем (полнота разбора, причина).
    """
    try:
        r = subprocess.run(["pktmon", "etl2txt", str(etl), "-o", str(txt)],
                           capture_output=True, text=True, encoding="oem",
                           errors="replace", timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, f"etl2txt не уложился в {timeout} с"
    except OSError as e:
        return False, f"etl2txt не запустился: {e!r}"
    if r.returncode != 0:
        return False, f"etl2txt rc={r.returncode}: {(r.stdout or r.stderr or '').strip()[:160]}"
    if not txt.exists():
        return False, "etl2txt не создал txt"
    return True, ""


def _finish_pktmon(handle: dict) -> dict:
    """Остановка захвата и разбор (UTF-16/UTF-8) remote IP:port + направлений."""
    etl = Path(handle["etl"])
    txt = Path(handle["txt"])
    ports = handle["ports"]
    utils.run_quiet(["pktmon", "stop"])
    complete, why = _etl2txt(etl, txt)
    utils.run_quiet(["pktmon", "filter", "remove"])
    try:
        if not complete:
            # Неполный разбор хуже отсутствия разбора: по обрезанному файлу
            # «входящих нет» выглядит как блокировка. Лучше честно «данных нет».
            _applog("probe", f"UDP-захват не разобран: {why}")
            return {"ips": {}, "sent": 0, "recv": 0,
                    "incomplete": True, "reason": why}
        return _parse_pktmon_txt(txt, ports)
    finally:
        for f in (etl, txt):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass


def _hist_key(proto: str, endpoint: str) -> str:
    """Ключ истории наблюдения. Протокол входит в ключ.

    Один и тот же endpoint (ip:port) вполне может наблюдаться и по TCP, и по
    UDP - например QUIC 443 и TCP 443 на один CDN-IP. Раньше запись
    заводилась по одному ключу, и вторая ветка подмешивалась в первую:
    states получали одновременно SynSent и "UDP", а поле proto оставалось от
    первого увиденного. Из-за этого «UDP без ответа» не попадал в вердикт
    (ветка tcp), а состояния TCP терялись, если первым увидели UDP.
    """
    return f"{proto} {endpoint}"


def _hist_endpoint(key: str) -> str:
    """'tcp 1.2.3.4:443' -> '1.2.3.4:443' - для показа и извлечения IP."""
    return key.split(" ", 1)[1] if " " in key else key


def _merge_history(hist: dict, tcp: dict, udp: dict, now: float) -> None:
    """Копит наблюдения по целям за всё окно. Снимок каждые 2с перезаписывался,
    и краткие таймауты/ретраи терялись; история даёт «где именно не бьётся»:
    состояния и их частоту, первое/последнее появление цели."""
    for proto, snap in (("tcp", tcp), ("udp", udp)):
        for key, v in snap.items():
            h = hist.setdefault(_hist_key(proto, key),
                                {"proto": proto, "states": {},
                                 "first": now, "last": now, "snapshots": 0})
            state = v["state"] if proto == "tcp" else "UDP"
            h["states"][state] = h["states"].get(state, 0) + 1
            h["state"] = state
            h["last"] = now
            h["snapshots"] += 1


def _capture_into_history(hist: dict, cap: dict, now: float) -> None:
    """Добавляет в историю счётчики pktmon по целям (исходящие→входящие)."""
    for key, v in (cap or {}).items():
        h = hist.setdefault(_hist_key("udp", key),
                            {"proto": "udp", "states": {}, "first": now,
                             "last": now, "snapshots": 0, "state": "UDP"})
        h["sent"] = h.get("sent", 0) + int(v.get("sent", 0))
        h["recv"] = h.get("recv", 0) + int(v.get("recv", 0))
        h["last"] = now
        if not h["snapshots"]:
            h["snapshots"] = 1
            h["states"]["UDP"] = 1


def _verdict(hist: dict, ipv6: bool, no_conn: bool,
             dns: Optional[dict] = None) -> str:
    if no_conn:
        return ("Нет соединений - включите анализ и воспроизведите проблему "
                "(зайдите в игру/попробуйте обновление) во время наблюдения.")
    dns = dns or {}
    parts = []
    if ipv6:
        parts.append("обнаружен IPv6 - обход работает только по IPv4")

    def _name(ip: str) -> str:
        doms = dns.get(ip)
        return f"{ip} ({', '.join(doms[:2])})" if doms else ip

    syn_fail, established, udp_dead = [], [], []
    for key, h in hist.items():
        states = h.get("states", {})
        endpoint = _hist_endpoint(key)
        if h.get("proto") == "tcp":
            if "SynSent" in states and "Established" not in states:
                syn_fail.append(endpoint)
            elif "Established" in states:
                established.append(endpoint)
        elif h.get("sent", 0) > 0 and h.get("recv", 0) == 0:
            udp_dead.append(endpoint)
    if syn_fail:
        hint = ("SynSent без ответа: "
                + ", ".join(_name(k.rsplit(":", 1)[0]) for k in syn_fail[:4])
                + " - SYN не получает ответа (возможен IP-блок провайдера). "
                "Десинк SYN-дроп не лечит - нужен WARP.")
        if established:
            hint += f" Остальные соединения работают ({len(established)})."
        parts.append(hint)
    elif established:
        parts.append("TCP-соединения устанавливаются - сеть работает, проблема, "
                     "вероятно, на стороне приложения/сервиса.")
    if udp_dead:
        parts.append("UDP без ответа: " + ", ".join(udp_dead[:4])
                     + " - исходящие идут, входящих нет (глушится ТСПУ/сервером). "
                       "Нужен WARP.")
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
        """Запуск анализа. process - имя процесса (маска) или числовой PID.
        Если процесс ещё не запущен - ждём появления до wait_sec секунд
        (захват «с нуля»: пользователь запускает игру после старта анализа)."""
        with self._lock:
            # двойной POST: до старта потока is_alive()==False и второй старт
            # перетирал _thread/_state (L8) - вся процедура под локом
            if self._thread is not None and self._thread.is_alive():
                return False, "Анализ уже запущен"
            if duration != 0 and duration < 5:
                duration = 30
            self._thread = threading.Thread(
                target=self._run, args=(process, duration, wait_sec), daemon=True)
            self._stop_flag.clear()
            self._state = {"process": process, "elapsed": 0,
                           "duration": duration, "tcp": {}, "udp": {},
                           "history": {}, "udp_capture": None, "dns": {},
                           "verdict": "", "error": "", "phase": "старт"}
            self._thread.start()
        return True, "Анализ запущен"

    def _find_pids(self, spec: str) -> list[int]:
        """spec: имя-маска ('WardogsClient') или числовой PID."""
        spec = (spec or "").strip()
        if spec.isdigit():
            return [int(spec)]
        # Из POST поле попадает в PowerShell-скрипт от имени администратора:
        # валидация + экранирование кавычек (H4, инъекция от админа)
        if not re.fullmatch(r"[\w .\-]+", spec, flags=re.UNICODE):
            return []
        safe = spec.replace("'", "''")
        script = (f"Get-Process | Where-Object {{ $_.ProcessName -like '*{safe}*' }} "
                  "| Select-Object -ExpandProperty Id | ConvertTo-Json -Compress")
        data = _ps_json(script)
        return [int(p) for p in data]

    def _run(self, spec: str, duration: int, wait_sec: int) -> None:
        # Всё тело - внутри try: _find_pids ходит в PowerShell и может
        # упасть (нечисловой элемент в JSON, ps недоступен). Раньше он стоял
        # ДО try, и такой сбой убивал поток молча: UI навсегда показывал
        # «ожидание процесса», finally (сброс pktmon) не выполнялся
        # (REVIEW_VERDICT.md 2.8).
        try:
            self._run_inner(spec, duration, wait_sec)
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._state.update(
                    {'error': f'Не удалось разобрать процесс: {e}',
                     'phase': 'завершено'})
            _applog('probe', f'_run({spec!r}) упал вне основного try: {e!r}')
        finally:
            utils.run_quiet(['pktmon', 'stop'])
            utils.run_quiet(['pktmon', 'filter', 'remove'])

    def _run_inner(self, spec: str, duration: int, wait_sec: int) -> None:
        pids = self._find_pids(spec)
        waited = 0
        if not pids and wait_sec > 0:
            with self._lock:
                self._state.update({"phase": f"ожидание процесса '{spec}'... "
                                            "(запустите игру)"})
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
        dns_seen: dict[str, list[str]] = {}
        last_dns = 0.0
        last_udp_rescan = 0.0
        try:
            handle = _run_pktmon(pids, etl, txt)
            while (duration <= 0 or time.time() - start < duration) \
                    and not self._stop_flag.is_set():
                # UDP-сокеты игровых клиентов открываются ПОСЛЕ старта: раньше
                # снапшот портов брался один раз, и при пустом списке захват не
                # стартовал вовсе, а новые порты не попадали в фильтры (аудит
                # 2026-10: Ace Combat - «UDP-захват: 0/0»). Пере-сканируем.
                if time.time() - last_udp_rescan >= 10:
                    last_udp_rescan = time.time()
                    # PID тоже обновляем: игры/анти-чит поднимают дочерние
                    # процессы уже после старта - у них свои сокеты, без этого
                    # их соединения не попадали ни в снимки, ни в захват (аудит)
                    for pid in self._find_pids(spec):
                        if pid not in pids:
                            pids.append(pid)
                    if handle is None:
                        handle = _run_pktmon(pids, etl, txt)
                    else:
                        for p in _udp_ports(pids):
                            if p not in handle["ports"]:
                                utils.run_quiet(["pktmon", "filter", "add",
                                                 f"gp{p}", "-t", "UDP", "-p", str(p)])
                                handle["ports"].append(p)
                tcp = _tcp_snapshot(pids)
                udp = _udp_snapshot(pids)
                if any(":" in k.rsplit(":", 1)[0] for k in list(tcp) + list(udp)):
                    ipv6 = True
                elapsed = int(time.time() - start)
                if time.time() - last_dns >= 5:
                    last_dns = time.time()
                    for ip, names in _dns_cache_entries().items():
                        acc = dns_seen.setdefault(ip, [])
                        for n in names:
                            if n not in acc:
                                acc.append(n)
                with self._lock:
                    _merge_history(self._state["history"], tcp, udp, time.time())
                    self._state.update({"tcp": tcp, "udp": udp, "elapsed": elapsed,
                                        "ipv6": ipv6, "pids_count": len(pids),
                                        "phase": "наблюдение"})
                time.sleep(2)
            udp_capture = _finish_pktmon(handle) if handle else {}
            with self._lock:
                _capture_into_history(self._state["history"],
                                      (udp_capture or {}).get("ips", {}), time.time())
                remote_ips = {_hist_endpoint(k).rsplit(":", 1)[0]
                              for k in self._state["history"]}
                no_conn = not self._state["history"]
            # финальный кэш + накопленное за сессию (короткие TTL успевают уйти)
            for ip, names in _dns_cache_entries().items():
                acc = dns_seen.setdefault(ip, [])
                for n in names:
                    if n not in acc:
                        acc.append(n)
            dns = {ip: dns_seen[ip] for ip in remote_ips if ip in dns_seen} \
                if remote_ips else {}
            verdict = _verdict(self._state["history"],
                               self._state.get("ipv6", False), no_conn, dns)
            with self._lock:
                self._state.update({"udp_capture": udp_capture,
                                    "udp_ports": (handle or {}).get("ports", []),
                                    "dns": dns,
                                    "verdict": verdict, "phase": "завершено",
                                    "elapsed": int(time.time() - start)})
        except Exception as e:  # noqa: BLE001
            # pktmon снимаем в finally внешнего _run - здесь только причина
            with self._lock:
                self._state.update({"error": str(e), "phase": "завершено"})

    def stop(self) -> dict:
        self._stop_flag.set()
        with self._lock:
            if self._state and not self._state.get("error"):
                self._state["phase"] = "остановка..."
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
        if s.get("pids_count"):
            lines.append(f"Процессов под наблюдением: {s['pids_count']} "
                         "(PID и UDP-порты обновляются каждые 10 с)")
        if s.get("error"):
            lines.append(f"Ошибка: {s['error']}")
        lines.append("")
        lines.append("--- Цели (история за окно наблюдения) ---")
        hist = s.get("history", {})
        if not hist:
            lines.append("(нет)")
        for k, h in sorted(hist.items(),
                           key=lambda kv: (-kv[1].get("snapshots", 0), kv[0])):
            states = h.get("states", {})
            dur = int(max(0.0, h.get("last", 0) - h.get("first", 0)))
            if h.get("proto") == "udp":
                metric = (f"пакеты {h.get('sent', 0)}→{h.get('recv', 0)}"
                          if (h.get("sent") or h.get("recv"))
                          else f"снимков {h.get('snapshots', 0)}")
            else:
                metric = f"снимков {h.get('snapshots', 0)}, ~{dur} с"
            if h.get("proto") == "tcp" and "SynSent" in states \
                    and "Established" not in states:
                flag = "  <-- SYN без ответа (возможен IP-блок)"
            elif h.get("proto") == "udp" and h.get("sent", 0) > 0 \
                    and h.get("recv", 0) == 0:
                flag = "  <-- входящих нет (глушится)"
            elif "Established" in states:
                flag = "  <-- работало"
            else:
                flag = ""
            lines.append(f"{_hist_endpoint(k):<24} {h.get('state', '?'):<12} {metric}{flag}")
        cap = s.get("udp_capture") or {}
        if cap:
            lines.append("")
            if cap.get("incomplete"):
                lines.append(f"UDP-захват: разбор неполный ({cap.get('reason', 'причина неизвестна')})"
                             " - счётчики пакетов не показаны, чтобы не выдать "
                             "обрыв за блокировку")
            else:
                lines.append("UDP-захват: отправлено "
                             f"{cap.get('sent', 0)}, получено {cap.get('recv', 0)}")
                ports = s.get("udp_ports") or []
                if ports:
                    shown = ", ".join(str(p) for p in ports[:12])
                    if len(ports) > 12:
                        shown += "…"
                    lines.append(f"UDP-порты в захвате ({len(ports)}): {shown}")
        else:
            lines.append("")
            lines.append("UDP-захват: не вёлся (UDP-сокеты процесса не "
                         "обнаружены за всё время наблюдения)")
        dns = s.get("dns", {})
        if dns:
            lines.append("")
            lines.append("--- Домены (DNS-кэш) ---")
            for ip, doms in dns.items():
                lines.append(f"{ip:<20} -> {', '.join(doms)}")
        lines.append("")
        lines.append("--- Вердикт ---")
        lines.append(s.get("verdict", ""))
        lines.append("")
        lines.append("Совет для точного диагноза: запускать анализ ДО проблемного "
                     "действия")
        lines.append("(вход в онлайн, старт матча) и держать до повторения проблемы -")
        lines.append("тогда зависший endpoint (SYN без ответа) попадёт в отчёт.")
        return "\n".join(lines)

    def save_report(self) -> Path:
        """Отчёт - в logs/ программы: '<имя_процесса>_<дата_время>.txt'.

        Всё, кроме латиницы и цифр, заменяется на '_' - в т.ч. пробелы и
        точки: '.exe' в имени файла сбивал тип файла и небезопасен при обмене.
        """
        import datetime as _dt
        import re as _re
        spec = str(self.get_status().get("process") or "").strip()
        safe = _re.sub(r"[^A-Za-z0-9]+", "_", spec).strip("_") or "process"
        logs = utils.app_root() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = logs / f"{safe}_{ts}.txt"
        path.write_text(self.report_text(), encoding="utf-8")
        _applog("probe", f"отчёт сохранён: {path}")
        return path