from __future__ import annotations

import base64
import json
import subprocess
import threading
import time
import winsound
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse, parse_qs

from core.config import ConfigManager, DEFAULT_PROFILE, VERSION
from core.zapret_controller import ZapretController
from core.tester import Zapret2Tester, CDN_PROVIDERS, NAKED_BASELINE_HOSTS
from core.service_manager import SERVICE_NAME, is_installed as svc_installed, status as svc_status, install as svc_install, remove as svc_remove, start as svc_start, stop as svc_stop, build_service_bat
from core.collector import collect_all, export_data_package
from core.launcher import build_args_from_preset, validate_args
from core.test_logger import TestLogger


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js":  "application/javascript; charset=utf-8",
    ".json":"application/json; charset=utf-8",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".woff2":"font/woff2",
}


# ── Global state ─────────────────────────────────────────────

_root_dir: Optional[Path] = None
_controller: Optional[ZapretController] = None
_tester: Optional[Zapret2Tester] = None
_config_manager: Optional[ConfigManager] = None
_app_token: str = ""
_tester_lock = threading.Lock()
_server: Optional[HTTPServer] = None


# ── Tester shared state (polling replacement for WebSocket) ──

class TesterState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.progress_pct = 0
        self.progress_msg = ""
        self.results: list[dict] = []
        self.final_result: Optional[dict] = None
        self.all_results: Optional[list[dict]] = None
        self.error: Optional[str] = None
        self.cancelled = False
        self.action_type: Optional[str] = None
        self.logger: Optional[TestLogger] = None

    def reset(self):
        self.progress_pct = 0
        self.progress_msg = ""
        self.results = []
        self.final_result = None
        self.all_results = None
        self.error = None
        self.cancelled = False
        self.action_type = None
        self.logger = None

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "progress": {"percent": self.progress_pct, "message": self.progress_msg},
                "results": list(self.results),
                "final_result": self.final_result,
                "all_results": self.all_results,
                "error": self.error,
                "cancelled": self.cancelled,
                "action": self.action_type,
            }

    def set_progress(self, pct: int, msg: str) -> None:
        with self.lock:
            self.progress_pct = pct
            self.progress_msg = msg

    def add_result(self, data: dict) -> None:
        with self.lock:
            self.results.append(data)

    def set_final(self, result: dict, all_results: Optional[list[dict]] = None) -> None:
        with self.lock:
            self.final_result = result
            self.all_results = all_results
            self.running = False


_tester_state = TesterState()

# Update-check result cache: one check per application session.
_update_check_cache: Optional[dict] = None


# ── Helpers ──────────────────────────────────────────────────

def get_root_dir() -> Path:
    if _root_dir is None:
        raise RuntimeError("Service not initialised")
    return _root_dir

def get_controller() -> ZapretController:
    if _controller is None:
        raise RuntimeError("Service not initialised")
    return _controller

def get_config_manager() -> ConfigManager:
    if _config_manager is None:
        raise RuntimeError("Service not initialised")
    return _config_manager

def get_tester() -> Zapret2Tester:
    if _tester is None:
        raise RuntimeError("Service not initialised")
    return _tester


def init(root_dir: Path, token: str = "") -> None:
    global _root_dir, _controller, _tester, _config_manager, _app_token
    _root_dir = root_dir
    _app_token = token
    _config_manager = ConfigManager(root_dir)
    _controller = ZapretController(root_dir, config_manager=_config_manager)
    _tester = Zapret2Tester(root_dir)


def _play_completion_sound() -> None:
    try:
        winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        pass


def _serialize_result(res) -> dict:
    return {
        "profile": res.profile_name,
        "ok_count": res.ok_count,
        "fail_count": res.fail_count,
        "success_rate": res.success_rate,
        "net_ok_count": res.net_ok_count,
        "net_fail_count": res.net_fail_count,
        "net_total": res.net_total,
        "network_rate": res.network_rate,
        "ping_ok_count": res.ping_ok_count,
        "ping_total": res.ping_total,
        "total_time_ms": res.total_time,
        "provider_hop": res.provider_hop,
        "provider_ip": res.provider_ip,
        "results": [
            {"domain": r.domain, "test_type": r.test_type, "status": r.status,
             "time_ms": r.time_ms, "error": r.error}
            for r in res.results
        ],
        "cdn_results": [
            {"domain": r.domain, "test_type": r.test_type, "status": r.status,
             "time_ms": r.time_ms, "error": r.error,
             "cdn_provider": CDN_PROVIDERS.get(r.domain, "")}
            for r in res.cdn_results
        ],
    }


def _make_progress_cb(state: TesterState) -> Callable:
    def cb(pct: int, msg: str) -> None:
        with state.lock:
            state.progress_pct = pct
            state.progress_msg = msg
    return cb


