from __future__ import annotations

import ipaddress
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.test_logger import TestLogger

from core.launcher import build_args_from_preset, write_run_bat, launch_winws2_bat


# ── Host tiers ──────────────────────────────────────────────────

# Realistic browser headers so curl requests are not rejected by servers
# that block headless/bot-looking requests (e.g. some CDNs return 403 otherwise).
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)
BROWSER_HEADERS = [
    "-H", f"User-Agent: {BROWSER_USER_AGENT}",
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Language: en-US,en;q=0.5",
    "-H", "Accept-Encoding: identity",
]

# Domains counted in network_rate — MUST be covered by our hostlists
# (zapret desyncs them), otherwise a DPI block outside profile control
# would distort the strategy score.
RATED_HOSTS = [
    "discord.com", "gateway.discord.gg", "cdn.discordapp.com", "updates.discord.com",
    "www.youtube.com", "youtu.be", "i.ytimg.com", "redirector.googlevideo.com",
    "github.com", "raw.githubusercontent.com", "storage.googleapis.com",
]

# Probed but NOT counted in network_rate: excluded / not-covered hosts.
# Shows the raw network state (RF-blocked sites, excluded services) without
# distorting the strategy comparison.
CONTROL_HOSTS = [
    "www.google.com", "www.gstatic.com",
    "www.cloudflare.com", "cdnjs.cloudflare.com",
    "web.telegram.org", "api.telegram.org",
    "x.com", "www.facebook.com", "www.instagram.com",
    "www.linkedin.com", "web.whatsapp.com",
    "fcm.googleapis.com", "api.push.apple.com",
    "vk.ru", "ya.ru", "www.gosuslugi.ru",
]

TEST_HOSTS = RATED_HOSTS + CONTROL_HOSTS
CONTROL_DOMAINS = frozenset(CONTROL_HOSTS)

# Test type per domain
# "http" = curl GET (returns HTTP code). "tls" = handshake only.
HOST_TEST: dict[str, str] = {
    "discord.com":              "http",
    "gateway.discord.gg":       "tls",
    "cdn.discordapp.com":       "tls",
    "updates.discord.com":      "tls",
    "www.youtube.com":          "http",
    "youtu.be":                 "http",
    "i.ytimg.com":              "tls",
    "redirector.googlevideo.com": "tls",
    "github.com":               "http",
    "raw.githubusercontent.com": "http",
    "storage.googleapis.com":   "tls",
    "www.google.com":           "http",
    "www.gstatic.com":          "tls",
    "www.cloudflare.com":       "http",
    "cdnjs.cloudflare.com":     "tls",
    "web.telegram.org":         "http",
    "api.telegram.org":         "http",
    "x.com":                    "http",
    "www.facebook.com":         "http",
    "www.instagram.com":        "http",
    "www.linkedin.com":         "http",
    "web.whatsapp.com":         "http",
    "fcm.googleapis.com":       "tls",
    "api.push.apple.com":       "tls",
    "vk.ru":                    "http",
    "ya.ru":                    "http",
    "www.gosuslugi.ru":         "http",
}

# PING hosts (ICMP only, no curl)
PING_HOSTS: list[str] = [
    "1.1.1.1", "1.0.0.1",
    "8.8.8.8", "8.8.4.4",
    "9.9.9.9",
]

# Hosts probed WITHOUT protection before the profile sweep (naked baseline).
# If every strategy yields the same result as this baseline, winws2 is
# probably not altering traffic on this machine (or the DPI is extreme).
NAKED_BASELINE_HOSTS: list[str] = [
    "discord.com", "www.youtube.com", "gateway.discord.gg", "i.ytimg.com",
]

# TCP 16-20 test body size (64KB random — stateful DPI cuts the stream mid-transfer).
TCP1620_BODY = 64 * 1024

# CDN test hosts (опционально, через галочку)
CDN_HOSTS = [
    "hyperion-cs.github.io", "www.mobil.com.se", "cdn.apple-mapkit.com",
    "amplifon.com", "optout.aboutads.info", "cdn.eso.org",
    "go.coveo.com", "justice.gov", "img.wzstats.gg", "esm.sh",
    "antoniotartaglia.it", "status.moow.info", "ui-arts.com",
    "app.thecuriositylibrary.com", "admin.survey54.com", "ssl.p.jwpcdn.com",
    "www.jetblue.com", "buyvm.net", "dmvideo.download",
    "gcore.com", "api.usercentrics.eu", "widgets.reputation.com",
    "king.hr", "mail.server.apaone.com", "nioges.com",
    "5fd8bdae.nip.io", "net4u.de", "elecane.com",
    "store.takeda.com", "sh00065.hostgator.com", "ged.com.sg",
    "www.adwin.fr", "www.emca.be", "www.velivole.fr",
    "askit-app.de", "us.rudder.qntmnet.com",
]
CDN_PROVIDERS: dict[str, str] = {
    "hyperion-cs.github.io": "Self",
    "www.mobil.com.se": "Akamai",
    "cdn.apple-mapkit.com": "Akamai",
    "amplifon.com": "AWS",
    "optout.aboutads.info": "AWS",
    "cdn.eso.org": "CDN77",
    "go.coveo.com": "Cloudflare",
    "justice.gov": "Cloudflare",
    "img.wzstats.gg": "Cloudflare",
    "esm.sh": "Cloudflare",
    "antoniotartaglia.it": "Contabo",
    "status.moow.info": "Contabo",
    "ui-arts.com": "DigitalOcean",
    "app.thecuriositylibrary.com": "DigitalOcean",
    "admin.survey54.com": "DigitalOcean",
    "ssl.p.jwpcdn.com": "Fastly",
    "www.jetblue.com": "Fastly",
    "buyvm.net": "FT/BuyVM",
    "dmvideo.download": "FT/BuyVM",
    "gcore.com": "Gcore",
    "api.usercentrics.eu": "GCP",
    "widgets.reputation.com": "GCP",
    "king.hr": "Hetzner",
    "mail.server.apaone.com": "Hetzner",
    "nioges.com": "Hetzner",
    "5fd8bdae.nip.io": "Hetzner",
    "net4u.de": "Hetzner",
    "elecane.com": "Melbicom",
    "store.takeda.com": "Azure",
    "sh00065.hostgator.com": "Oracle",
    "ged.com.sg": "Oracle",
    "www.adwin.fr": "OVH",
    "www.emca.be": "OVH",
    "www.velivole.fr": "Scaleway",
    "askit-app.de": "Vultr",
    "us.rudder.qntmnet.com": "Vultr",
}

