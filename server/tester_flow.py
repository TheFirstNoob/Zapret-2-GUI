"""tester_flow.py - фоновые воркеры тестера и их хелперы (аудит #1/#3).

Аудит #3: run_tester_action раздроблен на ветки-функции (_test_branch /
_test_profiles_branch / _cdn_scan_branch / _current_branch / _naked_branch /
_full_analysis_branch), сборка custom уехала в server/custom_build.py.
Логика прогонов не менялась; state и tester передаются явно.
"""
from __future__ import annotations

import subprocess
import time
import winsound
from pathlib import Path
from typing import Callable, Optional

from core.config import DEFAULT_PROFILE
from core.service_manager import (pause_recovery, recovery_snapshot,
                                  resume_recovery,
                                  restore_recovery_from_snapshot)
from core.tester import (CDN_PROVIDERS, CONTROL_DOMAINS, QUIC_QUIRK_DOMAINS,
                         is_control)
from core.test_logger import TestLogger
from server import custom_build, session_recovery
from server.app_state import (STATE, TesterState, get_config_manager,
                              get_controller, get_root_dir, get_tester,
                              scan_winws_exe, ui_debug as _ui_debug, ui_presets)
from server.recommend import build_recommendation, recheck_contested


def play_completion_sound() -> None:
    try:
        winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        pass


def serialize_result(res) -> dict:
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
    }


def make_progress_cb(state: TesterState) -> Callable:
    def cb(pct: int, msg: str) -> None:
        with state.lock:
            state.progress_pct = pct
            state.progress_msg = msg
    return cb


def make_result_cb(state: TesterState, profile: Optional[str] = None) -> Callable:
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
            # фронт считает live-счётчики «Хосты» только по этим категориям -
            # чтобы не прыгали (17/17 → 8/8) на финальном network_rate
            "rated": (r.domain not in CONTROL_DOMAINS
                      and r.domain not in QUIC_QUIRK_DOMAINS
                      and not is_control(r.domain)),
            "control": (r.domain in CONTROL_DOMAINS or is_control(r.domain)),
        }
        if profile:
            payload["profile"] = profile
        state.add_result(payload)
    return cb


def run_tester(fn):
    with STATE.tester_lock:
        return fn()


def check_vpn() -> dict:
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


def kill_never_hang(image_names: list[str]) -> None:
    from core.proc import kill_image
    for name in image_names:
        kill_image(name, timeout=6)


def svc_was_running() -> bool:
    try:
        from core.service_manager import status as svc_status
        return svc_status() == "running"
    except Exception:
        return False