def _make_result_cb(state: TesterState, profile: Optional[str] = None) -> Callable:
    def cb(r) -> None:
        is_cdn = r.domain in CDN_PROVIDERS
        payload = {
            "type": "test_result",
            "domain": r.domain,
            "test_type": r.test_type,
            "status": r.status,
            "status_code": r.status_code,
            "time_ms": r.time_ms,
            "error": r.error,
            "cdn_provider": CDN_PROVIDERS.get(r.domain, "") if is_cdn else "",
        }
        if profile:
            payload["profile"] = profile
        state.add_result(payload)
    return cb


def _run_tester(fn):
    with _tester_lock:
        return fn()


def _check_vpn() -> dict:
    result = {"vpn_active": False, "warp_installed": False, "details": ""}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$a=Get-NetAdapter -Name 'CloudflareWARP' -ErrorAction SilentlyContinue;"
             "$s=Get-Service 'CloudflareWARP' -ErrorAction SilentlyContinue;"
             "if($a){$as=$a.Status}else{$as='NotFound'};"
             "if($s){$ss=$s.Status}else{$ss='NotFound'};"
             "Write-Output ('ADAPTER='+$as); Write-Output ('SERVICE='+$ss)"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.startswith("ADAPTER="):
                status = line.split("=", 1)[1]
                if status == "Up":
                    result["vpn_active"] = True
                    result["details"] = "CloudflareWARP adapter is Up (активен)"
                elif status != "NotFound":
                    result["warp_installed"] = True
                    result["details"] = "WARP adapter найден, статус: " + status
            elif line.startswith("SERVICE="):
                status = line.split("=", 1)[1]
                if status != "NotFound":
                    result["warp_installed"] = True
                    if not result["details"]:
                        result["details"] = "WARP service найден (" + status + "), адаптер неактивен"
        if result["vpn_active"]:
            result["warp_installed"] = True
    except Exception:
        pass
    return result


def _kill_never_hang(image_names: list[str]) -> None:
    for name in image_names:
        _run_with_timeout_quiet(["taskkill", "/F", "/IM", name], timeout=6.0)


def _restore_protection_after_naked(z2_was: bool, z1_was: bool, state) -> str:
    """Restart the protection that was active before the naked test.

    The naked test kills winws/winws2 — leaving the user silently
    unprotected afterwards was a long-standing footgun.  Best effort:
    failures are reported, never raised.
    """
    try:
        if z2_was:
            cfg = get_config_manager().load()
            profile = cfg.last_profile or DEFAULT_PROFILE
            state.set_progress(99, f"Восстанавливаем Zapret 2 ({profile})...")
            ok, msg = get_controller().start(
                profile,
                game_filter_mode=cfg.game_filter_mode,
                discord_voice=cfg.discord_voice,
                winws2_debug=cfg.winws2_debug,
                autohostlist=cfg.autohostlist,
                ipset_catchall=cfg.ipset_catchall,
            )
            return (f"Zapret 2 восстановлен (пресет {profile})" if ok
                    else f"Не удалось восстановить Zapret 2: {msg}")
        if z1_was:
            cfg = get_config_manager().load()
            strat = cfg.zapret1_last_strategy
            if cfg.zapret1_dir and strat:
                bat = Path(cfg.zapret1_dir) / f"{strat}.bat"
                if bat.exists():
                    state.set_progress(99, f"Восстанавливаем Zapret 1 ({strat})...")
                    subprocess.Popen([str(bat)], cwd=str(bat.parent),
                                     creationflags=subprocess.CREATE_NO_WINDOW)
                    return f"Zapret 1 восстановлен ({strat})"
            return "Zapret 1 не восстановлен (стратегия не настроена)"
    except Exception:
        pass
    return ""


def _run_with_timeout(args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
            encoding="oem",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise


def _run_with_timeout_quiet(args: list[str], timeout: float = 5.0) -> None:
    try:
        _run_with_timeout(args, timeout)
    except Exception:
        pass


def _scan_winws_exe() -> dict:
    pid = 0
    try:
        r = _run_with_timeout(
            ["tasklist", "/FI", "IMAGENAME eq winws.exe", "/FO", "CSV", "/NH"],
            timeout=6.0,
        )
        for line in r.stdout.splitlines():
            parts = [p.strip(' "') for p in line.split(",")]
            if len(parts) >= 2 and parts[0].lower() == "winws.exe":
                pid = int(parts[1])
                break
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"running": bool(pid), "pid": pid}


# ── Tester action runner (background thread) ─────────────────

# Hosts the user cares about most — shown prominently in the final verdict.
KEY_HOST_LABELS: list[tuple[str, str]] = [
    ("discord.com", "Discord"),
    ("gateway.discord.gg", "Discord (шлюз)"),
    ("www.youtube.com", "YouTube"),
    ("i.ytimg.com", "YouTube CDN"),
]