WINDIVERT_CLEANUP_DELAY = 0.5


@dataclass
class TestResult:
    domain: str
    test_type: str
    status: str
    status_code: int = 0
    time_ms: float = 0.0
    error: str = ""
    alias: bool = False  # True = www-added variant, not the primary domain


@dataclass
class ProfileTestResult:
    profile_name: str
    results: list[TestResult] = field(default_factory=list)
    ok_count: int = 0
    fail_count: int = 0
    total_time: float = 0.0
    success_rate: float = 0.0
    # Strategy score on network tests ONLY (curl/TLS, pings excluded).
    # Pings measure raw reachability, not DPI bypass: including them in the
    # score produces misleading "partial" results (e.g. all pings OK but
    # every blocked host still blocked).
    net_ok_count: int = 0
    net_fail_count: int = 0
    net_total: int = 0
    network_rate: float = 0.0
    ping_ok_count: int = 0
    ping_total: int = 0
    tier: str = "full"
    provider_hop: int = 0      # first non-private hop (TTL probe)
    provider_ip: str = ""       # IP of that hop
    cdn_results: list[TestResult] = field(default_factory=list)


class _TestAbort(Exception):
    def __init__(self, result=None): self.result = result


class Zapret2Tester:
    def __init__(self, root_dir: Path, timeout: int = 8) -> None:
        self.root_dir = Path(root_dir)
        self.bin_dir = self.root_dir / "bin"
        self.lua_dir = self.root_dir / "lua"
        self.blobs_dir = self.root_dir / "blobs"
        self.hostlists_dir = self.root_dir / "hostlists"
        self.timeout = timeout
        self._original_timeout = timeout
        self.shutdown_event = threading.Event()
        self._process: Optional[subprocess.Popen] = None
        self._logger: Optional["TestLogger"] = None
        # TTL probe result cache: provider hop position never changes between
        # profiles in one session — probe tracert once, reuse for all profiles.
        self._ttl_cache: Optional[dict] = None

    def set_logger(self, logger: Optional["TestLogger"]) -> None:
        self._logger = logger

    def _ensure_winws2_dead(self) -> None:
        # Kill managed process handle first (by PID) — чистый PID-таргетинг
        self._kill_managed()

        # Минимальная задержка на освобождение WinDivert драйвера
        # Даже если процесс уже мёртв, WinDivert освобождает хендлы асинхронно
        time.sleep(WINDIVERT_CLEANUP_DELAY)

        # Проверяем, остался ли winws2 процесс.
        if not self._any_winws2_running():
            return

        # Чужой winws2 ещё жив — blanket kill (крайняя мера)
        self._taskkill_safe("winws2.exe")

        # Poll: ждём освобождения WinDivert вместо фиксированного sleep
        self._wait_windivert_free()

    def _any_winws_running(self) -> bool:
        """True если хотя бы один winws2.exe или winws.exe запущен."""
        for image_name in ("winws2.exe", "winws.exe"):
            try:
                r = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
                    capture_output=True, text=True, encoding="oem", errors="replace", timeout=3,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if image_name.lower() in r.stdout.lower():
                    return True
            except (subprocess.TimeoutExpired, OSError):
                pass
        return False

    def _any_winws2_running(self) -> bool:
        """True если winws2.exe запущен (только winws2, без winws.exe)."""
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq winws2.exe", "/NH"],
                capture_output=True, text=True, encoding="oem", errors="replace", timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if "winws2.exe" in r.stdout.lower():
                return True
        except (subprocess.TimeoutExpired, OSError):
            pass
        return False

    def _wait_windivert_free(self, timeout: float = WINDIVERT_CLEANUP_DELAY * 4) -> None:
        """Poll пока winws2 процессы не исчезнут (WinDivert освобождается).
       _TIMEOUT — upper bound, обычно завершается за <100ms если kill уже отработал."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._any_winws2_running():
                return
            time.sleep(0.1)

    def _kill_managed(self) -> None:
        proc = self._process
        if proc is None:
            return
        pid = proc.pid
        self._process = None
        # Prefer taskkill on PID (cleaner than terminate/kill chain)
        self._run_quiet(["taskkill", "/F", "/PID", str(pid)], timeout=5.0)
        if not self._any_winws2_running():
            return
        # Fallback: terminate → kill
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            try:
                proc.kill()
                proc.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass

    @staticmethod
    def _run_quiet(args: list[str], timeout: float = 6.0) -> None:
        """Run a subprocess that may hang; guaranteed timeout, never raises."""
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="oem", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
        except Exception:
            pass

    @staticmethod
    def _process_exists(image_name: str) -> bool:
        """Quick check if any process with the given image name is running."""
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
                capture_output=True, text=True, encoding="oem", errors="replace", timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return image_name.lower() in r.stdout.lower()
        except (subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def _kill_never_hang(image_name: str) -> None:
        """Kill process by image name using multiple fallback methods.

        Never hangs: checks if process exists first, each method has
        a short timeout, and if all fail we just return.
        """
        if not Zapret2Tester._process_exists(image_name):
            return

        # Method 1: taskkill
        Zapret2Tester._run_quiet(["taskkill", "/F", "/IM", image_name], timeout=6.0)
        if not Zapret2Tester._process_exists(image_name):
            return

        # Method 2: wmic
        Zapret2Tester._run_quiet(
            ["wmic", "process", "where", f"name='{image_name}'", "delete"],
            timeout=6.0,
        )
        if not Zapret2Tester._process_exists(image_name):
            return

        # Method 3: PowerShell
        base = image_name.replace(".exe", "").replace(".EXE", "")
        Zapret2Tester._run_quiet(
            ["powershell", "-NoProfile", "-Command",
             f"Stop-Process -Name '{base}' -Force -ErrorAction SilentlyContinue"],
            timeout=6.0,
        )

    @staticmethod
    def _taskkill_safe(image_name: str) -> None:
        """Kill process, never hang. Delegates to multi-method kill."""
        Zapret2Tester._kill_never_hang(image_name)

    def _run_profile(self, profile_name: str, ipset_catchall: bool = False) -> bool:
        exe_path = self.bin_dir / "winws2.exe"
        if not exe_path.exists():
            exe_path = self.root_dir / "winws2.exe"
        if not exe_path.exists():
            return False

        preset = self.root_dir / "presets" / f"{profile_name}.txt"
        if not preset.exists():
            return False

        self._wait_windivert_free()

        args = build_args_from_preset(self.root_dir, self.lua_dir, self.blobs_dir, preset,
                                      ipset_catchall=ipset_catchall)
        bat = self.root_dir / "_zapret_run.bat"
        write_run_bat(self.root_dir, bat, exe_path, args)

        ok = launch_winws2_bat(bat, self.root_dir, timeout=5.0)
        self._process = None
        return ok

    def _ping_test(self, domain: str) -> TestResult:
        start = time.time()
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", str(self.timeout * 1000), domain],
                capture_output=True, text=True, encoding="oem", errors="replace", timeout=self.timeout + 2,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            elapsed = (time.time() - start) * 1000
            if result.returncode == 0:
                return TestResult(domain, "ping", "OK", time_ms=elapsed)
            return TestResult(domain, "ping", "FAIL", time_ms=elapsed, error="Ping failed")
        except (subprocess.TimeoutExpired, OSError) as e:
            elapsed = (time.time() - start) * 1000
            return TestResult(domain, "ping", "ERROR", time_ms=elapsed, error=str(e))

    # ── curl-based tests (как в zapret_test_final.py — проверено, работает) ──

    def _curl_test(self, domain: str, test_type: str, path: str = "/") -> TestResult:
        start = time.time()
        url = f"https://{domain}{path}"
        try:
            r = subprocess.run(
                ["curl.exe", "-4", "-I", "-s", "-m", str(min(int(self.timeout), 6)),
                 "--connect-timeout", "2", "--show-error"]
                + BROWSER_HEADERS
                + ["-o", "NUL", "-w", "%{http_code}", url],
                capture_output=True, text=True, encoding="oem", errors="replace", timeout=self.timeout + 5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            elapsed = (time.time() - start) * 1000
            code_str = r.stdout.strip()
            if code_str.isdigit():
                code = int(code_str)
                if code >= 100:
                    return TestResult(domain, test_type, "OK", code, elapsed)
            # HEAD failed — try GET (no -I)
            r = subprocess.run(
                ["curl.exe", "-4", "-s", "-m", str(min(int(self.timeout), 6)),
                 "--connect-timeout", "2", "--show-error"]
                + BROWSER_HEADERS
                + ["-o", "NUL", "-w", "%{http_code}", url],
                capture_output=True, text=True, encoding="oem", errors="replace", timeout=self.timeout + 5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            elapsed = (time.time() - start) * 1000
            code_str = r.stdout.strip()
            if code_str.isdigit():
                code = int(code_str)
                if code >= 100:
                    return TestResult(domain, test_type, "OK", code, elapsed)
                return TestResult(domain, test_type, "BLOCKED", code, elapsed)
            if test_type == "tls:443" and r.returncode == 0:
                return TestResult(domain, test_type, "OK", time_ms=elapsed)
            err = r.stderr[:80] if r.stderr else f"rc={r.returncode}"
            return TestResult(domain, test_type, "ERROR", 0, elapsed, err)
        except subprocess.TimeoutExpired:
            elapsed = (time.time() - start) * 1000
            return TestResult(domain, test_type, "TIMEOUT", 0, elapsed, "timeout")
        except OSError as e:
            elapsed = (time.time() - start) * 1000
            return TestResult(domain, test_type, "ERROR", 0, elapsed, f"curl not found: {e}")

    def _expand_with_www(self, domains: list[str]) -> list[tuple[str, bool]]:
        """Expand domain list with www variants.
        Skips subdomains (redirector.*, gateway.*, cdn.*, i.*, updates.*) — they don't have www variants.
        Domains specified with www. prefix only test the www variant (non-www often redirects/fails).
        Returns list of (domain, is_alias) tuples where is_alias=True for added www/non-www variants."""
        CDN_PREFIXES = ("redirector.", "gateway.", "cdn.", "cdnjs.", "i.", "updates.")
        NO_WWW = {"youtu.be"}
        expanded: list[tuple[str, bool]] = []
        seen: set[str] = set()
        for d in domains:
            base = d[4:] if d.startswith("www.") else d
            # Skip www expansion for CDN subdomains, NO_WWW domains and any
            # 3+ label subdomain (web.telegram.org, api.push.apple.com, ...)
            # — they have no www variant.
            if base in NO_WWW or base.startswith(CDN_PREFIXES) or base.count(".") >= 2:
                if base not in seen:
                    expanded.append((base, False))
                    seen.add(base)
                continue
            if d.startswith("www."):
                # Domain explicitly has www — only test the www variant
                if d not in seen:
                    expanded.append((d, False))
                    seen.add(d)
                continue
            for variant in (base, f"www.{base}"):
                if variant not in seen:
                    is_alias = variant != d
                    expanded.append((variant, is_alias))
                    seen.add(variant)
        return expanded

    def _host_test_type(self, domain: str) -> str:
        """Resolve test type for domain — falls back to base if www variant not in HOST_TEST."""
        t = HOST_TEST.get(domain)
        if t:
            return t
        base = domain[4:] if domain.startswith("www.") else domain
        return HOST_TEST.get(base, "http")

    def _run_domain_tests(self, domains: list[str], concurrency: int = 5, http_only: bool = False, result_cb=None, expand_www: bool = False, progress_cb=None) -> list[TestResult]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        if expand_www:
            test_items = self._expand_with_www(domains)
        else:
            test_items = [(d, False) for d in domains]
        total = len(test_items)
        done = 0
        results = []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {}
            for d, is_alias in test_items:
                if http_only:
                    futures[pool.submit(self._curl_test, d, "http", path="/")] = (d, is_alias)
                else:
                    ttype = self._host_test_type(d)
                    label = "tls:443" if ttype == "tls" else "https"
                    futures[pool.submit(self._curl_test, d, label)] = (d, is_alias)
            for fut in as_completed(futures):
                d, is_alias = futures[fut]
                r = fut.result()
                r.alias = is_alias
                results.append(r)
                done += 1
                if progress_cb:
                    progress_cb(done, total)
                if result_cb:
                    result_cb(r)
        return results

    # ── TCP 16-20 test (from dpi-checkers) ─────────────────────────
    # Sends POST with 64KB random body after HEAD verification.
    # If HEAD succeeds but POST connection dies (timeout/reset) →
    # stateful DPI detects suspicious content and kills the connection.

    def _run_tcp1620_tests(self, domains: list[str], concurrency: int = 5) -> list[TestResult]:
        """Run TCP 16-20 tests via curl POST with 64KB random body."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        body_file = self.root_dir / "tcp1620_test_body.bin"
        try:
            body_file.write_bytes(os.urandom(TCP1620_BODY))
        except OSError:
            return [TestResult(d, "tcp1620", "ERROR", error="Cannot create test body") for d in domains]
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {}
            for d in domains:
                futures[pool.submit(self._tcp1620_test_curl, d, body_file)] = d
            for fut in as_completed(futures):
                results.append(fut.result())
        try:
            body_file.unlink()
        except OSError:
            pass
        return results

    def _tcp1620_test_curl(self, domain: str, body_file: Path) -> TestResult:
        """TCP 16-20 test via curl: POST 64KB body, detect stateful DPI cutoff."""
        start = time.time()
        try:
            r = subprocess.run(
                ["curl.exe", "-4", "--no-sessionid", "--no-keepalive",
                 "-s", "-m", str(min(int(self.timeout), 6)),
                 "-w", "%{http_code} %{size_upload}", "-o", "NUL",
                 "--data-binary", f"@{body_file}",
                 f"https://{domain}/"],
                capture_output=True, text=True, encoding="oem", errors="replace", timeout=self.timeout + 5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            elapsed = (time.time() - start) * 1000
            parts = r.stdout.strip().split()
            code = int(parts[0]) if parts and parts[0].isdigit() else 0
            if code >= 200 and code < 500:
                # Server answered — the connection survived the 64KB upload:
                # no stateful-DPI cutoff on this path.
                return TestResult(domain, "tcp1620", "OK", code, elapsed)
            if code == 0:
                # No HTTP response at all while a plain GET on the same host
                # just succeeded: the 64KB upload got cut mid-stream — that's
                # the stateful-DPI signature (dpich "Detected").
                return TestResult(domain, "tcp1620", "TCP16_20", 0, elapsed,
                                  "upload cutoff — stateful DPI")
            return TestResult(domain, "tcp1620", "BLOCKED", code, elapsed)
        except subprocess.TimeoutExpired:
            elapsed = (time.time() - start) * 1000
            return TestResult(domain, "tcp1620", "TCP16_20", 0, elapsed, "POST timeout — stateful DPI")
        except OSError as e:
            elapsed = (time.time() - start) * 1000
            return TestResult(domain, "tcp1620", "ERROR", 0, elapsed, f"curl: {e}")

    @staticmethod
    def _simple_score(results: list[TestResult]) -> float:
        """Simple OK/total ratio (0.0–1.0)."""
        if not results:
            return 0.0
        ok = sum(1 for r in results if r.status == "OK")
        return ok / len(results)

    @staticmethod
    def _net_stats(results: list[TestResult]) -> tuple[int, int, int, float, int, int]:
        """Split results into network (curl/TLS) vs ping counters.

        Returns (net_ok, net_fail, net_total, network_rate_pct,
                 ping_ok, ping_total).  network_rate is the strategy score:
        pings measure raw reachability, not DPI bypass — including them
        inflates the score on machines where pings pass but every blocked
        host stays blocked (e.g. all 8 presets "20/30 (67%)" while actual
        connectivity was 4/13).
        """
        net = [r for r in results
               if r.test_type != "ping" and r.domain not in CONTROL_DOMAINS]
        pings = [r for r in results if r.test_type == "ping"]
        net_ok = sum(1 for r in net if r.status == "OK")
        net_total = len(net)
        net_fail = net_total - net_ok
        ping_ok = sum(1 for r in pings if r.status == "OK")
        rate = (net_ok / net_total * 100) if net_total else 0.0
        return net_ok, net_fail, net_total, rate, ping_ok, len(pings)

    # ── TTL probe ──────────────────────────────────────────────────
    # Runs a traceroute to detect the first hop outside the local network.
    # That hop is likely the provider's DPI equipment.
    # Result is stored in ProfileTestResult for later autottl optimization.

    @staticmethod
    def _is_private_ip(ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip).is_private
        except ValueError:
            return False

    def _probe_provider_ttl(self) -> dict:
        """Run tracert to google.com, return first non-private hop number and IP.
        Returns dict with hop (int), ip (str), or hop=0 if it fails.
        Result is cached per tester instance (see __init__)."""

        if self._ttl_cache is not None:
            return self._ttl_cache

        # 5 hops / 900ms per probe is enough to see the provider's DPI box
        # (usually hop 1-4) and bounds the worst case to ~14s instead of 25s+.
        tracert_targets = ["google.com", "discord.com", "github.com"]
        for target in tracert_targets:
            try:
                r = subprocess.run(
                    ["tracert", "-d", "-h", "5", "-w", "900", target],
                    capture_output=True, text=True, encoding="oem", errors="replace", timeout=14,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                output = r.stdout
                if not output:
                    continue
                lines = output.splitlines()
                import re as _re
                for line in lines:
                    line = line.strip()
                    # Match: " 3    12 ms    15 ms    10 ms  213.180.36.1"
                    m = _re.match(r'\s*(\d+)\s+<\d+', line)
                    if not m:
                        m = _re.match(r'\s*(\d+)\s+\d+', line)
                    if not m:
                        continue
                    hop = int(m.group(1))
                    # Extract IP at end of line
                    ip_match = _re.findall(r'(\d+\.\d+\.\d+\.\d+)', line)
                    if not ip_match:
                        continue
                    ip = ip_match[-1]
                    if not Zapret2Tester._is_private_ip(ip):
                        self._ttl_cache = {"hop": hop, "ip": ip, "target": target}
                        return self._ttl_cache
                    # If last hop and all were private, return the last one
                    if hop >= 5:
                        self._ttl_cache = {"hop": hop, "ip": ip, "target": target}
                        return self._ttl_cache
            except (subprocess.TimeoutExpired, OSError):
                continue

        # No result from any target — proceed without TTL info
        self._ttl_cache = {"hop": 0, "ip": "", "target": ""}
        return self._ttl_cache

    def _get_tier_hosts(self, tier: str) -> list[str]:
        return list(TEST_HOSTS)

    def _setup_profile(self, profile: str, progress_cb, _logged_progress, ipset_catchall: bool = False) -> tuple[str, str, str, float]:
        """Returns (profile_name, provider_hop, provider_ip) or raises early return via tuple[3] being 0."""
        profile_name = profile
        preset = self.root_dir / "presets" / f"{profile_name}.txt"
        if not preset.exists():
            raise _TestAbort(ProfileTestResult(profile_name=profile_name, results=[
                TestResult(profile_name, "process", "ERROR", error=f"Preset not found: {preset}"),
            ]))

        if self._logger:
            self._logger.progress(profile_name, "START")

        _logged_progress(5, f"[{profile_name}] запуск winws2...")
        if not self._run_profile(profile_name, ipset_catchall):
            raise _TestAbort(ProfileTestResult(profile_name=profile_name, results=[
                TestResult(profile_name, "process", "ERROR", error="winws2 not found or spawn failed"),
            ]))

        _logged_progress(7, f"[{profile_name}] ждём готовность WinDivert (1.5s)...")
        # launch_winws2_bat already confirmed the process is alive; WinDivert
        # opens its handle within a few hundred ms — 1.5s settle is enough
        # (was a fixed 5s sleep per profile).
        time.sleep(1.5)

        if not self._any_winws2_running():
            self._ensure_winws2_dead()
            raise _TestAbort(ProfileTestResult(profile_name=profile_name, results=[
                TestResult(profile_name, "process", "ERROR", error="winws2 did not start"),
            ]))

        import socket as _socket
        try:
            t0 = time.time()
            sock = _socket.create_connection(("discord.com", 443), timeout=3)
            rtt_ms = (time.time() - t0) * 1000
            sock.close()
            self.timeout = max(2.0, min(float(self._original_timeout), rtt_ms * 3 / 1000))
            _logged_progress(10, f"[{profile_name}] ✓ готов (RTT {rtt_ms:.0f}ms)")
        except OSError:
            self.timeout = self._original_timeout
            _logged_progress(10, f"[{profile_name}] ✓ запущен (timeout {self.timeout:.0f}s)")

        ttl_info = self._probe_provider_ttl()
        provider_hop = ttl_info["hop"]
        provider_ip = ttl_info["ip"]
        if provider_hop:
            _logged_progress(12, f"ТСПУ вероятно на хопе {provider_hop} ({provider_ip})")
        else:
            _logged_progress(12, "TTL probe не дал результата")

        return profile_name, provider_hop, provider_ip, self.timeout

    def _run_aux_tests(self, skip_cdn, _logged_progress, result_cb):
        cdn_results: list[TestResult] = []
        if not skip_cdn and self._any_winws2_running() and not self.shutdown_event.is_set():
            _logged_progress(97, "Проверка CDN-хостов...")
            cdn_results = self._run_domain_tests(CDN_HOSTS, concurrency=15, http_only=True, result_cb=result_cb)
            # TCP 16-20: POST 64KB — stateful DPI cuts the stream mid-transfer.
            # Only probed on hosts that answered (dead hosts tell nothing).
            alive = [r.domain for r in cdn_results if r.status == "OK"]
            if alive and not self.shutdown_event.is_set():
                _logged_progress(98, "Проверка stateful DPI (TCP 16-20)...")
                for r in self._run_tcp1620_tests(alive):
                    cdn_results.append(r)
                    if result_cb:
                        result_cb(r)
        return cdn_results

    def _build_result(self, profile_name, all_results, cdn_results, provider_hop, provider_ip, tier, _logged_progress):
        _logged_progress(97, "Остановка...")
        self._ensure_winws2_dead()
        ok_count = sum(1 for r in all_results if r.status == "OK")
        fail_count = sum(1 for r in all_results if r.status in ("BLOCKED", "TIMEOUT", "FAIL", "ERROR"))
        total_time = sum(r.time_ms for r in all_results)
        total = ok_count + fail_count
        success_rate = (ok_count / total * 100) if total else 0
        net_ok, net_fail, net_total, network_rate, ping_ok, ping_total = self._net_stats(all_results)
        if self._logger:
            self._logger.result(profile_name, ok_count, fail_count, success_rate, provider_hop, provider_ip or "")
        _logged_progress(100, f"Готово: {ok_count}/{total} OK ({success_rate:.0f}%)")
        return ProfileTestResult(
            profile_name=profile_name, results=all_results,
            ok_count=ok_count, fail_count=fail_count, total_time=total_time,
            success_rate=success_rate, tier=tier,
            net_ok_count=net_ok, net_fail_count=net_fail, net_total=net_total,
            network_rate=network_rate, ping_ok_count=ping_ok, ping_total=ping_total,
            provider_hop=provider_hop, provider_ip=provider_ip,
        )

    def test_profile(
        self,
        profile: str,
        progress_cb: Callable[[int, str], None],
        tier: str = "critical",
        result_cb: Optional[Callable[[TestResult], None]] = None,
        skip_cdn: bool = False,
        ipset_catchall: bool = False,
    ) -> ProfileTestResult:
        self.shutdown_event.clear()
        self._ensure_winws2_dead()

        def _logged_progress(pct: int, msg: str) -> None:
            if self._logger:
                self._logger.progress(profile, msg)
            progress_cb(pct, msg)

        # _setup_profile raises _TestAbort BEFORE the try below (preset missing,
        # winws2 not spawning).  A single broken profile must never kill the
        # whole sweep — return its error result so the caller can continue.
        try:
            profile_name, provider_hop, provider_ip, _ = self._setup_profile(
                profile, progress_cb, _logged_progress, ipset_catchall)
        except _TestAbort as e:
            if e.result is not None:
                return e.result
            return ProfileTestResult(profile_name=profile)

        domains = self._get_tier_hosts(tier)
        all_results: list[TestResult] = []
        tests_done = 0
        total_tests = len(domains) * 2 + len(PING_HOSTS)

        try:
            _logged_progress(15, f"Тест {len(domains)} доменов...")

            if self.shutdown_event.is_set():
                raise _TestAbort(ProfileTestResult(profile_name=profile_name))

            curl_total = len(domains) * 2  # +www expansion
            def _on_curl_progress(done_curl, total_curl):
                pct = 15 + int(done_curl * 40 / total_curl)
                progress_cb(pct, f"curl-тест {done_curl}/{total_curl}")

            for r in self._run_domain_tests(domains, concurrency=8, expand_www=True, result_cb=result_cb, progress_cb=_on_curl_progress):
                if self.shutdown_event.is_set():
                    raise _TestAbort(ProfileTestResult(profile_name=profile_name))
                all_results.append(r)
                tests_done += 1

            for domain in domains:
                if self.shutdown_event.is_set(): break
                all_results.append(self._ping_test(domain))
                if result_cb: result_cb(all_results[-1])
                tests_done += 1
                progress_cb(55 + int(tests_done * 20 / (len(domains) + len(PING_HOSTS))), f"ping {domain}")

            for host in PING_HOSTS:
                if self.shutdown_event.is_set(): break
                all_results.append(self._ping_test(host))
                if result_cb: result_cb(all_results[-1])
                tests_done += 1
                progress_cb(55 + int(tests_done * 20 / (len(domains) + len(PING_HOSTS))), f"ping {host}")

            cdn_results = self._run_aux_tests(skip_cdn, _logged_progress, result_cb)
            return self._build_result(profile_name, all_results, cdn_results, provider_hop, provider_ip, tier, _logged_progress)

        except _TestAbort as e:
            return e.result if e.result is not None else self._build_result(profile_name, all_results, [], provider_hop, provider_ip, tier, _logged_progress)

    def _test_baseline(
        self,
        profile_name: str,
        progress_cb: Callable[[int, str], None],
        tier: str = "smoke",
        result_cb: Optional[Callable[[TestResult], None]] = None,
        kill_processes: bool = False,
        skip_cdn: bool = False,
    ) -> ProfileTestResult:
        self.shutdown_event.clear()
        if kill_processes:
            self._ensure_winws2_dead()

        def _logged_progress(pct: int, msg: str) -> None:
            if self._logger:
                self._logger.progress(profile_name, msg)
            progress_cb(pct, msg)

        _logged_progress(5, f"{profile_name}: проверка...")

        domains = self._get_tier_hosts(tier)
        total_tests = len(domains) * 2 + len(PING_HOSTS)
        tests_done = 0
        all_results: list[TestResult] = []

        _logged_progress(15, f"{profile_name}: {len(domains)} доменов...")

        def _on_curl_progress(done_curl, total_curl):
            pct = 15 + int(done_curl * 40 / total_curl)
            progress_cb(pct, f"curl {done_curl}/{total_curl}")

        async_results = self._run_domain_tests(domains, concurrency=8, expand_www=True, result_cb=result_cb, progress_cb=_on_curl_progress)
        for r in async_results:
            if self.shutdown_event.is_set():
                return ProfileTestResult(profile_name=profile_name)
            all_results.append(r)
            tests_done += 1

        for domain in domains:
            if self.shutdown_event.is_set():
                return ProfileTestResult(profile_name=profile_name)
            all_results.append(self._ping_test(domain))
            if result_cb:
                result_cb(all_results[-1])
            tests_done += 1
            pct = 55 + int(tests_done * 20 / (len(domains) + len(PING_HOSTS)))
            progress_cb(pct, f"{profile_name} ping {domain}")

        for host in PING_HOSTS:
            if self.shutdown_event.is_set():
                return ProfileTestResult(profile_name=profile_name)
            all_results.append(self._ping_test(host))
            if result_cb:
                result_cb(all_results[-1])
            tests_done += 1
            pct = 55 + int(tests_done * 20 / (len(domains) + len(PING_HOSTS)))
            progress_cb(pct, f"{profile_name} ping {host}")

        cdn_results: list[TestResult] = []
        if not skip_cdn and not self.shutdown_event.is_set():
            _logged_progress(97, f"Проверка CDN-хостов ({profile_name})...")
            cdn_results = self._run_domain_tests(CDN_HOSTS, concurrency=15, http_only=True, result_cb=result_cb)

        ok_count = sum(1 for r in all_results if r.status == "OK")
        fail_count = sum(1 for r in all_results if r.status in ("BLOCKED", "TIMEOUT", "FAIL", "ERROR"))
        total_time = sum(r.time_ms for r in all_results)
        total = ok_count + fail_count
        success_rate = (ok_count / total * 100) if total else 0
        net_ok, net_fail, net_total, network_rate, ping_ok, ping_total = self._net_stats(all_results)

        result = ProfileTestResult(
            profile_name=profile_name,
            results=all_results,
            ok_count=ok_count,
            fail_count=fail_count,
            total_time=total_time,
            success_rate=success_rate,
            tier=tier,
            net_ok_count=net_ok,
            net_fail_count=net_fail,
            net_total=net_total,
            network_rate=network_rate,
            ping_ok_count=ping_ok,
            ping_total=ping_total,
            cdn_results=cdn_results,
        )

        if self._logger:
            self._logger.result(profile_name, ok_count, fail_count, success_rate)

        _logged_progress(100, f"{profile_name}: {ok_count}/{total} OK ({success_rate:.0f}%)")
        return result

    def test_current_setup(
        self,
        progress_cb: Callable[[int, str], None],
        tier: str = "smoke",
        result_cb: Optional[Callable[[TestResult], None]] = None,
        skip_cdn: bool = False,
    ) -> ProfileTestResult:
        """Test the CURRENT setup (whatever is running — likely Zapret 1)."""
        return self._test_baseline("__current__", progress_cb, tier, result_cb, kill_processes=False, skip_cdn=skip_cdn)

    def test_naked(
        self,
        progress_cb: Callable[[int, str], None],
        tier: str = "smoke",
        result_cb: Optional[Callable[[TestResult], None]] = None,
        skip_cdn: bool = False,
    ) -> ProfileTestResult:
        """Raw connection test WITHOUT any zapret running."""
        return self._test_baseline("__naked__", progress_cb, tier, result_cb, kill_processes=True, skip_cdn=skip_cdn)

    def run_naked_baseline(
        self,
        progress_cb: Callable[[int, str], None],
        result_cb: Optional[Callable[[TestResult], None]] = None,
    ) -> Optional[ProfileTestResult]:
        """Quick connectivity check with zero protection (4 hosts, ~3-5s).

        Runs before the profile sweep so the final recommendation can detect
        the "every strategy == naked" case — a sign that winws2 is not
        actually altering traffic on this machine, or the DPI blocks all
        desync attempts.  Returns None if the test was cancelled.
        """
        self.shutdown_event.clear()
        self._ensure_winws2_dead()
        if self.shutdown_event.is_set():
            return None
        progress_cb(2, "Голый тест (без защиты) — базовый уровень...")
        results = self._run_domain_tests(
            NAKED_BASELINE_HOSTS, concurrency=4, expand_www=False,
            result_cb=result_cb,
        )
        net_ok, net_fail, net_total, network_rate, *_ = self._net_stats(results)
        return ProfileTestResult(
            profile_name="__naked__", results=results,
            ok_count=net_ok, fail_count=net_fail,
            success_rate=network_rate,
            net_ok_count=net_ok, net_fail_count=net_fail, net_total=net_total,
            network_rate=network_rate, tier="smoke",
        )

    def collect_sanity_info(self, profile_name: str, blocked_domains: list[str]) -> dict:
        """Diagnostics that distinguish 'strong DPI' from 'winws2 does nothing'.

        Two cheap checks (no debug logging):
        1. dry-run of the SAME args the tester builds — winws2 prints how many
           desync profiles it loaded.  0-1 profiles (instead of the expected
           4-7 for default.txt) is the old short-path bug signature (§1):
           the preset is broken on THIS machine regardless of the DPI.
        2. List coverage — if a blocked domain is absent from every @lists/*.txt
           the preset references, its desync profile never fires (no_action,
           §15) and the strategy cannot bypass it.
        """
        exe = self.bin_dir / "winws2.exe"
        if not exe.exists():
            exe = self.root_dir / "winws2.exe"
        preset = self.root_dir / "presets" / f"{profile_name}.txt"
        if not exe.exists() or not preset.exists():
            return {"dry_run": {"ok": False, "profiles_loaded": None, "errors": ["winws2 или пресет не найден"]},
                    "list_coverage": []}

        dry = {"ok": True, "profiles_loaded": None, "errors": []}
        try:
            args = build_args_from_preset(self.root_dir, self.lua_dir, self.blobs_dir, preset)
            r = subprocess.run(
                [str(exe), "--dry-run"] + args,
                capture_output=True, text=True, encoding="oem", errors="replace",
                timeout=10, cwd=str(self.root_dir),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            output = ((r.stdout or "") + "\n" + (r.stderr or "")).lower()
            import re as _re
            m = None
            if "already running with the same filter" in output:
                # Another winws2 with the same filters is running (e.g. the
                # service): dry-run aborts early ("1 profile") and the count
                # is meaningless — but the list-coverage check still applies.
                dry["note"] = "winws2 уже запущен — dry-run не показателен"
            else:
                m = _re.search(r"(\d+)\s+user defined desync profile", output)
            if m:
                dry["profiles_loaded"] = int(m.group(1))
            for line in output.splitlines():
                s = line.strip()
                if any(marker in s for marker in
                       ("unknown option", "bad file", "cannot access file", "cannot open",
                        "lua error", "error loading", "cannot create")):
                    dry["errors"].append(s)
            if dry["errors"]:
                dry["ok"] = False
        except (OSError, subprocess.TimeoutExpired) as e:
            # WinError 740 = process needs elevation (tester normally runs
            # elevated, but never treat "can't spawn" as a broken engine).
            if getattr(e, "winerror", None) == 740 or "WinError 740" in str(e):
                dry = {"ok": True, "profiles_loaded": None, "errors": []}
            else:
                dry["ok"] = False
                dry["errors"].append(str(e))

        # ── List coverage ──
        include_lists: list[tuple[str, Path]] = []
        try:
            for line in preset.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line.startswith("--hostlist=") and "@lists/" in line:
                    name = line.split("=", 1)[1].split("/")[-1]
                    if not name.endswith(".txt"):
                        name += ".txt"
                    include_lists.append((name, self.root_dir / "lists" / name))
        except OSError:
            include_lists = []

        coverage: list[dict] = []
        for domain in blocked_domains:
            d = domain.lower()
            found = []
            for name, path in include_lists:
                if not path.exists():
                    continue
                try:
                    lines = [l.strip().lower() for l in path.read_text(encoding="utf-8-sig").splitlines()
                             if l.strip() and not l.strip().startswith(("#", "//"))]
                except OSError:
                    continue
                if any(d == l or d.endswith("." + l) for l in lines):
                    found.append(name)
            coverage.append({"domain": domain, "covered": bool(found), "lists": found})

        return {"dry_run": dry, "list_coverage": coverage}

    def is_running(self) -> bool:
        return self._any_winws2_running()

    def signal_shutdown(self) -> None:
        self.shutdown_event.set()
