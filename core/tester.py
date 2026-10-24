from __future__ import annotations

import ipaddress
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.test_logger import TestLogger

from core.launcher import build_args_from_preset, launch_winws2
from core.status import FAIL_STATUSES
from core import tester_probes, tester_proc, tester_scoring, timeouts
# Ре-экспорт статических определений (аудит #5): внешние модули исторически
# импортируют их из core.tester; probes/proc/scoring берут напрямую из defs.
from core.tester_defs import (  # noqa: F401
    BROWSER_HEADERS, BROWSER_USER_AGENT, CDN_HOSTS, CDN_PROVIDERS,
    CONTROL_DOMAINS, CONTROL_HOSTS, H3_WALL_DEADLINE, HOST_TEST,
    NAKED_BASELINE_HOSTS, PING_HOSTS, QUIC_QUIRK_DOMAINS, RATED_HOSTS,
    TCP1620_BODY, TEST_HOSTS, WINDIVERT_CLEANUP_DELAY,
    CdnScanResult, CdnScanVerdict, ProfileTestResult, TestResult, _TestAbort,
    is_control,
)


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
        # TTL-проба кэшируется: позиция хопа провайдера не меняется между
        # профилями одной сессии - tracert гоняем один раз.
        self._ttl_cache: Optional[dict] = None
        self._ipset_net_cache: Optional[list] = None

    def set_logger(self, logger: Optional["TestLogger"]) -> None:
        self._logger = logger

    def _ipset_networks(self) -> list:
        """CIDR-сети из ipset-all.txt.gz (кэш на инстанс) - для проверки
        «IP кандидата уже десинкается ipset-режимом» (нет наложений)."""
        if self._ipset_net_cache is None:
            self._ipset_net_cache = tester_probes.ipset_networks(self.root_dir)
        return self._ipset_net_cache

    def _ensure_winws2_dead(self) -> None:
        # Path-фильтр (ревью 18.10): blanket kill не должен трогать движок
        # второй копии GUI, установленной в другой каталог.
        tester_proc.ensure_winws2_dead(
            self._kill_managed,
            allowed_paths={str(self.bin_dir / "winws2.exe"),
                           str(self.root_dir / "winws2.exe")})

    def _foreign_engine_error(self) -> str:
        """Ошибка, если после наших path-фильтрованных kill'ов остался
        ЧУЖОЙ winws2 (lite/другая копия GUI): убивать его мы не вправе, но
        и мерить с ним нельзя - два фильтра WinDivert исказят результат
        (parity lite/GUI, 18.10)."""
        try:
            if tester_proc.any_winws2_running():
                return ("другой winws2 уже запущен (lite или копия GUI из "
                        "другой папки) - остановите его и повторите")
        except Exception:
            pass
        return ""

    def _kill_managed(self) -> bool:
        proc = self._process
        self._process = None
        return tester_proc.kill_managed(proc)

    def _any_winws_running(self) -> bool:
        return tester_proc.any_winws_running()

    def _any_winws2_running(self) -> bool:
        return tester_proc.any_winws2_running()

    def _run_profile(self, profile_name: str, ipset_catchall: bool = False,
                     fake_blob: str = "", discord_alt: bool = False,
                     ipset_include_file: Optional[Path] = None) -> bool:
        exe_path = self.bin_dir / "winws2.exe"
        if not exe_path.exists():
            exe_path = self.root_dir / "winws2.exe"
        if not exe_path.exists():
            return False

        preset = self.root_dir / "presets" / f"{profile_name}.txt"
        if not preset.exists():
            return False

        tester_proc.wait_windivert_free()

        args = build_args_from_preset(self.root_dir, self.lua_dir, self.blobs_dir, preset,
                                      ipset_catchall=ipset_catchall, fake_blob=fake_blob,
                                      discord_alt=discord_alt,
                                      ipset_include_file=ipset_include_file)
        # ts-fooling-стратегии требуют включённых timestamps в ОС: без этого
        # тест ложно валится, если служба ни разу не запускалась (кэш внутри).
        try:
            from core.tcp_timestamps import enable_for_engine
            enable_for_engine()
        except Exception:
            pass
        ok, proc = launch_winws2(self.root_dir, exe_path, args, timeout=5.0)
        # Управляемый экземпляр (ревью-раунд 3, P1-1): держим Popen-хэндл -
        # остановка идёт PID-таргетингом с ожиданием выхода, а не blanket
        # kill по имени; bat-фолбэк даёт proc=None (unmanaged).
        self._process = proc if ok else None
        return ok

    def _run_domain_tests(self, domains: list[str], concurrency: int = 5, http_only: bool = False, result_cb=None, expand_www: bool = False, progress_cb=None) -> list[TestResult]:
        return tester_probes.run_domain_tests(
            domains, concurrency=concurrency, http_only=http_only,
            result_cb=result_cb, expand_www=expand_www,
            progress_cb=progress_cb, timeout=self.timeout)

    # ── TTL-проба ──────────────────────────────────────────────────
    # Traceroute до первого хопа вне локальной сети - вероятный DPI-бокс
    # провайдера; результат в ProfileTestResult для autottl-оптимизации.

    def _probe_provider_ttl(self) -> dict:
        """tracert до google.com: первый не-приватный хоп (hop, ip, target).
        hop=0 при неудаче; результат кэшируется на инстанс (см. __init__)."""
        if self._ttl_cache is None:
            self._ttl_cache = tester_probes.probe_provider_ttl()
        return self._ttl_cache

    def _get_tier_hosts(self, tier: str) -> list[str]:
        """Хосты прогона. tier («smoke»/«critical»/«full») сейчас НЕ влияет:
        все режимы гоняют полный TEST_HOSTS - так сравнение профилей честнее
        (одинаковая батарея). Имя параметра - историческое (аудит 2026-10)."""
        return list(TEST_HOSTS)

    def _setup_profile(self, profile: str, progress_cb, _logged_progress, ipset_catchall: bool = False, discord_alt: bool = False, ipset_include_file: Optional[Path] = None) -> tuple[str, str, str, float]:
        """Запустить winws2 для пресета, измерить RTT, пробить хоп ТСПУ.
        Возвращает (profile_name, provider_hop, provider_ip, timeout);
        при сбое запуска - raise _TestAbort с результатом-ошибкой."""
        profile_name = profile
        preset = self.root_dir / "presets" / f"{profile_name}.txt"
        if not preset.exists():
            raise _TestAbort(ProfileTestResult(profile_name=profile_name, results=[
                TestResult(profile_name, "process", "ERROR", error=f"Preset not found: {preset}"),
            ]))

        if self._logger:
            self._logger.progress(profile_name, "START")

        _logged_progress(5, f"[{profile_name}] запуск winws2...")
        if not self._run_profile(profile_name, ipset_catchall,
                                 discord_alt=discord_alt,
                                 ipset_include_file=ipset_include_file):
            # диагностика «у друга не запускается»: точные пути в лог сессии
            if self._logger:
                from core.launcher import _read_stderr_sink
                sink = _read_stderr_sink(self.root_dir)
                if sink:
                    self._logger.progress(profile_name,
                                          f"winws2 output: {sink[:600]}")
                self._logger.progress(
                    profile_name,
                    f"ABORT: spawn failed | exe={self.bin_dir / 'winws2.exe'} "
                    f"exists={self.bin_dir.joinpath('winws2.exe').exists()} | "
                    f"preset={preset} exists={preset.exists()}")
            raise _TestAbort(ProfileTestResult(profile_name=profile_name, results=[
                TestResult(profile_name, "process", "ERROR", error="winws2 not found or spawn failed"),
            ]))

        _logged_progress(7, f"[{profile_name}] ждём готовность WinDivert (1.5s)...")
        # launch_winws2 уже подтвердил жизнь процесса (direct, bat - фолбэк);
        # WinDivert открывает хендл за сотни мс - 1.5s хватает.
        time.sleep(timeouts.SETTLE_WINWS2)

        if not self._any_winws2_running():
            self._ensure_winws2_dead()
            if self._logger:
                from core.launcher import _read_stderr_sink
                sink = _read_stderr_sink(self.root_dir)
                if sink:
                    self._logger.progress(profile_name,
                                          f"winws2 output: {sink[:600]}")
                self._logger.progress(
                    profile_name,
                    "ABORT: winws2 died immediately after spawn "
                    "(WinDivert conflict / AV / driver refused)")
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

    def _build_result(self, profile_name, all_results, provider_hop, provider_ip, tier, _logged_progress):
        return tester_scoring.build_result(
            profile_name, all_results, provider_hop, provider_ip, tier,
            _logged_progress, kill_fn=self._ensure_winws2_dead,
            logger=self._logger)

    def test_profile(
        self,
        profile: str,
        progress_cb: Callable[[int, str], None],
        tier: str = "critical",
        result_cb: Optional[Callable[[TestResult], None]] = None,
        ipset_catchall: bool = False,
        discord_alt: bool = False,
    ) -> ProfileTestResult:
        self._ensure_winws2_dead()

        def _logged_progress(pct: int, msg: str) -> None:
            if self._logger:
                self._logger.progress(profile, msg)
            progress_cb(pct, msg)

        # _setup_profile бросает _TestAbort ДО try ниже (нет пресета, winws2
        # не стартует). Один битый профиль не должен валить весь свеп - его
        # ошибка возвращается, вызывающий продолжает.
        try:
            _foreign = self._foreign_engine_error()
            if _foreign:
                raise _TestAbort(ProfileTestResult(
                    profile_name=profile,
                    results=[TestResult(profile, "process", "ERROR",
                                        error=_foreign)]))
            profile_name, provider_hop, provider_ip, _ = self._setup_profile(
                profile, progress_cb, _logged_progress, ipset_catchall,
                discord_alt=discord_alt)
        except _TestAbort as e:
            # Диагностика «не запускается у пользователя»: причина аборт
            # пишется в test_session.log (попадает в ZIP-отчёт)
            err_r = e.result or ProfileTestResult(profile_name=profile)
            detail = "; ".join(
                (getattr(r, "error", "") or "") for r in (err_r.results or [])) \
                if err_r.results else "abort"
            if self._logger:
                self._logger.progress(
                    profile,
                    f"ABORT: {detail} | exe={self.bin_dir / 'winws2.exe'} | "
                    f"preset={self.root_dir / 'presets' / (profile + '.txt')}")
            return e.result if e.result is not None else err_r

        domains = self._get_tier_hosts(tier)
        all_results: list[TestResult] = []

        try:
            _logged_progress(15, f"Тест {len(domains)} доменов...")

            if self.shutdown_event.is_set():
                raise _TestAbort(ProfileTestResult(profile_name=profile_name))

            def _on_curl_progress(done_curl, total_curl):
                pct = 15 + int(done_curl * 40 / total_curl)
                progress_cb(pct, f"curl-тест {done_curl}/{total_curl}")

            for r in self._run_domain_tests(domains, concurrency=8, expand_www=True, result_cb=result_cb, progress_cb=_on_curl_progress):
                if self.shutdown_event.is_set():
                    raise _TestAbort(ProfileTestResult(profile_name=profile_name))
                all_results.append(r)

            # Пинг-фаза считается отдельно: tests_done включал curl-результаты,
            # бар прыгал с 55% сразу на ~88%. Пинги только на DNS-канарейках (IP);
            # доменные убраны 2026-09-13 - «сеть жива».
            ping_total = len(PING_HOSTS)
            ping_done = 0

            for host in PING_HOSTS:
                if self.shutdown_event.is_set(): break
                all_results.append(tester_probes.ping_test(host, self.timeout))
                if result_cb: result_cb(all_results[-1])
                ping_done += 1
                progress_cb(55 + int(ping_done * 20 / ping_total), f"ping {host}")

            return self._build_result(profile_name, all_results, provider_hop, provider_ip, tier, _logged_progress)

        except _TestAbort as e:
            # Отмена/сбой посреди прогона: winws2 с параметрами пресета может
            # остаться жив и перехватывать трафик - гасим обязательно.
            try:
                self._ensure_winws2_dead()
            except Exception:
                pass
            return e.result if e.result is not None else self._build_result(profile_name, all_results, provider_hop, provider_ip, tier, _logged_progress)

    def scan_cdn_recommendations(self, progress_cb, result_cb=None, naked_check: bool = True,
                                 ipset_mode: bool = False, ab_ipset: bool = True,
                                 profile_name: str = "default") -> CdnScanResult:
        """CDN-стабилизация: вердикты по CDN-хостам для полу-автономного ведения списков.

        Три фазы: (1) CDN-батарея (Alive + TCP16-20) под защитой; (2) для
        мёртвых - naked-перепроверка «мёртв» vs «десинк ломает»; (3) для
        живых+режущихся - верификация десинком (пробный список, fake+multisplit):
        вылечился → fix, режется/умер → hard (не лечится, не трогать).

        ipset_mode=True - защита через ipset-all: fix-кандидат проверяется на
        ПОКРЫТИЕ (все IP в ipset-all → covered; иначе fix с резолвнутыми IP для
        ipset-include-user). При naked_done=True вызывающий обязан восстановить
        защиту (флаги z2_was/z1_was)."""
        result = CdnScanResult(ipset_mode=ipset_mode)
        try:
            if not self._any_winws2_running():
                result.error = "winws2 не запущен - запустите защиту перед сканированием"
                return result
            progress_cb(5, "Проверка CDN-хостов под защитой...")
            protected = self._run_domain_tests(CDN_HOSTS, concurrency=15, http_only=True, result_cb=result_cb)
            if self.shutdown_event.is_set():
                return result
            alive = [r.domain for r in protected if r.status == "OK"]
            dpi_map: dict[str, str] = {}
            if alive:
                progress_cb(25, "Проверка stateful DPI (TCP 16-20)...")
                for r in tester_probes.run_tcp1620_tests(self.root_dir, alive, timeout=self.timeout):
                    dpi_map[r.domain] = "DET" if r.status == "TCP16_20" else "ok"
            # ── A/B: второй прогон в противоположном режиме ipset ──
            # Включение/выключение IP-обхода меняет картину «пробило/сломало»:
            # ipset-all чинит одних и ломает других - один прогон этого не
            # видит. Сканер сам перезапускает защиту - вызывающий обязан её
            # восстановить (protection_touched).
            alive2_map: dict[str, bool] = {}
            det2_map: dict[str, str] = {}
            if ab_ipset and not self.shutdown_event.is_set():
                result.z2_was = result.z2_was or self._any_winws2_running()
                result.z1_was = result.z1_was or self._any_winws_running()
                result.protection_touched = True
                mode2 = "IP-обход ВКЛ" if not ipset_mode else "IP-обход ВЫКЛ"
                progress_cb(30, f"A/B-прогон: {mode2}...")
                self._ensure_winws2_dead()
                if self._run_profile(profile_name, ipset_catchall=not ipset_mode)                         and self._any_winws2_running():
                    result.ab_done = True
                    battery2 = self._run_domain_tests(CDN_HOSTS, concurrency=15,
                                                      http_only=True, result_cb=result_cb)
                    for r in battery2:
                        alive2_map[r.domain] = (r.status == "OK")
                    alive2 = [r.domain for r in battery2 if r.status == "OK"]
                    if alive2 and not self.shutdown_event.is_set():
                        progress_cb(42, "Проверка stateful DPI во втором прогоне...")
                        for r in tester_probes.run_tcp1620_tests(self.root_dir, alive2, timeout=self.timeout):
                            det2_map[r.domain] = "DET" if r.status == "TCP16_20" else "ok"
                else:
                    progress_cb(48, "A/B-прогон не состоялся (пресет не стартовал)")
                self._ensure_winws2_dead()
            # мёртвые в первом прогоне: naked-перепроверка нужна только тем,
            # кого A/B не спас (во втором прогоне они тоже мертвы)
            dead = [r.domain for r in protected
                    if r.status != "OK" and alive2_map.get(r.domain) is not True]
            naked_map: dict[str, str] = {}
            if naked_check and dead:
                result.z2_was = result.z2_was or self._any_winws2_running()
                result.z1_was = result.z1_was or self._any_winws_running()
                progress_cb(52, "Перепроверка мёртвых хостов без защиты...")
                self._ensure_winws2_dead()
                result.naked_done = True
                for r in self._run_domain_tests(dead, concurrency=8, http_only=True, result_cb=result_cb):
                    naked_map[r.domain] = "A" if r.status == "OK" else "x"
            candidates = [d for d in alive if dpi_map.get(d) == "DET"]
            verify_map: dict[str, str] = {}
            if candidates and not self.shutdown_event.is_set():
                if not result.naked_done:
                    result.z2_was = self._any_winws2_running()
                    result.z1_was = self._any_winws_running()
                progress_cb(60, "Верификация кандидатов десинком (пробный список)...")
                if ipset_mode:
                    verify_map = self._verify_with_ipset(candidates, result_cb)
                else:
                    verify_map = self._verify_with_desync(candidates, result_cb,
                                                          ipset_catchall=ipset_mode)
                # верификация ВСЕГДА снимает защиту (finally в verify-функциях),
                # даже если пробный прогон не состоялся - рестор обязателен
                result.naked_done = True
            # покрытие ipset-all для fix-кандидатов (только ipset-режим)
            ip_map: dict[str, list[str]] = {}
            cover_map: dict[str, bool] = {}
            if ipset_mode:
                nets = self._ipset_networks()
                fix_domains = [d for d in verify_map if verify_map[d] == "fix"]
                for d in fix_domains:
                    ips = tester_probes.resolve_ips(d)
                    ip_map[d] = ips
                    cover_map[d] = bool(ips) and all(
                        any(ipaddress.ip_address(ip) in n for n in nets) for ip in ips)
            progress_cb(90, "Сборка вердиктов...")
            ab_fixed = ab_broken = 0
            for r in protected:
                dpi = dpi_map.get(r.domain, "-")
                naked = naked_map.get(r.domain, "-")
                verdict = ""
                if r.status == "OK":
                    if dpi == "DET":
                        verdict = verify_map.get(r.domain, "unknown")
                        if verdict == "fix" and cover_map.get(r.domain):
                            verdict = "covered"
                    else:
                        verdict = "ok"
                elif naked == "A":
                    verdict = "break"
                elif naked == "x":
                    verdict = "dead"
                else:
                    verdict = "unknown"
                # Эффект IP-обхода (A/B-прогоны): жив в hostlist и мёртв в ipset
                # → ломает; мёртв в hostlist и жив в ipset → чинит.
                ipset_eff = "-"
                if result.ab_done:
                    a1 = (r.status == "OK")
                    a2 = alive2_map.get(r.domain)
                    if a2 is not None:
                        hostlist_alive = a1 if not ipset_mode else a2
                        ipset_alive = a2 if not ipset_mode else a1
                        if hostlist_alive and not ipset_alive:
                            ipset_eff = "ломает"
                            ab_broken += 1
                        elif not hostlist_alive and ipset_alive:
                            ipset_eff = "чинит"
                            ab_fixed += 1
                result.verdicts.append(CdnScanVerdict(
                    domain=r.domain,
                    provider=CDN_PROVIDERS.get(r.domain, "-"),
                    alive="A" if r.status == "OK" else "x",
                    dpi=dpi, naked=naked, verdict=verdict,
                    ips=ip_map.get(r.domain, []),
                    covered=cover_map.get(r.domain, False),
                    ipset=ipset_eff,
                ))
            result.ab_fixed, result.ab_broken = ab_fixed, ab_broken
            # IP для точечных действий по A/B-эффекту: «чинит» → ipset-включения,
            # «ломает» → ipset-исключения (действия IP-based, домен не поможет).
            need_ips = [v.domain for v in result.verdicts if v.ipset in ("чинит", "ломает")]
            if need_ips and not self.shutdown_event.is_set():
                progress_cb(95, f"Резолв IP для точечных действий ({len(need_ips)})...")
                ip_by_domain = {d: tester_probes.resolve_ips(d) for d in need_ips}
                for v in result.verdicts:
                    if v.ipset in ("чинит", "ломает"):
                        v.ips = ip_by_domain.get(v.domain, [])
            progress_cb(100, "Готово")
        except _TestAbort as e:
            if e.result is not None and getattr(e.result, "error", None):
                result.error = str(e.result.error)
            else:
                result.error = "прервано"
        return result

    # Короткая батарея для подбора блоба: ключевые сервисы, ~10-15 с на блоб.
    BLOB_PROBE_HOSTS = [
        "discord.com", "www.youtube.com", "www.google.com",
        "gateway.discord.gg", "cdn.discordapp.com", "i.ytimg.com",
    ]

    def probe_blobs(self, progress_cb, blob_keys: list[str],
                    profile_name: str = "default") -> list[dict]:
        """Перебор TLS-фейк-блобов: для каждого - перезапуск защиты с
        подменённым блобом и короткая батарея. Возвращает [{blob, ok, total,
        rate}]. Защиту не восстанавливает - задача вызывающего."""
        out: list[dict] = []
        try:
            self._ensure_winws2_dead()
            total = max(1, len(blob_keys))
            for i, key in enumerate(blob_keys):
                if self.shutdown_event.is_set():
                    break
                progress_cb(int(i * 90 / total), f"Блоб «{key}» ({i + 1}/{total})...")
                if not self._run_profile(profile_name, fake_blob=key)                         or not self._any_winws2_running():
                    out.append({"blob": key, "ok": 0, "total": len(self.BLOB_PROBE_HOSTS), "rate": -1.0})
                    continue
                time.sleep(timeouts.SETTLE_BLOB)
                res = self._run_domain_tests(self.BLOB_PROBE_HOSTS, concurrency=6,
                                             http_only=False, result_cb=None)
                ok = sum(1 for r in res if r.status == "OK")
                out.append({"blob": key, "ok": ok, "total": len(res),
                            "rate": round(ok / len(res) * 100, 1) if res else 0.0})
            progress_cb(95, "Восстановление защиты...")
        finally:
            self._ensure_winws2_dead()
        return out

    # ── ASN-скан (110 IP-проб из dpi-detector): белый SNI на конкретный IP,
    # загрузка ~32 КБ, классификация обрыва - как в оригинальном инструменте ──
    ASN_SNI = "example.com"           # IANA-домен: в реестре РКН быть не может,
    # пропускает максимум (батарея SNI 07.09: example 104/110, sferum 100,
    # hcaptcha 84, google 79; чёрный rutracker.org = 0/110 - ТСПУ режет по SNI)
    ASN_BODY = 32 * 1024

    def asn_scan(self, progress_cb, result_cb=None, sni: str = "") -> list[dict]:
        """IP-пробы по ASN: IP:443 с белым SNI и загрузкой ~32 КБ. Статусы:
        OK / DETECTED (обрыв на N КБ - stateful DPI) / TCP RST / SYN DROP /
        TIMEOUT / ERROR. Работает под текущей защитой, ничего не перезапускает.

        sni - SNI пробы (по умолчанию example.com). 2026-09-07: на «чёрном»
        SNI (rutracker.org) валится всё, на «белых» картина одинаковая -
        DPI режет по IP, а не по белому SNI."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import subprocess
        # Конкурентность 8 - компромисс: у dpi-detector 30-50 и комьюнити
        # спокойно это терпит; 4 было перестраховкой от «пачки SYN в один ASN».
        concurrency = 8
        probes = []
        probe_file = self.root_dir / "lists" / "cdn-asn-probes.json"
        try:
            import json
            probes = json.loads(probe_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return [{"id": "-", "asn": "-", "provider": "-", "status": "ERROR",
                     "detail": f"не читается {probe_file.name}: {e}"}]
        if not probes:
            return [{"id": "-", "asn": "-", "provider": "-", "status": "ERROR",
                     "detail": "список проб пуст"}]

        body_file = self.root_dir / "asn_probe_body.bin"
        try:
            body_file.write_bytes(os.urandom(self.ASN_BODY))
        except OSError:
            return [{"id": "-", "asn": "-", "provider": "-", "status": "ERROR",
                     "detail": "не удалось создать тестовое тело"}]

        sni = sni or self.ASN_SNI

        def probe_one(p: dict) -> dict:
            # Мобильные сети теряют SYN рывками: «не отвечает» подтверждаем
            # повтором, иначе результат - снимок на одну минуту.
            first = _probe_once(p)
            if first.get("status") in ("SYN DROP", "TIMEOUT"):
                time.sleep(1.2)
                second = _probe_once(p)
                if second.get("status") not in ("SYN DROP", "TIMEOUT"):
                    second["detail"] = (second.get("detail", "") + " | отвеч со 2-й попытки").strip(" |")
                    return second
                first["detail"] = (first.get("detail", "") + " | подтверждено повтором").strip(" |")
                return first
            return first

        def _probe_once(p: dict) -> dict:
            start = time.time()
            ip, pid = p.get("ip", ""), p.get("id", "?")
            try:
                r = subprocess.run(
                    ["curl.exe", "-4", "-k", "-sS", "-m", "10", "--connect-timeout", "3",
                     "--resolve", f"{sni}:443:{ip}",
                     "-w", "%{http_code} %{size_upload} %{time_total}",
                     "-o", "NUL",
                     "--data-binary", f"@{body_file}",
                     f"https://{sni}/"],
                    capture_output=True, text=True, encoding="oem", errors="replace",
                    timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                elapsed = round(time.time() - start, 1)
                err = (r.stderr or "").lower()
                out = (r.stdout or "").split()
                code = out[0] if out and out[0].isdigit() else ""
                uploaded = int(out[1]) if len(out) > 1 and out[1].isdigit() else 0
                kb = uploaded // 1024
                status, detail = "", ""
                if code and uploaded >= 28 * 1024:
                    status, detail = "OK", f"{elapsed}s"
                elif uploaded:
                    status = "DETECTED"
                    detail = f"обрыв на {kb} КБ | {elapsed}s"
                elif "reset by peer" in err or "recv failure" in err:
                    status, detail = "TCP RST", f"{elapsed}s"
                elif "connection timed out" in err and "connect" in err:
                    status, detail = "SYN DROP", "TCP SYN timeout | 8.0s"
                elif "timed out" in err:
                    status, detail = "TIMEOUT", f"{elapsed}s"
                elif "ssl" in err and ("handshake" in err or "alert" in err):
                    status, detail = "TLS RST", f"{elapsed}s"
                elif r.returncode == 28 or "timed out" in err:
                    # таймаут: SYN-фаза (соединение не установилось) или поток
                    status = "TIMEOUT"
                    if "connection timed out" in err:
                        status = "SYN DROP"
                    detail = (err.strip().split("curl:")[-1].strip()[:50] or "10s") + f" | {elapsed}s"
                else:
                    status, detail = "ERROR", (err.strip()[:60] or f"код {r.returncode} | {elapsed}s")
                res = {"id": pid, "asn": str(p.get("asn", "")), "provider": p.get("provider", ""),
                       "status": status, "detail": detail, "code": code}
            except subprocess.TimeoutExpired:
                res = {"id": pid, "asn": str(p.get("asn", "")), "provider": p.get("provider", ""),
                       "status": "SYN DROP", "detail": "TCP SYN timeout"}
            except OSError as e:
                res = {"id": pid, "asn": str(p.get("asn", "")), "provider": p.get("provider", ""),
                       "status": "ERROR", "detail": str(e)[:60]}
            if result_cb:
                result_cb(res)
            return res

        out: list[dict] = []
        total = len(probes)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(probe_one, p): i for i, p in enumerate(probes)}
            done = 0
            for fut in as_completed(futures):
                if self.shutdown_event.is_set():
                    break
                out.append(fut.result())
                done += 1
                progress_cb(int(done * 95 / total), f"ASN-пробы {done}/{total}...")
        try:
            body_file.unlink()
        except OSError:
            pass
        order = {p["id"]: i for i, p in enumerate(probes)}
        out.sort(key=lambda x: order.get(x["id"], 999))
        ok_n = sum(1 for x in out if x["status"] == "OK")
        progress_cb(100, f"Готово: {ok_n}/{total} OK")
        return out

    def _verify_with_desync(self, domains: list[str], result_cb,
                            ipset_catchall: bool = False) -> dict[str, str]:
        """Пробный прогон с десинком кандидатов: вердикт fix/hard по факту.

        Вердикт для КАЖДОГО домена (fix - вылечился, hard - умер или режется
        дальше); пустой словарь = проверка не состоялась (unknown у вызывающего)."""
        result: dict[str, str] = {}
        probe_list = self.root_dir / "lists" / "list-probe.txt"
        preset_path = self.root_dir / "presets" / "_probe_cdn.txt"
        try:
            probe_list.write_text("\n".join(domains) + "\n", encoding="utf-8")
            preset_src = (self.root_dir / "presets" / "default.txt").read_text(encoding="utf-8")
            marker = "--hostlist=@lists/list-general.txt\n"
            if marker not in preset_src:
                return result
            probe_preset = preset_src.replace(marker, marker + "--hostlist=@lists/list-probe.txt\n")
            preset_path.write_text(probe_preset, encoding="utf-8")
            if not self._run_profile("_probe_cdn", ipset_catchall=ipset_catchall):
                return result
            if not self._any_winws2_running():
                return result
            alive_now = self._run_domain_tests(domains, concurrency=15, http_only=True, result_cb=result_cb)
            alive_names = {r.domain for r in alive_now if r.status == "OK"}
            for d in domains:
                result[d] = "hard" if d not in alive_names else "fix"
            if alive_names:
                for r in tester_probes.run_tcp1620_tests(self.root_dir, sorted(alive_names), timeout=self.timeout):
                    if r.status == "TCP16_20":
                        result[r.domain] = "hard"
            return result
        except (OSError, _TestAbort):
            return result
        finally:
            self._ensure_winws2_dead()
            for p in (probe_list, preset_path):
                try:
                    p.unlink()
                except OSError:
                    pass

    def _verify_with_ipset(self, domains: list[str], result_cb) -> dict[str, str]:
        """Верификация в ipset-режиме: резолв кандидатов в IP → ВРЕМЕННЫЙ
        ipset-probe → прогон default+ipset. Возвращает вердикт для
        КАЖДОГО домена (fix/hard), пусто = проверка не состоялась.

        Ревью 18.10: пользовательский ipset-include-user.txt НЕ трогаем
        (раньше писали пробные IP в него и восстанавливали из памяти:
        crash/kill оставлял мусор, а параллельная правка юзера могла быть
        молча откатана finally)."""
        result: dict[str, str] = {}
        probe_inc = self.root_dir / "lists" / "ipset-probe.txt"
        all_ips: set[str] = set()
        for d in domains:
            all_ips.update(tester_probes.resolve_ips(d))
        if not all_ips:
            return result
        try:
            from core import list_health as _lh
            _lh.atomic_write_locked(probe_inc, "\n".join(sorted(all_ips)) + "\n")
            if not self._run_profile("default", ipset_catchall=True,
                                     ipset_include_file=probe_inc):
                return result
            if not self._any_winws2_running():
                return result
            alive_now = self._run_domain_tests(domains, concurrency=15, http_only=True, result_cb=result_cb)
            alive_names = {r.domain for r in alive_now if r.status == "OK"}
            for d in domains:
                result[d] = "hard" if d not in alive_names else "fix"
            if alive_names:
                for r in tester_probes.run_tcp1620_tests(self.root_dir, sorted(alive_names), timeout=self.timeout):
                    if r.status == "TCP16_20":
                        result[r.domain] = "hard"
            return result
        except (OSError, _TestAbort):
            return result
        finally:
            self._ensure_winws2_dead()
            try:
                probe_inc.unlink()
            except OSError:
                pass

    def _test_baseline(
        self,
        profile_name: str,
        progress_cb: Callable[[int, str], None],
        tier: str = "smoke",
        result_cb: Optional[Callable[[TestResult], None]] = None,
        kill_processes: bool = False,
    ) -> ProfileTestResult:
        # _setup_profile масштабирует self.timeout по RTT - сбрасываем, чтобы
        # базовые прогоны не использовали устаревший таймаут прошлого пресета.
        self.timeout = self._original_timeout
        if kill_processes:
            self._ensure_winws2_dead()
            _foreign = self._foreign_engine_error()
            if _foreign:
                raise RuntimeError(_foreign)

        def _logged_progress(pct: int, msg: str) -> None:
            if self._logger:
                self._logger.progress(profile_name, msg)
            progress_cb(pct, msg)

        _logged_progress(5, f"{profile_name}: проверка...")

        domains = self._get_tier_hosts(tier)
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

        # Пинг-фаза (только DNS-канарейки, доменные пинги убраны 2026-09-13).
        ping_total = len(PING_HOSTS)
        ping_done = 0

        for host in PING_HOSTS:
            if self.shutdown_event.is_set():
                return ProfileTestResult(profile_name=profile_name)
            all_results.append(tester_probes.ping_test(host, self.timeout))
            if result_cb:
                result_cb(all_results[-1])
            ping_done += 1
            progress_cb(55 + int(ping_done * 20 / ping_total), f"{profile_name} ping {host}")

        ok_count = sum(1 for r in all_results if r.status == "OK")
        fail_count = sum(1 for r in all_results if r.status in FAIL_STATUSES)
        total_time = sum(r.time_ms for r in all_results)
        total = ok_count + fail_count
        success_rate = (ok_count / total * 100) if total else 0
        net_ok, net_fail, net_total, network_rate, ping_ok, ping_total = tester_scoring.net_stats(all_results)

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
    ) -> ProfileTestResult:
        """Тест ТЕКУЩЕЙ конфигурации (что запущено - вероятно Zapret 1)."""
        return self._test_baseline("__current__", progress_cb, tier, result_cb, kill_processes=False)

    def test_naked(
        self,
        progress_cb: Callable[[int, str], None],
        tier: str = "smoke",
        result_cb: Optional[Callable[[TestResult], None]] = None,
    ) -> ProfileTestResult:
        """Тест сырого соединения БЕЗ запущенного zapret."""
        return self._test_baseline("__naked__", progress_cb, tier, result_cb, kill_processes=True)

    def run_naked_baseline(
        self,
        progress_cb: Callable[[int, str], None],
        result_cb: Optional[Callable[[TestResult], None]] = None,
    ) -> Optional[ProfileTestResult]:
        """Быстрая проверка связности без защиты (NAKED_BASELINE_HOSTS, ~3-5с).

        Гоняется перед свепом профилей, чтобы финальная рекомендация поймала
        случай «все стратегии == naked» - winws2 не меняет трафик на этой
        машине или DPI блокирует все попытки десинка. None при отмене."""
        self._ensure_winws2_dead()
        _foreign = self._foreign_engine_error()
        if _foreign:
            raise RuntimeError(_foreign)
        if self.shutdown_event.is_set():
            return None
        progress_cb(2, "Голый тест (без защиты) - базовый уровень...")
        results = self._run_domain_tests(
            NAKED_BASELINE_HOSTS, concurrency=4, expand_www=False,
            result_cb=result_cb,
        )
        net_ok, net_fail, net_total, network_rate, *_ = tester_scoring.net_stats(results)
        return ProfileTestResult(
            profile_name="__naked__", results=results,
            ok_count=net_ok, fail_count=net_fail,
            success_rate=network_rate,
            net_ok_count=net_ok, net_fail_count=net_fail, net_total=net_total,
            network_rate=network_rate, tier="smoke",
        )

    def collect_sanity_info(self, profile_name: str, blocked_domains: list[str]) -> dict:
        """Диагностика, отличающая «сильный DPI» от «winws2 ничего не делает».

        Два дешёвых теста (без debug-логов):
        1. dry-run тех же args, что строит тестер: winws2 печатает число
           загруженных desync-профилей. 0-1 вместо ожидаемых 4-7 для default.txt -
           сигнатура старого бага короткого пути (§1): пресет битый на ЭТОЙ машине.
        2. Покрытие списков: домена нет ни в одном @lists/*.txt из пресета -
           его desync-профиль не срабатывает (no_action, §15)."""
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
                # Другой winws2 с теми же фильтрами запущен (например служба):
                # dry-run обрывается рано («1 profile») и счётчик бессмыслен -
                # но проверка покрытия списков всё ещё применима.
                dry["note"] = "winws2 уже запущен - dry-run не показателен"
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
            # WinError 740 = нужен подъём прав (тестер обычно под админом, но
            # «не могу запустить» никогда не считается поломкой движка).
            if getattr(e, "winerror", None) == 740 or "WinError 740" in str(e):
                dry = {"ok": True, "profiles_loaded": None, "errors": []}
            else:
                dry["ok"] = False
                dry["errors"].append(str(e))

        # ── Покрытие списков ──
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
        # Читаем каждый список ОДИН раз, а не на каждый домен: sanity
        # вызывается для всех заблокированных доменов сразу.
        list_entries: dict[str, list[str]] = {}
        for name, path in include_lists:
            if not path.exists():
                continue
            from core import list_health
            list_entries[name] = list_health.read_entries(path)
        for domain in blocked_domains:
            d = domain.lower()
            found = [name for name, entries in list_entries.items()
                     if any(d == l or d.endswith("." + l) for l in entries)]
            coverage.append({"domain": domain, "covered": bool(found), "lists": found})

        return {"dry_run": dry, "list_coverage": coverage}

    def is_running(self) -> bool:
        return self._any_winws2_running()

    def signal_shutdown(self) -> None:
        self.shutdown_event.set()