def _build_recommendation(all_results, naked, sanity: dict) -> dict:
    """Build the final verdict: best strategy by network rate, key-host
    status (Discord/YouTube), and diagnosis when nothing works."""
    if not all_results:
        return {"verdict": "no_data", "message": "Нет результатов тестов", "best_profile": ""}

    best = max(all_results, key=lambda r: (r.network_rate, r.ok_count))
    blocked = sorted({r.domain for res in all_results for r in res.results
                      if r.test_type != "ping" and r.status != "OK"})
    net_rate = best.network_rate
    blocked_set = set(blocked)

    same_as_naked = False
    if naked is not None and naked.results:
        naked_ok = {r.domain for r in naked.results if r.status == "OK"}
        prof_ok = {r.domain for r in best.results
                   if r.test_type != "ping" and r.status == "OK"
                   and r.domain in NAKED_BASELINE_HOSTS}
        same_as_naked = (naked_ok == prof_ok)

    dry = sanity.get("dry_run", {})
    profiles_loaded = dry.get("profiles_loaded")
    engine_broken = (not dry.get("ok", True)
                     or (profiles_loaded is not None and profiles_loaded <= 1))
    misses = [c for c in sanity.get("list_coverage", []) if not c.get("covered")]

    # YouTube over TCP fails on every tested setup due to a known TLS quirk
    # (§17) — the browser reaches it via QUIC, so it is not a real outage.
    # Verdicts are computed ONLY from the complete per-profile results
    # (all domain tests finished), never from streaming rows — no async race.
    youtube_tcp_quirk = blocked_set <= {"www.youtube.com", "redirector.googlevideo.com",
                                        "i.ytimg.com", "youtu.be"}

    # "YouTube works" inference: TCP page blocked, but the YouTube infra
    # (i.ytimg.com thumbnails / youtu.be) is reachable through TLS on the
    # SAME profile run.  On every working setup i.ytimg.com passed; on
    # "nothing got through" setups it is blocked as well.
    yt_tcp_blocked = any(r.domain == "www.youtube.com" and r.test_type != "ping" and r.status != "OK"
                         for r in best.results)
    yt_infra_ok = any(r.domain in ("i.ytimg.com", "youtu.be") and r.test_type != "ping" and r.status == "OK"
                      for r in best.results)
    youtube_quirk_ok = yt_tcp_blocked and yt_infra_ok

    if engine_broken:
        verdict = "engine_broken"
        if profiles_loaded is not None and profiles_loaded <= 1:
            message = (f"⚠ winws2 загрузил только {profiles_loaded} профиль(-я) вместо ожидаемых 4-7 — "
                       "сигнатура старого бага с короткими путями (@lua/@blobs). "
                       "Результаты стратегий недостоверны. Обновите программу и повторите тест.")
        else:
            message = ("⚠ winws2 --dry-run отклонил аргументы: "
                       + ("; ".join(dry.get("errors", [])) or "неизвестная ошибка")
                       + ". Результаты стратегий недостоверны.")
    elif misses:
        verdict = "no_bypass"
        doms = ", ".join(c["domain"] for c in misses)
        message = (f"❌ Не пробито: {doms}. Эти домены отсутствуют в списках пресета — "
                   "стратегия к ним не применяется (no_action). Добавьте домены в списки и повторите тест.")
    elif same_as_naked and net_rate < 100:
        verdict = "no_bypass"
        message = ("❌ Все стратегии дали тот же результат, что и голый тест (без защиты). "
                   "Обход не применяется: либо winws2 не перехватывает трафик "
                   "(WinDivert/драйвер, антивирус, Killer NIC), либо DPI блокирует любые попытки. "
                   "Запустите «Диагностику» и сохраните отчёт.")
    elif net_rate >= 100 or (youtube_tcp_quirk and net_rate >= 60):
        verdict = "ok"
        extra = (" YouTube по TCP не доходит — известный TLS-прикол: в браузере "
                 "YouTube работает через QUIC." if youtube_tcp_quirk else "")
        message = f"✅ Лучшая стратегия: {best.profile_name} — {best.net_ok_count}/{best.net_total} доступно.{extra}"
    elif net_rate > 0:
        verdict = "partial"
        message = (f"⚠ Лучшая стратегия: {best.profile_name} — {best.net_ok_count}/{best.net_total} "
                   f"({net_rate:.0f}%). Не пробито: {', '.join(blocked) or '—'}")
    else:
        verdict = "no_bypass"
        message = "❌ Ни одна стратегия не пробила блокировку."

    key_hosts = []
    for domain, label in KEY_HOST_LABELS:
        trs = [r for r in best.results if r.test_type != "ping" and r.domain == domain]
        if trs:
            tr = min(trs, key=lambda r: r.time_ms or 0)
            status = tr.status
            note = ""
            # YouTube TCP is a known false negative — mark it working via QUIC
            # only when the inference holds on the FULL results of this profile.
            if domain == "www.youtube.com" and status != "OK" and youtube_quirk_ok:
                status = "QUIC_OK"
                note = "TCP-проверка неприменима — работает через QUIC"
            key_hosts.append({"domain": domain, "label": label,
                              "status": status, "time_ms": tr.time_ms, "note": note})
        else:
            key_hosts.append({"domain": domain, "label": label,
                              "status": "N/A", "time_ms": 0, "note": ""})

    return {
        "verdict": verdict,
        "message": message,
        "best_profile": best.profile_name,
        "best_network_rate": net_rate,
        "best_ok": best.net_ok_count,
        "best_total": best.net_total,
        "same_as_naked": same_as_naked,
        "blocked_domains": blocked,
        "key_hosts": key_hosts,
        "naked_network_rate": naked.network_rate if naked else None,
        "provider_hop": best.provider_hop,
        "provider_ip": best.provider_ip,
    }