def restore_protection_after_naked(z2_was: bool, z1_was: bool, state, svc_was: bool = False) -> str:
    """Восстановление защиты, активной до голого теста: naked гасит
    winws/winws2, оставлять пользователя без защиты нельзя.
    Best effort - ошибки возвращаем, не бросаем."""
    try:
        if z2_was:
            # Если обход жил в службе - поднимаем службу (sc start с её же
            # binPath), а не голый процесс: иначе после скана служба остаётся
            # «остановлена», хотя winws2 работает вручную.
            if svc_was:
                try:
                    from core.service_manager import start as svc_start
                    ok_s, msg_s = svc_start(None)
                    if ok_s:
                        state.set_progress(99, "Восстанавливаем Zapret 2 (через службу)...")
                        return "Zapret 2 восстановлен через службу"
                except Exception:
                    pass
            cfg = get_config_manager().load()
            profile = cfg.last_profile or DEFAULT_PROFILE
            state.set_progress(99, f"Восстанавливаем Zapret 2 ({profile})...")
            ok, msg = get_controller().start(
                profile,
                game_filter_mode=cfg.game_filter_mode,
                discord_voice=cfg.discord_voice,
                discord_voice_mode=cfg.discord_voice_mode,
                fake_blob=cfg.fake_blob,
                winws2_debug=cfg.winws2_debug,
                autohostlist=cfg.autohostlist,
                ipset_catchall=cfg.ipset_catchall,
                discord_alt=cfg.discord_alt,
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
    except Exception as e:
        return f"Не удалось восстановить защиту: {e}"


def run_asn_scan() -> None:
    """ASN-пробы (110 IP): мериют ТСПУ напрямую, БЕЗ нашего десинка в пути.

    Обязателен чистый путь: под десинком замер показывает смесь «ТСПУ + наш
    обман» - SYN DROP могли вызывать мы сами. Защита останавливается на
    время скана и восстанавливается (сервис-осведомлённо)."""
    state = STATE.tester_state
    tester = get_tester()
    svc_was = svc_was_running()
    z2_was = tester.is_running()
    z1_was = tester._any_winws_running()
    pause_recovery()  # SCM-перезапуск службового winws2 посреди скана (H3)
    try:
        with state.lock:
            state.reset()
            state.action_type = "asn_scan"
        if z2_was or z1_was:
            state.set_progress(2, "Останавливаем обход (замер чистого пути к ТСПУ)...")
            kill_never_hang(["winws.exe", "winws2.exe"])
        results = run_tester(lambda: tester.asn_scan(make_progress_cb(state)))
        note = ""
        if z2_was or z1_was or svc_was:
            note = restore_protection_after_naked(z2_was, z1_was, state, svc_was)
        with state.lock:
            state.final_result = {"type": "asn_scan", "probes": results, "restored": note}
            state.running = False
    except Exception as e:
        with state.lock:
            state.error = str(e)
    finally:
        resume_recovery()
        with state.lock:
            state.running = False


def run_blob_probe(data: dict) -> None:
    """Перебор TLS-фейк-блобов на короткой батарее. Защита на время прогона
    перезапускается по одному разу на блоб - восстановление
    сервис-осведомлённое."""
    state = STATE.tester_state
    tester = get_tester()
    pause_recovery()  # SCM-перезапуск службового winws2 рушит перебор (H3)
    try:
        with state.lock:
            state.reset()
            state.action_type = "blob_probe"
        cfg = get_config_manager().load()
        from core.service_manager import is_installed as svc_installed, status as svc_status
        svc_was = svc_installed() and svc_status() == "running"
        z2_was = tester.is_running()
        blobs_dir = get_root_dir() / "blobs"
        keys = sorted(f.stem.removeprefix("tls_clienthello_")
                      for f in blobs_dir.glob("tls_clienthello_*.bin")
                      if not f.stem.removeprefix("tls_clienthello_").endswith("_kyber"))
        if not keys:
            with state.lock:
                state.error = "в blobs/ нет tls_clienthello_*.bin"
            return
        results = run_tester(lambda: tester.probe_blobs(
            make_progress_cb(state), keys,
            profile_name=cfg.last_profile or DEFAULT_PROFILE))
        note = ""
        if z2_was or svc_was:
            note = restore_protection_after_naked(True, False, state, svc_was)
        with state.lock:
            state.final_result = {"type": "blob_probe", "results": results,
                                  "restored": note}
            state.running = False
            return
    except Exception as e:
        with state.lock:
            state.error = str(e)
    finally:
        resume_recovery()
        with state.lock:
            state.running = False


def _start_logger(tester, action: str) -> TestLogger:
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
    return logger


def _cdn_scan_branch(state, tester, data: dict) -> None:
    progress = make_progress_cb(state)
    result_cb = make_result_cb(state)
    cfg = get_config_manager().load()
    svc_was = svc_was_running()
    scan = run_tester(lambda: tester.scan_cdn_recommendations(
        progress, result_cb=result_cb,
        ipset_mode=bool(cfg.ipset_catchall),
        ab_ipset=True,
        profile_name=cfg.last_profile or DEFAULT_PROFILE))
    note = ""
    # Скан сам перезапускает защиту (A/B-прогон, naked,
    # верификация) - восстанавливаем всегда, через службу, если
    # она жила.
    if scan.naked_done or scan.protection_touched:
        note = restore_protection_after_naked(scan.z2_was, scan.z1_was, state, svc_was)
    state.set_final({
        "type": "cdn_scan",
        "verdicts": [v.__dict__ for v in scan.verdicts],
        "naked_done": scan.naked_done,
        "note": note,
        "error": scan.error,
        "ipset_mode": scan.ipset_mode,
    })
    state.running = False


def _test_branch(state, tester, data: dict) -> None:
    # Защита пользователя (включая Zapret 1) на время теста гасится и
    # возвращается - чистый замер и предсказуемый финал (как в naked-ветке).
    z2_was = get_controller().status().running
    z1_was = scan_winws_exe()["running"]
    svc_was = svc_was_running()
    if z1_was:
        kill_never_hang(["winws.exe"])
    result = run_tester(lambda: tester.test_profile(
        data.get("profile", DEFAULT_PROFILE), make_progress_cb(state),
        tier=data.get("tier", "critical"), result_cb=make_result_cb(state),
        ipset_catchall=bool(get_config_manager().load().ipset_catchall),
    ))
    final = serialize_result(result)
    # Восстановление защиты и при отмене: отмена теста != «выключи обход»
    note = restore_protection_after_naked(
        z2_was or svc_was, z1_was, state, svc_was)
    if note:
        final["restored"] = note
    play_completion_sound()
    state.set_final(final)


def _is_start_failure(res) -> bool:
    """Профиль НЕ запустился (аборт движка/пустой результат).

    Аборт test_profile возвращает ProfileTestResult с единственным служебным
    TestResult(test_type="process"); такие НЕ должны попадать в ранжирование
    как 0%-стратегии (ревью-раунд 3: ошибка запуска != плохая стратегия)."""
    if res is None:
        return True
    res_list = getattr(res, "results", None) or []
    if not res_list:
        return True
    return all(r.test_type == "process" for r in res_list)


def _test_profiles_branch(state, tester, data: dict) -> None:
    profiles = data.get("profiles", None)
    if not profiles:
        profiles = ui_presets() or ["default"]
    # Порядок ВСЕГДА: default первым, auto/custom последними -
    # проверенная стратегия должна тестироваться первой (порядок
    # задаём здесь, а не только для glob-пути из /api/status).
    def _order_key(p: str):
        if p == "default":
            return (0, "")
        if p in ("auto", "custom"):
            return (2, p)
        return (1, p)
    profiles = sorted(profiles, key=_order_key)
    # custom генерируется ЭТИМ же тестом: стухшая копия из
    # прошлого запуска бессмысленна - не тратим на неё прогон;
    # свежая сборка получает одну проверочную сессию ниже.
    profiles = [p for p in profiles if p != "custom"]
    all_results = []
    start_failures: list[str] = []
    alt_params = bool(data.get("alt_params", False))
    # Прогоны: база для всех пресетов; с галочкой - ещё и ALT
    # (справочно: в рекомендацию идут только базовые прогоны).
    runs: list[tuple[str, bool]] = []
    for p in profiles:
        runs.append((p, False))
        if alt_params:
            runs.append((p, True))
    total = len(runs)
    _tier = data.get("tier", "critical")
    # Тестер гоняет стратегии в текущей конфигурации пользователя
    # (глобальный тоггл «Общий IP-обход»); CDN-механика переехала
    # в отдельную вкладку (скан с A/B по ipset).
    ipset_mode = bool(get_config_manager().load().ipset_catchall)
    progress = make_progress_cb(state)

    # Защита, которая была у пользователя ДО прогона, захватывается
    # ДО naked-baseline: тот гасит winws2, и чтение после свеепа
    # всегда даёт False (восстановление становилось мёртвым - H1)
    z2_was = get_controller().status().running
    z1_was = scan_winws_exe()["running"]
    svc_was = svc_was_running()
    if z1_was:
        # Zapret 1 иначе искажает и «голый» тест, и все профили
        # (ревью-раунд 3): гасим на время свипа и вернём после (как naked).
        kill_never_hang(["winws.exe"])

    # Сначала naked-baseline: ловит «стратегии ничего не делают».
    naked_baseline = run_tester(lambda: tester.run_naked_baseline(
        make_progress_cb(state),
        result_cb=make_result_cb(state, profile="__naked__"),
    ))
    if naked_baseline is not None:
        progress(5, f"Голый тест: {naked_baseline.net_ok_count}/{naked_baseline.net_total} доступно")

    for idx, (profile_name, is_alt) in enumerate(runs):
        if tester.shutdown_event.is_set():
            break
        label = f"{profile_name} (ALT)" if is_alt else profile_name
        progress(int(6 + idx / total * 94),
                 f"Тестируем стратегию {label} ({idx + 1}/{total})...")

        def _inner_progress(pct: int, msg: str):
            overall = int(6 + (idx + pct / 100) / total * 94)
            progress(overall, msg)

        cb_for_profile = make_result_cb(state, profile=label)
        try:
            res = run_tester(
                lambda pn=profile_name, cb=cb_for_profile, alt=is_alt: tester.test_profile(
                    pn, _inner_progress, tier=_tier,
                    result_cb=cb,
                    ipset_catchall=ipset_mode,
                    discord_alt=alt)
            )
        except Exception as e:  # noqa: BLE001
            # P2: неожиданный сбой одного профиля не рушит весь свип
            _ui_debug(f"tester: profile {label} EXCEPTION: {e!r}")
            res = None
        if _is_start_failure(res):
            # P1-1: движок не запустился - это НЕ 0%-стратегия; в
            # ранжирование не идёт (иначе вердикт врёт «не пробило»)
            start_failures.append(label)
            progress(int(6 + (idx + 1) / total * 94),
                     f"Стратегия {label}: не запустилась")
        else:
            if not is_alt:
                all_results.append(res)
            progress(int(6 + (idx + 1) / total * 94),
                     f"Стратегия {label}: {res.success_rate:.0f}%")
        with state.lock:
            state.completed.append(label)
    if all_results:
        best = max(all_results, key=lambda r: (r.network_rate, r.net_ok_count))
        blocked = sorted({r.domain for r in best.results
                          if r.test_type != "ping" and r.status != "OK"})
        sanity = tester.collect_sanity_info(best.profile_name, blocked)
        rec = build_recommendation(all_results, naked_baseline, sanity)
        final = serialize_result(best)
        final["recommendation"] = rec
        final["sanity"] = sanity
        final["naked"] = serialize_result(naked_baseline) if naked_baseline else None

        # Личная стратегия: лучший сегмент на семейство
        # (Discord ← P_a, Google ← P_b, General ← P_c).
        custom = None
        try:
            custom = custom_build.build_custom_strategy(
                get_root_dir(), all_results, tester)
            final["custom"] = custom
        except Exception as e:
            custom = {"error": str(e), "preset": "custom"}
            final["custom"] = custom

        # Собранная custom всегда заслуживает одной проверочной
        # сессии, прежде чем рекомендовать её (в прогоне её не было).
        if final.get("custom", {}).get("valid") and not tester.shutdown_event.is_set():
            progress(98, "Тестируем собранную стратегию custom...")
            try:
                res = run_tester(
                    lambda: tester.test_profile(
                        "custom", make_progress_cb(state),
                        tier=_tier, result_cb=make_result_cb(state, profile="custom"),
                        ipset_catchall=ipset_mode)
                )
            except Exception as e:  # noqa: BLE001
                _ui_debug(f"tester: custom check EXCEPTION: {e!r}")
                res = None
            if res is not None and _is_start_failure(res):
                # custom не стартовал: не 0%-результат, а сбой движка
                custom["valid"] = False
                custom["error"] = ("custom не запустился в проверочной "
                                   "сессии (движок/WinDivert)")
                _ui_debug("tester: custom check start failed")
                res = None
            if res is not None:
                all_results.append(res)
                best = max(all_results, key=lambda r: (r.network_rate, r.net_ok_count))
                blocked = sorted({r.domain for r in best.results
                                  if r.test_type != "ping" and r.status != "OK"})
                sanity = tester.collect_sanity_info(best.profile_name, blocked)
                rec = build_recommendation(all_results, naked_baseline, sanity)
                final = serialize_result(best)
                final["recommendation"] = rec
                final["sanity"] = sanity
                final["naked"] = serialize_result(naked_baseline) if naked_baseline else None
                final["custom"] = custom
                c_rate = getattr(res, "network_rate", 0.0)
                if c_rate > best.network_rate + 1e-9:
                    custom["relation"] = "better"
                elif abs(c_rate - best.network_rate) < 1e-9:
                    custom["relation"] = "equal"
                else:
                    custom["relation"] = "worse"
                custom["rate"] = round(c_rate, 1)

        # ── Речек спорных доменов (§29) ──
        # Подробности - в докстринге recheck_contested.
        rec = recheck_contested(tester, best, rec, progress)
        final["recommendation"] = rec
        _ui_debug(f"tester: sweep done best={best.profile_name} "
                  f"rate={best.network_rate:.1f}")
        if tester.shutdown_event.is_set():
            # P3: отмена посреди свипа - рекомендация по подмножеству
            # профилей; честно помечаем прогон неполным
            final["partial"] = True
            rec["message"] = ((rec.get("message") or "")
                              + " ⏹ Прогон прерван - результаты неполные.")

        # Вернуть защиту, которая была у пользователя до теста
        # (было: после basic-прогона обход пропадал молча).
        # z2_was/svc_was захвачены В НАЧАЛЕ прогона (до naked),
        # здесь они уже не читаются - winws2 к этому моменту гашен.
        if start_failures:
            final["start_failures"] = start_failures
        # Восстановление защиты ДЕЛАЕМ И ПРИ ОТМЕНЕ (как naked/asn): отмена
        # теста не означает «оставь меня без обхода». P2-4: z2_was может быть
        # False при живой службе (winws2 умер до замера) - svc_was в этом
        # случае обязан вернуть службу.
        final["restored"] = restore_protection_after_naked(
            z2_was or svc_was, z1_was, state, svc_was)

        play_completion_sound()
        state.set_final(final, [serialize_result(r) for r in all_results])
    elif start_failures and not tester.shutdown_event.is_set():
        # P1-1: ни одного валидного прогона - честный вердикт «движок не
        # запустился» (UI: engine_broken), а не «стратегии не пробили».
        state.set_final({
            "profile": "",
            "start_failures": start_failures,
            "recommendation": {
                "verdict": "engine_broken",
                "best_profile": "",
                "message": ("⚠ Ни один профиль не запустился: winws2 не "
                            "стартует или WinDivert занят (сбой: "
                            + ", ".join(start_failures[:6])
                            + "). Смотрите test_session.log; попробуйте "
                            "«Выгрузить драйвер» на главной или перезапустите "
                            "программу."),
            },
        })
    else:
        state.running = False


def _current_branch(state, tester, data: dict) -> None:
    winws_info = scan_winws_exe()
    if not winws_info["running"]:
        state.set_final({"type": "need_zapret1"})
        state.running = False
        return

    state.set_progress(0, "Zapret 1 обнаружен. Тестирование...")
    cur_progress = make_progress_cb(state)
    cur_result_cb = make_result_cb(state, profile="__current__")
    cur_result = run_tester(
        lambda: tester.test_current_setup(
            cur_progress, tier=data.get("tier", "critical"),
            result_cb=cur_result_cb)
    )
    state.set_final({
        "type": "current_result",
        **serialize_result(cur_result),
    })


def _naked_branch(state, tester, data: dict) -> None:
    # Запоминаем, чем был защищён пользователь, чтобы вернуть после
    z2_was = get_controller().status().running
    z1_was = scan_winws_exe()["running"]
    svc_was = svc_was_running()
    state.set_progress(1, "Останавливаем zapret...")
    kill_never_hang(["winws.exe", "winws2.exe"])
    state.set_progress(3, "Защита остановлена. Запуск голого теста...")
    naked_result = run_tester(
        lambda: tester.test_naked(
            make_progress_cb(state), tier=data.get("tier", "critical"),
            result_cb=make_result_cb(state))
    )
    restore_note = restore_protection_after_naked(
        z2_was, z1_was, state, svc_was)
    final = {"type": "naked_result", **serialize_result(naked_result)}
    if restore_note:
        final["restored"] = restore_note
    state.set_final(final)


def _full_analysis_branch(state, tester, data: dict) -> None:
    profiles = data.get("profiles", [DEFAULT_PROFILE])
    # Защита до анализа: он гасит всё, а раньше НЕ возвращал - пользователь
    # оставался без обхода (находка ревью-раунда 3; «Расширенный тест»).
    z2_was = get_controller().status().running
    z1_was = scan_winws_exe()["running"]
    svc_was = svc_was_running()
    kill_never_hang(["winws.exe", "winws2.exe"])
    time.sleep(0.5)

    from core.full_analyzer import run_full_analysis, AnalyzerEvent

    def _on_event(ev: AnalyzerEvent) -> None:
        with state.lock:
            ev.payload["type"] = ev.type
            if ev.type == "progress":
                state.progress_pct = ev.payload.get("percent", 0)
                state.progress_msg = ev.payload.get("message", "")
            elif ev.type == "test_result":
                state.results.append(ev.payload)
            elif ev.type == "intermediate":
                state.results.append(ev.payload)

    # run_full_analysis сам берёт STATE.tester_lock (нереентерабельный
    # Lock - оборачивать в run_tester = гарантированный дедлок)
    fa_ipset = bool(get_config_manager().load().ipset_catchall)
    final_all = run_full_analysis(tester, profiles, STATE.tester_lock, on_event=_on_event,
                                  ipset_catchall=fa_ipset)

    # Возврат защиты, которая была до анализа (иначе обход оставался
    # выключенным - находка ревью-раунда 3)
    # Восстановление защиты и при отмене (отмена анализа != «выключи обход»)
    restore_note = restore_protection_after_naked(
        z2_was or svc_was, z1_was, state, svc_was)

    # Финальный poll: чистим промежуточные результаты -
    # оставляем только test_result (есть домен и статус)
    with state.lock:
        state.results = [r for r in state.results
                         if r.get("domain") and r.get("status")]
        state.final_result = {"type": "final", "all_results": final_all}
        if restore_note:
            state.final_result["restored"] = restore_note
        state.all_results = final_all


def run_tester_action(data: dict) -> None:
    action = data.get("action", "")
    state = STATE.tester_state
    known = ("test", "test_profiles", "current", "naked", "cdn_scan",
             "check-winws", "check_vpn", "full_analysis")
    if action not in known:
        with state.lock:
            state.error = f"Неизвестное действие тестера: {action!r}"
            state.running = False
        return
    with state.lock:
        state.running = True
        state.reset()
        state.action_type = action
        # гонка cancel→start: cancelled остаётся True от прошлого прогона до
        # reset() в потоке - первый poll (350мс) видел «Тест отменён» (M2)
        state.cancelled = False

    tester = get_tester()
    logger = None
    _ui_debug(f"tester worker: start action={action!r} data={dict(data)}")

    try:
        # Длительные фазы гасят winws2 - SCM-recovery на это время выключается
        # (иначе перезапускает службовый winws2 посреди прогона: конфликт
        # WinDivert, обрыв теста - баг 2026-09-12). ВНУТРИ try: зависший
        # sc.exe не должен уронить поток до входа в try и застревать
        # running=True навсегда (H2).
        if action in ("test", "test_profiles", "naked", "full_analysis", "cdn_scan"):
            try:
                pause_recovery()
            except Exception as _pe:
                _ui_debug(f"pause_recovery failed: {_pe}")
            # crash-recovery: durable-журнал снимка ДО любых гашений
            # (logs/test_session_state.json; при гибели GUI посреди прогона
            # защита/recovery восстановятся на следующем старте)
            try:
                session_recovery.write_session_journal(
                    get_root_dir(), action,
                    protection={
                        "z2": get_controller().status().running,
                        "z1": scan_winws_exe()["running"],
                        "svc": svc_was_running(),
                    },
                    recovery=recovery_snapshot())
            except Exception as _je:
                _ui_debug(f"session journal write failed: {_je}")

        # короткие синхронные проверки
        if action == "check-winws":
            info = scan_winws_exe()
            state.set_final({"type": "check_result", "running": info["running"]})
            state.running = False
            return

        if action == "check_vpn":
            result = check_vpn()
            state.set_final({"type": "vpn_result", **result})
            state.running = False
            return

        if action == "cdn_scan":
            _cdn_scan_branch(state, tester, data)
            return

        # действия, которым нужен логгер
        logger = _start_logger(tester, action)
        if action == "test":
            _test_branch(state, tester, data)
        elif action == "test_profiles":
            _test_profiles_branch(state, tester, data)
        elif action == "current":
            _current_branch(state, tester, data)
        elif action == "naked":
            _naked_branch(state, tester, data)
        elif action == "full_analysis":
            _full_analysis_branch(state, tester, data)

    except Exception as e:
        _ui_debug(f"tester worker: EXCEPTION action={action!r}: {e}")
        # незавершённый прогон: вернуть recovery+защиту сразу (тот же путь,
        # что при аварийном старте) - иначе обход остаётся выключенным
        try:
            session_recovery.recover_unfinished_session(
                get_root_dir(),
                restore_recovery=restore_recovery_from_snapshot,
                restore_protection=lambda z, o, s: restore_protection_after_naked(
                    z, o, state, s),
                log=_ui_debug)
        except Exception:
            pass
        with state.lock:
            state.error = str(e)
    finally:
        with state.lock:
            st_err = state.error
            has_final = state.final_result is not None
        _ui_debug(f"tester worker: end action={action!r} error={st_err!r} final={has_final}")
        resume_recovery()
        try:
            # журнал отработан (успешный прогон сам вернул защиту; исключение
            # обработано recover выше) - файл больше не нужен
            session_recovery.clear_session_journal(get_root_dir())
        except Exception:
            pass
        with state.lock:
            state.running = False
        if logger:
            logger.close()
            tester.set_logger(None)
