r"""Golden-проверка @conf: эквивалентность argv-запуска и запуска через conf.

  python tools/check_arg_file.py            # все presets/*.txt: argv vs conf (dry-run)
  python tools/check_arg_file.py --quoting  # + матрица квотирования (пробел/'/[]/кириллица)

Exit code: 0 = всё совпало, 1 = расхождения. Служба и перехват НЕ трогаются
(только --dry-run). Историю исследования см.
AI_DOCS/ARG_FILE_RESEARCH_2026-10-14.md; песочницы - %TEMP%\opencode\argfile*.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.launcher import (  # noqa: E402
    _winws2_env, _winws2_raw_cmdline, build_args_from_preset, write_run_conf)


def _exe() -> Path:
    for p in (ROOT / "bin" / "winws2.exe", ROOT / "winws2.exe"):
        if p.exists():
            return p
    raise SystemExit("winws2.exe не найден (bin/winws2.exe)")


def _run(cmd: str | list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="oem",
                       errors="replace", timeout=90,
                       creationflags=subprocess.CREATE_NO_WINDOW,
                       cwd=str(cwd) if cwd else None, env=_winws2_env())
    return (r.stdout or "") + "\n" + (r.stderr or "")


def _key(out: str) -> tuple[str, bool]:
    prof = [l.strip() for l in out.splitlines() if "profile(s)" in l]
    return (prof[0] if prof else "?", "verified" in out)


def golden() -> int:
    exe = _exe()
    fails = 0
    for pf in sorted((ROOT / "presets").glob("*.txt")):
        if pf.stem == "custom":
            continue
        try:
            args = build_args_from_preset(ROOT, ROOT / "lua", ROOT / "blobs", pf,
                                          lists_dir=ROOT / "lists",
                                          windivert_dir=ROOT / "windivert")
        except Exception as e:  # noqa: BLE001
            print(f"SKIP {pf.name}: build_args: {e}")
            continue
        o_argv = _run([str(exe), "--dry-run"] + args, cwd=ROOT)
        conf = write_run_conf(ROOT, args, name="check_golden.conf")
        o_conf = _run(_winws2_raw_cmdline(exe, conf, "--dry-run"), cwd=ROOT)
        ka, kc = _key(o_argv), _key(o_conf)
        ok = ka == kc
        fails += 0 if ok else 1
        print(("PASS" if ok else "FAIL") + f" {pf.name}: argv={ka} conf={kc}")
        if not ok:
            print("--- argv ---\n" + o_argv[-1200:])
            print("--- conf ---\n" + o_conf[-1200:])
    return fails


def quoting() -> int:
    """Пути с пробелом / ' / [] / кириллицей: raw vs DQ (класс бага 14.10)."""
    exe = _exe()
    fails = 0
    tmp = Path(tempfile.mkdtemp(prefix="zapret2_quote_"))
    try:
        weird = tmp / "q'test] dir"
        weird.mkdir()
        hl_weird = weird / "list.txt"
        shutil.copyfile(ROOT / "lists" / "list-general.txt", hl_weird)
        hl_space = tmp / "list with space.txt"
        shutil.copyfile(ROOT / "lists" / "list-general.txt", hl_space)
        hl_cyr = tmp / "список тест.txt"
        shutil.copyfile(ROOT / "lists" / "list-general.txt", hl_cyr)
        base = ["--chdir=" + str(ROOT),
                "--lua-init=@lua/zapret-lib.lua",
                "--wf-udp-out", "443", "--filter-udp", "443",
                "--filter-l7", "quic", "--lua-desync=drop", "--dry-run"]
        cases = [
            (f"--hostlist={hl_weird}", False, "raw ' + []"),
            (f'--hostlist="{hl_weird}"', True, "DQ ' + []"),
            (f"--hostlist={hl_space}", False, "raw пробел"),
            (f'--hostlist="{hl_space}"', True, "DQ пробел"),
            (f'--hostlist="{hl_cyr}"', True, "DQ кириллица+пробел"),
        ]
        for token, expect_ok, label in cases:
            conf = tmp / "q.conf"
            conf.write_text("\n".join(base[:2] + [token] + base[2:]) + "\n",
                            encoding="utf-8")
            out = _run(_winws2_raw_cmdline(exe, conf, "--dry-run"), cwd=ROOT)
            ok = ("verified" in out
                  and "cannot access" not in out and "bad file" not in out)
            good = ok == expect_ok
            fails += 0 if good else 1
            print(f"{'PASS' if good else 'FAIL'} quoting [{label}]: "
                  f"verified={ok} (ожидалось {expect_ok})")
            if not good:
                print(out[-800:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fails


if __name__ == "__main__":
    rc = golden()
    if "--quoting" in sys.argv:
        rc += quoting()
    print(("ИТОГ: OK" if rc == 0 else f"ИТОГ: FAIL ({rc})"))
    raise SystemExit(1 if rc else 0)