def _run_tester_action(data: dict) -> None:
    action = data.get("action", "")
    state = _tester_state
    with state.lock:
        state.running = True
        state.reset()
        state.action_type = action

    tester = get_tester()
    logger = None

    try:
        if action in ("test", "test_profiles", "current", "naked",
                       "check-winws", "check_vpn", "full_analysis"):

            # short synchronous checks
            if action == "check-winws":
                info = _scan_winws_exe()
                state.set_final({"type": "check_result", "running": info["running"]})
                state.running = False
                return

            if action == "check_vpn":
                result = _check_vpn()
                state.set_final({"type": "vpn_result", **result})
                state.running = False
                return

            # actions that need a logger
            mode_map = {
                "test":         "test",
                "test_profiles":"quick",
                "current":      "current",
                "naked":        "naked",
                "full_analysis":"full",
            }
            mode = mode_map.get(action, "test")
            logger = TestLogger(get_root_dir(), mode=mode)
            tester.set_logger(logger)

            progress = _make_progress_cb(state)
            result_cb = _make_result_cb(state)

            if action == "test":
                result = _run_tester(lambda: tester.test_profile(
                    data.get("profile", DEFAULT_PROFILE), progress,
                    tier=data.get("tier", "critical"), result_cb=result_cb,
                    skip_cdn=data.get("skip_cdn", False),
                ))
                state.set_final(_serialize_result(result))

            elif action == "test_profiles":
                profiles = data.get("profiles", None)
                if not profiles:
                    presets_dir = get_root_dir() / "presets"
                    profiles = sorted(f.stem for f in presets_dir.glob("*.txt")) if presets_dir.is_dir() else ["default"]

                all_results = []
                total = len(profiles)
                _tier = data.get("tier", "critical")
                skip_cdn = data.get("skip_cdn", False)

                # Naked baseline first: detects "strategies do nothing" cases.
                naked_baseline = _run_tester(lambda: tester.run_naked_baseline(
                    _make_progress_cb(state),
                    result_cb=_make_result_cb(state, profile="__naked__"),
                ))
                if naked_baseline is not None:
                    progress(5, f"Голый тест: {naked_baseline.net_ok_count}/{naked_baseline.net_total} доступно")

                for idx, profile_name in enumerate(profiles):
                    if tester.shutdown_event.is_set():
                        break
                    base_pct = 6 + int(idx / total * 94)
                    progress(base_pct, f"Тестируем стратегию {profile_name} ({idx + 1}/{total})...")

                    def _inner_progress(pct: int, msg: str):
                        overall = int(6 + (idx + pct / 100) / total * 94)
                        progress(overall, msg)

                    res = _run_tester(
                        lambda pn=profile_name: tester.test_profile(
                            pn, _inner_progress, tier=_tier,
                            result_cb=result_cb, skip_cdn=skip_cdn)
                    )
                    all_results.append(res)
                    progress(int(6 + (idx + 1) / total * 94),
                             f"Стратегия {profile_name}: {res.success_rate:.0f}%")
                if all_results:
                    best = max(all_results, key=lambda r: (r.network_rate, r.ok_count))
                    blocked = sorted({r.domain for res in all_results for r in res.results
                                      if r.test_type != "ping" and r.status != "OK"})
                    sanity = tester.collect_sanity_info(best.profile_name, blocked)
                    rec = _build_recommendation(all_results, naked_baseline, sanity)
                    final = _serialize_result(best)
                    final["recommendation"] = rec
                    final["sanity"] = sanity
                    final["naked"] = _serialize_result(naked_baseline) if naked_baseline else None
                    state.set_final(final, [_serialize_result(r) for r in all_results])
                else:
                    state.running = False

            elif action == "current":
                winws_info = _scan_winws_exe()
                if not winws_info["running"]:
                    state.set_final({"type": "need_zapret1"})
                    state.running = False
                    return

                state.set_progress(0, "Zapret 1 обнаружен. Тестирование...")
                cur_progress = _make_progress_cb(state)
                cur_result_cb = _make_result_cb(state, profile="__current__")
                cur_result = _run_tester(
                    lambda: tester.test_current_setup(
                        cur_progress, tier=data.get("tier", "critical"),
                        result_cb=cur_result_cb,
                        skip_cdn=data.get("skip_cdn", False))
                )
                state.set_final({
                    "type": "current_result",
                    **_serialize_result(cur_result),
                })

            elif action == "naked":
                # Remember what protected the user so we can restore it after
                z2_was_running = get_controller().status().running
                z1_was_running = _scan_winws_exe()["running"]
                state.set_progress(1, "Останавливаем zapret...")
                _kill_never_hang(["winws.exe", "winws2.exe"])
                state.set_progress(3, "Защита остановлена. Запуск голого теста...")
                naked_result = _run_tester(
                    lambda: tester.test_naked(
                        _make_progress_cb(state), tier=data.get("tier", "critical"),
                        result_cb=result_cb, skip_cdn=data.get("skip_cdn", False))
                )
                restore_note = _restore_protection_after_naked(
                    z2_was_running, z1_was_running, state)
                final = {"type": "naked_result", **_serialize_result(naked_result)}
                if restore_note:
                    final["restored"] = restore_note
                state.set_final(final)

            elif action == "full_analysis":
                profiles = data.get("profiles", [DEFAULT_PROFILE])
                _kill_never_hang(["winws.exe", "winws2.exe"])
                time.sleep(0.5)

                from core.full_analyzer import run_full_analysis, AnalyzerEvent

                def _on_event(ev: AnalyzerEvent) -> None:
                    if ev.type == "skipped":
                        state.set_progress(0, f"Пропущено {ev.payload.get('count', 0)} blob-комбо ({ev.payload.get('reason', '')})")
                        return
                    with state.lock:
                        ev.payload["type"] = ev.type
                        if ev.type == "progress":
                            state.progress_pct = ev.payload.get("percent", 0)
                            state.progress_msg = ev.payload.get("message", "")
                        elif ev.type == "test_result":
                            state.results.append(ev.payload)
                        elif ev.type == "intermediate":
                            state.results.append(ev.payload)

                final_all = _run_tester(
                    lambda: run_full_analysis(tester, profiles, _tester_lock, on_event=_on_event),
                )
                
                # Reduce intermediate + progress noise from final poll
                with state.lock:
                    # Clear in-flight results (keep only test_result items)
                    state.results = [r for r in state.results
                                     if r.get("domain") and r.get("status")]
                    state.final_result = {"type": "final", "all_results": final_all}
                    state.all_results = final_all

    except Exception as e:
        with state.lock:
            state.error = str(e)
    finally:
        with state.lock:
            state.running = False
        if logger:
            logger.close()
            tester.set_logger(None)


