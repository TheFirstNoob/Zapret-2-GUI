"""Варианты UDP-обхода для Wardogs (порт 4192): udplen / fake.

Запуск: python tools/_game_udp.py <вариант>
  udplen_hex   - udplen +5, паттерн 0xDEADBEEF (рецепт Discord Voice)
  udplen_quic  - udplen +5, паттерн quic_google (QUIC-подобный паддинг)
  udplen_fake  - fake quic x3 + udplen +5 (комбо)
  udplen_up2   - udplen +2 (мягкий)
После запуска winws2 работает вручную (служба остановлена) — проверяем в игре,
затем вернуть службу: sc.exe start zapret2.
"""
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI")
MIR = Path(r"C:\Users\TheFirstNoob\Desktop\Zapret 2 GUI\zapret2_gui")
sys.path.insert(0, str(REPO))

from core.launcher import build_args_from_preset, validate_args  # noqa: E402

PORT = 4192
VARIANTS = {
    "udplen_hex": ["--lua-desync=udplen:increment=5:pattern=0xDEADBEEF"],
    "udplen_quic": ["--lua-desync=udplen:increment=5:pattern=quic_google"],
    "udplen_fake": ["--lua-desync=fake:blob=quic_google:repeats=3",
                    "--lua-desync=udplen:increment=5:pattern=quic_google"],
    "udplen_up2": ["--lua-desync=udplen:increment=2:pattern=0xDEADBEEF"],
}


def add_wf_udp_port(args: list[str], port: int) -> None:
    for i, t in enumerate(args):
        if t == "--wf-udp-out" and i + 1 < len(args):
            if str(port) not in args[i + 1].split(","):
                args[i + 1] = args[i + 1] + f",{port}"
            return
    args.insert(0, f"--wf-udp-out={port}")


name = sys.argv[1] if len(sys.argv) > 1 else ""
if name not in VARIANTS:
    print("варианты:", ", ".join(VARIANTS))
    raise SystemExit(1)

args = build_args_from_preset(
    MIR, MIR / "lua", MIR / "blobs", MIR / "presets" / "default-alt.txt",
    lists_dir=MIR / "lists", windivert_dir=MIR / "windivert",
    debug=False, game_filter_mode="off", discord_voice=False,
    discord_voice_mode="", autohostlist=False, ipset_catchall=False)
add_wf_udp_port(args, PORT)
args += ["--new", f"--filter-udp={PORT}", "--out-range", "-d10"]
args += VARIANTS[name]

ok, err = validate_args(MIR / "bin" / "winws2.exe", args, cwd=MIR)
if not ok:
    print("VALIDATE FAIL:", err)
    raise SystemExit(1)

subprocess.run(["sc.exe", "stop", "zapret2"], capture_output=True)
for _ in range(20):
    q = subprocess.run(["sc.exe", "query", "zapret2"], capture_output=True,
                       text=True, encoding="oem", errors="replace")
    if "STOPPED" in (q.stdout or ""):
        break
    time.sleep(0.3)
subprocess.run(["taskkill", "/F", "/IM", "winws2.exe"], capture_output=True)
time.sleep(1.0)

bat = MIR / "_z2udp_run.bat"
cmd = 'start "z2udp" /min "%~dp0bin\\winws2.exe" ' + " ".join(
    f'"{a}"' for a in args)
bat.write_text("@echo off\r\ncd /d \"%~dp0\"\r\n" + cmd + "\r\n",
               encoding="ascii")
subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(MIR),
                 creationflags=0x08000000)
time.sleep(2.0)
r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq winws2.exe"],
                   capture_output=True, text=True,
                   encoding="oem", errors="replace")
alive = "winws2.exe" in (r.stdout or "")
print(f"variant={name} winws2={'RUNNING' if alive else 'NOT RUNNING'} "
      f"(порт {PORT})")
