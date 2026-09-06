"""Headless A/B прогон кандидата против default (STRATEGY_ROADMAP §2).

Последовательность (весь риск — внутри ОДНОГО запуска этого скрипта):
  warp disconnect -> sc stop zapret2 -> тест default (контроль)
  -> тест cand-autottl -> sc start zapret2 -> warp connect.
try/finally гарантирует восстановление службы и WARP даже при падении.

Запуск: python tools/ab_candidate.py cand-autottl [cand-...]
Результаты: tools/ab_result.json + stdout.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tester import Zapret2Tester  # noqa: E402


def _run(args: list[str], timeout: int = 10) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="oem",
                           errors="replace", timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return (r.stdout or "") + (r.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"ERR {e}"


def warp_status() -> str:
    out = _run(["warp-cli", "status"])
    for line in out.splitlines():
        if "Connected" in line or "Disconnected" in line:
            return line.strip()
    return out.strip()[:80]


def warp(action: str) -> str:
    return _run(["warp-cli", action]).strip()[:120]


def serialize(res) -> dict:
    return {
        "profile": res.profile_name,
        "network_rate": round(res.network_rate, 1),
        "success_rate": round(res.success_rate, 1),
        "net_ok": res.net_ok_count, "net_total": res.net_total,
        "ok": res.ok_count, "fail": res.fail_count,
        "ping_ok": getattr(res, "ping_ok_count", None),
        "total_time_s": round(res.total_time, 1),
        "error": getattr(res, "error", None),
        "results": [
            {"domain": r.domain, "type": r.test_type, "status": r.status,
             "ms": r.time_ms, "err": (r.error or "")[:60]}
            for r in res.results
        ],
    }


def main() -> None:
    profiles = sys.argv[1:] or ["cand-autottl"]
    out = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "warp_reconnected": False, "profiles": {}}

    def restore() -> None:
        print("\n=== RESTORE: service + WARP ===", flush=True)
        print("sc start:", _run(["sc", "start", "zapret2"], timeout=15).strip().splitlines()[0:1], flush=True)
        time.sleep(2)
        print("service:", _run(["sc", "query", "zapret2"]).strip().splitlines()[3:4], flush=True)
        print("warp connect:", warp("connect"), flush=True)
        time.sleep(4)
        out["warp_reconnected"] = "Connected" in warp_status()
        print("warp:", warp_status(), flush=True)
        print("winws2 alive:", _run(["tasklist", "/FI", "IMAGENAME eq winws2.exe", "/NH"]).strip()[-60:], flush=True)

    try:
        print("warp before:", warp_status(), flush=True)
        print("warp disconnect:", warp("disconnect"), flush=True)
        time.sleep(4)
        st1 = warp_status()
        time.sleep(12)
        st2 = warp_status()
        print(f"warp after 4s: {st1} | after 16s: {st2}", flush=True)
        if "Disconnected" not in st2:
            out["error"] = "WARP auto-reconnects (Always On) — A/B невозможен, нужен toggle-always-on"
            print(out["error"], flush=True)
            return

        print("sc stop zapret2:", _run(["sc", "stop", "zapret2"], timeout=15).strip().splitlines()[0:1], flush=True)
        time.sleep(1.5)
        tester = Zapret2Tester(ROOT)
        tester._ensure_winws2_dead()

        for profile in profiles:
            print(f"\n=== TEST {profile} ===", flush=True)
            t0 = time.time()
            try:
                res = tester.test_profile(profile, lambda pct, msg: print(f"  [{pct:3d}%] {msg}", flush=True))
                out["profiles"][profile] = serialize(res)
                print(f"  -> network_rate={res.network_rate:.1f}% ({res.net_ok_count}/{res.net_total}) "
                      f"ok={res.ok_count}/{res.ok_count + res.fail_count} "
                      f"time={time.time() - t0:.0f}s", flush=True)
            except Exception as e:
                out["profiles"][profile] = {"error": f"{type(e).__name__}: {e}"}
                print(f"  -> FAILED: {e}", flush=True)
            # каждый профиль сам гасит winws2 в конце — между профилями чисто
    finally:
        restore()
        out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        (ROOT / "tools" / "ab_result.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\nresults -> tools/ab_result.json", flush=True)


if __name__ == "__main__":
    main()