# ── HTTP Handler ────────────────────────────────────────────

class ZapretHandler(BaseHTTPRequestHandler):

    # Silence default logging
    def log_message(self, fmt, *args):
        pass

    # ── Auth ──

    def _check_token(self) -> bool:
        if _app_token:
            token = self.headers.get("x-app-token", "")
            if token != _app_token:
                self._send_json({"detail": "Forbidden"}, HTTPStatus.FORBIDDEN)
                return False
        return True

    # ── JSON helpers ──

    def _send_json(self, obj: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        ext = path.suffix.lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parse_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # ── GET ──

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # Token check for /api/
        if path.startswith("/api/") and not self._check_token():
            return

        try:
            if path == "/":
                self._handle_index(params)
            elif path == "/api/config":
                self._handle_get_config()
            elif path == "/api/version":
                self._handle_version()
            elif path == "/api/status":
                self._handle_status()
            elif path == "/api/profiles":
                self._handle_list_profiles()
            elif path == "/api/exclude-list":
                self._handle_get_list("list-exclude-user.txt")
            elif path == "/api/include-list":
                self._handle_get_list("list-include-user.txt")
            elif path == "/api/ipset-exclude-list":
                self._handle_get_list("ipset-exclude.txt")
            elif path == "/api/service/status":
                self._handle_service_status()
            elif path == "/api/zapret1/strategies":
                self._handle_zapret1_strategies()
            elif path == "/api/default-profiles":
                self._handle_default_profiles()
            elif path == "/api/tester/status":
                self._handle_tester_status()
            else:
                self._handle_static(path)
        except RuntimeError as e:
            self._send_json({"status": "error", "message": str(e)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_index(self, params: dict) -> None:
        frontend = get_root_dir() / "frontend"
        index_path = frontend / "index.html"
        if index_path.exists():
            html = index_path.read_text(encoding="utf-8")
            token = params.get("token", [""])[0]
            html = html.replace("__APP_TOKEN__", token)
            self._send_html(html)
        else:
            self._send_html("<html><body><h1>Frontend not found</h1></body></html>")

    def _handle_get_config(self) -> None:
        cfg = get_config_manager().load()
        self._send_json({"status": "ok", "config": {
            "root_dir": cfg.root_dir,
            "theme": cfg.theme,
            "language": cfg.language,
            "service_name": cfg.service_name,
            "last_profile": cfg.last_profile,
            "zapret1_dir": cfg.zapret1_dir,
            "zapret1_last_strategy": cfg.zapret1_last_strategy,
            "game_filter_mode": cfg.game_filter_mode,
            "discord_voice": cfg.discord_voice,
            "winws2_debug": cfg.winws2_debug,
            "autohostlist": cfg.autohostlist,
            "ipset_catchall": cfg.ipset_catchall,
        }})

    def _handle_version(self) -> None:
        self._send_json({"status": "ok", "version": VERSION})

    def _handle_status(self) -> None:
        controller = get_controller()
        status = controller.status()
        zapret1 = _scan_winws_exe()
        presets_dir = get_root_dir() / "presets"
        profiles = []
        if presets_dir.is_dir():
            for f in sorted(presets_dir.glob("*.txt")):
                profiles.append(f.stem)
        self._send_json({
            "status": "ok",
            "zapret": {
                "running": status.running, "pid": status.pid,
                "strategy": status.strategy,
            },
            "zapret1": zapret1,
            "profiles": profiles,
        })

    def _handle_list_profiles(self) -> None:
        presets_dir = get_root_dir() / "presets"
        profiles = []
        if presets_dir.is_dir():
            for f in sorted(presets_dir.glob("*.txt")):
                profiles.append({"name": f.stem, "display_name": f.stem, "description": "", "is_valid": True, "parse_error": "", "warnings": []})
        self._send_json({"status": "ok", "profiles": profiles})

    def _handle_get_list(self, filename: str) -> None:
        path = get_root_dir() / "lists" / filename
        content = ""
        if path.exists():
            content = path.read_text(encoding="utf-8")
        self._send_json({"status": "ok", "content": content})

    def _handle_service_status(self) -> None:
        self._send_json({
            "status": "ok",
            "service": SERVICE_NAME,
            "installed": svc_installed(),
            "running": svc_status() == "running",
        })

    def _handle_tester_status(self) -> None:
        self._send_json(_tester_state.to_dict())

    def _handle_zapret1_strategies(self) -> None:
        cfg = get_config_manager().load()
        dir_path = cfg.zapret1_dir
        if not dir_path or not Path(dir_path).is_dir():
            self._send_json({"status": "ok", "strategies": []})
            return
        bats = []
        for f in sorted(Path(dir_path).glob("*.bat")):
            name = f.stem.lower()
            if name == "service": continue
            bats.append({"name": f.stem, "path": str(f)})
        self._send_json({"status": "ok", "strategies": bats})

    def _handle_default_profiles(self) -> None:
        presets_dir = get_root_dir() / "presets"
        profiles = sorted(f.stem for f in presets_dir.glob("*.txt")) if presets_dir.is_dir() else ["default"]
        self._send_json({"status": "ok", "profiles": profiles})

    def _handle_static(self, path: str) -> None:
        frontend = get_root_dir() / "frontend"
        # /static/... or direct paths like /css/..., /js/...
        rel = path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[7:]
        file_path = frontend / rel
        # Security: prevent path traversal
        try:
            file_path = file_path.resolve()
            frontend_resolved = frontend.resolve()
            if not str(file_path).startswith(str(frontend_resolved)):
                self._send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
                return
        except (ValueError, OSError):
            self._send_json({"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
            return
        self._send_file(file_path)

    # ── POST ──

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._check_token():
            return

        data = self._parse_body()

        try:
            if path == "/api/config":
                self._handle_save_config(data)
            elif path == "/api/zapret1/save-dir":
                self._handle_zapret1_save_dir(data)
            elif path == "/api/zapret1/start":
                self._handle_zapret1_start(data)
            elif path == "/api/zapret1/stop":
                self._handle_zapret1_stop()
            elif path == "/api/start":
                self._handle_start_zapret(data)
            elif path == "/api/stop":
                self._handle_stop_zapret()
            elif path == "/api/exclude-list":
                self._handle_save_list(data, "list-exclude-user.txt")
            elif path == "/api/include-list":
                self._handle_save_list(data, "list-include-user.txt")
            elif path == "/api/ipset-exclude-list":
                self._handle_save_list(data, "ipset-exclude.txt")
            elif path == "/api/service/install":
                self._handle_service_install(data)
            elif path == "/api/service/remove":
                self._handle_service_remove()
            elif path == "/api/service/start":
                self._handle_service_start()
            elif path == "/api/service/stop":
                self._handle_service_stop()
            elif path == "/api/diagnose":
                self._handle_diagnose()
            elif path == "/api/export-report":
                self._handle_export_report(data)
            elif path == "/api/collect-info":
                self._handle_collect_info()
            elif path == "/api/tester/action":
                self._handle_tester_action(data)
            else:
                self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except RuntimeError as e:
            self._send_json({"status": "error", "message": str(e)}, HTTPStatus.SERVICE_UNAVAILABLE)
        except Exception as e:
            self._send_json({"status": "error", "message": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_save_config(self, data: dict) -> None:
        cfg = get_config_manager().load()
        if "theme" in data: cfg.theme = data["theme"]
        if "language" in data: cfg.language = data["language"]
        if "last_profile" in data: cfg.last_profile = data["last_profile"]
        if "zapret1_dir" in data: cfg.zapret1_dir = data["zapret1_dir"]
        if "game_filter_mode" in data: cfg.game_filter_mode = data["game_filter_mode"]
        if "discord_voice" in data: cfg.discord_voice = bool(data["discord_voice"])
        if "winws2_debug" in data: cfg.winws2_debug = bool(data["winws2_debug"])
        if "autohostlist" in data: cfg.autohostlist = bool(data["autohostlist"])
        if "ipset_catchall" in data: cfg.ipset_catchall = bool(data["ipset_catchall"])
        ok = get_config_manager().save(cfg)
        self._send_json({"status": "ok" if ok else "error"})

    def _handle_zapret1_save_dir(self, data: dict) -> None:
        path = data.get("path", "").strip()
        if not path or not Path(path).is_dir():
            self._send_json({"status": "error", "message": "Укажите существующую папку Zapret 1"})
            return
        cfg = get_config_manager().load()
        cfg.zapret1_dir = path
        get_config_manager().save(cfg)
        self._send_json({"status": "ok", "message": "Путь сохранён"})

    def _handle_zapret1_start(self, data: dict) -> None:
        strategy = data.get("strategy", "").strip()
        if not strategy:
            self._send_json({"status": "error", "message": "Стратегия не указана"})
            return
        controller = get_controller()
        z2 = controller.status()
        if z2.running:
            self._send_json({"status": "error", "message": "Zapret 2 (winws2.exe) запущен. Остановите его перед запуском Zapret 1."})
            return
        cfg = get_config_manager().load()
        dir_path = cfg.zapret1_dir
        if not dir_path:
            self._send_json({"status": "error", "message": "Папка Zapret 1 не указана"})
            return
        bat_path = Path(dir_path) / f"{strategy}.bat"
        if not bat_path.exists():
            self._send_json({"status": "error", "message": f"Файл {strategy}.bat не найден"})
            return
        try:
            subprocess.Popen([str(bat_path)], cwd=str(bat_path.parent),
                             creationflags=subprocess.CREATE_NO_WINDOW)
            cfg.zapret1_last_strategy = strategy
            get_config_manager().save(cfg)
            self._send_json({"status": "ok", "message": f"Zapret 1 запущен: {strategy}.bat"})
        except OSError as e:
            self._send_json({"status": "error", "message": str(e)})

    def _handle_zapret1_stop(self) -> None:
        try:
            subprocess.run(["taskkill", "/F", "/IM", "winws.exe"],
                           capture_output=True, timeout=8,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            self._send_json({"status": "ok", "message": "Zapret 1 остановлен"})
        except (subprocess.TimeoutExpired, OSError) as e:
            self._send_json({"status": "error", "message": str(e)})

    def _handle_start_zapret(self, data: dict) -> None:
        z1 = _scan_winws_exe()
        if z1["running"]:
            self._send_json({"status": "error", "message": "Zapret 1 (winws.exe) запущен. Остановите его перед запуском Zapret 2."})
            return
        controller = get_controller()
        profile_name = data.get("profile", "")
        cfg = get_config_manager().load()
        ok, msg = controller.start(
            profile_name,
            game_filter_mode=cfg.game_filter_mode,
            discord_voice=cfg.discord_voice,
            winws2_debug=cfg.winws2_debug,
            autohostlist=cfg.autohostlist,
            ipset_catchall=cfg.ipset_catchall,
        )
        self._send_json({"status": "ok" if ok else "error", "message": msg})

    def _handle_stop_zapret(self) -> None:
        get_controller().stop()
        _kill_never_hang(["winws2.exe", "winws.exe"])
        self._send_json({"status": "ok", "message": "Все процессы zapret остановлены"})

    def _handle_save_list(self, data: dict, filename: str) -> None:
        content = data.get("content", "").strip()
        path = get_root_dir() / "lists" / filename
        try:
            path.write_text(content, encoding="utf-8")
            self._send_json({"status": "ok", "message": "Список сохранён"})
        except OSError as e:
            self._send_json({"status": "error", "message": str(e)})

    def _prepare_service_args(self, data: dict) -> tuple[Optional[list[str]], str]:
        """Build + validate the winws2 args for the service (direct-exe style).

        The service runs winws2.exe itself (like Zapret 1), so args are baked
        into binPath and refreshed on install/start — no cmd/bat wrapper.
        """
        cfg = get_config_manager().load()
        profile = data.get("profile") or cfg.last_profile or DEFAULT_PROFILE
        game_filter = data.get("game_filter") or cfg.game_filter_mode or "off"
        discord_voice = bool(data.get("discord_voice", cfg.discord_voice))
        debug = bool(data.get("debug", cfg.winws2_debug))
        autohostlist = bool(data.get("autohostlist", cfg.autohostlist))
        ipset_catchall = bool(data.get("ipset_catchall", cfg.ipset_catchall))
        root = get_root_dir()
        exe = get_controller().winws2_path
        if exe is None:
            return None, "winws2.exe не найден"
        preset = root / "presets" / f"{profile}.txt"
        if not preset.exists():
            return None, f"Пресет '{profile}.txt' не найден"
        args = build_args_from_preset(root, root / "lua", root / "blobs", preset, debug=debug,
                                       game_filter_mode=game_filter,
                                       discord_voice=discord_voice,
                                       autohostlist=autohostlist,
                                       ipset_catchall=ipset_catchall)
        ok, err = validate_args(exe, args, cwd=root)
        if not ok:
            return None, err
        return args, ""

    def _handle_service_install(self, data: dict) -> None:
        args, err = self._prepare_service_args(data)
        if err:
            self._send_json({"status": "error", "message": f"Установка отменена — {err}"})
            return
        ok, msg = svc_install(root_dir=get_root_dir(), args=args)
        self._send_json({"status": "ok" if ok else "error", "message": msg})

    def _handle_service_remove(self) -> None:
        ok, msg = svc_remove()
        self._send_json({"status": "ok" if ok else "error", "message": msg})

    def _handle_service_start(self) -> None:
        # Refresh binPath with the current args: direct-exe services bake
        # them in, a stale cmdline would silently run an old strategy.
        args, err = self._prepare_service_args({})
        if err:
            self._send_json({"status": "error", "message": f"Служба не запущена — {err}"})
            return
        ok, msg = svc_start(args)
        self._send_json({"status": "ok" if ok else "error", "message": msg})

    def _handle_service_stop(self) -> None:
        ok, msg = svc_stop()
        self._send_json({"status": "ok" if ok else "error", "message": msg})

    def _handle_diagnose(self) -> None:
        import time as _time
        from core.diagnostics import run_diagnostics, format_report_text
        start = _time.time()
        report = run_diagnostics(get_root_dir(), get_config_manager().load())
        report["elapsed_sec"] = round(_time.time() - start, 1)
        report["report_text"] = format_report_text(report)
        self._send_json({"status": "ok", "report": report})

    def _handle_update_check(self) -> None:
        global _update_check_cache
        if _update_check_cache is None:
            from core.updates import check_for_updates
            _update_check_cache = check_for_updates()
        self._send_json({"status": "ok", **_update_check_cache})

    def _handle_export_report(self, data: dict) -> None:
        consent = data.get("consent", False)
        city = data.get("city", "")
        isp = data.get("isp", "")
        vpn_active = data.get("vpn_active", False)
        zapret1_strategy = data.get("zapret1_strategy", "")
        zapret1_filename = data.get("zapret1_filename", "")
        zapret1_cmdline = data.get("zapret1_cmdline", "")
        phase0_results = data.get("phase0_results")
        phase1_results = data.get("phase1_results")
        phase2_results = data.get("phase2_results")
        mode = data.get("mode", "lite")
        root = get_root_dir()

        bat_path = None
        if zapret1_filename and zapret1_strategy:
            try:
                bat_bytes = base64.b64decode(zapret1_strategy)
                bat_path = root / zapret1_filename
                bat_path.write_bytes(bat_bytes)
                zapret1_strategy = str(bat_path)
            except Exception:
                pass

        ok, path_or_err = export_data_package(
            consent=consent, city=city, isp=isp,
            vpn_active=vpn_active,
            zapret1_strategy=zapret1_strategy,
            root_dir=root, result_dir=root,
            bat_path=bat_path,
            zapret1_cmdline=zapret1_cmdline,
            phase0_results=phase0_results,
            phase1_results=phase1_results,
            phase2_results=phase2_results,
            mode=mode,
        )
        if bat_path and bat_path.exists():
            try:
                bat_path.unlink()
            except OSError:
                pass
        if ok:
            _play_completion_sound()
            self._send_json({"status": "ok", "file": path_or_err})
        else:
            self._send_json({"status": "error", "message": path_or_err})

    def _handle_collect_info(self) -> None:
        self._send_json({"status": "ok", "data": collect_all()})

    def _handle_tester_action(self, data: dict) -> None:
        action = data.get("action", "")
        if action == "cancel":
            get_tester().signal_shutdown()
            with _tester_state.lock:
                _tester_state.cancelled = True
            self._send_json({"status": "ok", "action": "cancelled"})
            return
        t = threading.Thread(target=_run_tester_action, args=(data,), daemon=True)
        t.start()
        self._send_json({"status": "ok", "action": "started"})


# ── Server lifecycle ────────────────────────────────────────

class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread,
                             args=(request, client_address), daemon=True)
        t.start()

    def process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def create_server(host: str, port: int) -> ThreadedHTTPServer:
    global _server
    srv = ThreadedHTTPServer((host, port), ZapretHandler)
    _server = srv
    return srv


def stop_server() -> None:
    global _server
    if _server:
        _server.shutdown()
        _server = None
