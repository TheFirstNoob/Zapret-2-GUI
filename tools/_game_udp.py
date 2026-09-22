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
# Игровые серверы: UDP шёл на 54.115.x (4192), TCP-бэкенды — 54.228/54.216/3.218.
# Порты у серверов могут меняться → таргетим по IP-диапазонам, не по порту.
IPSET_CIDRS = ("54.115.0.0/16", "54.228.0.0/16", "54.216.0.0/16",
               "3.218.0.0/16")
VARIANTS = {
    "udplen_hex": {"ports": [PORT],
                   "desync": ["--lua-desync=udplen:increment=5:pattern=0xDEADBEEF:payload=all"]},
    "udplen_quic": {"ports": [PORT],
                    "desync": ["--lua-desync=udplen:increment=5:pattern=quic_google:payload=all"]},
    "udplen_fake": {"ports": [PORT],
                    "desync": ["--lua-desync=fake:blob=quic_google:repeats=3:payload=all",
                               "--lua-desync=udplen:increment=5:pattern=quic_google:payload=all"]},
    "udplen_up2": {"ports": [PORT],
                   "desync": ["--lua-desync=udplen:increment=2:pattern=0xDEADBEEF:payload=all"]},
    # IP-таргетинг: любой порт на игровых диапазонах
    "udplen_ipset": {"ipset": True,
                     "desync": ["--lua-desync=udplen:increment=5:pattern=quic_google:payload=all"]},
    "udplen_ipset_hex": {"ipset": True,
                         "desync": ["--lua-desync=udplen:increment=5:pattern=0xDEADBEEF:payload=all"]},
    # Рецепт из треда: fake на диапазон 54.115.0.0/16 (любой порт), как GameFilter,
    # но без фейка рабочих UDP-потоков (104.29.x/Steam) — их не трогаем
    "fake_ipset": {"ipset": True,
                   "desync": ["--lua-desync=fake:blob=quic_google:repeats=10:payload=all"]},
    # Механизм zapret1: fake + DROP оригинала (как nfqws: игра ретранслирует,
    # DPI видит только QUIC-фейки). cutoff n4 ~ out-range -d4.
    "fake_drop": {"ipset": True, "cutoff": "-d4",
                  "desync": ["--lua-desync=fake:blob=quic_google:repeats=10:payload=all",
                             "--lua-desync=drop"]},
    "fake_drop_full": {"ipset": True, "no_cutoff": True,
                       "desync": ["--lua-desync=fake:blob=quic_google:repeats=10:payload=all",
                                  "--lua-desync=drop"]},
    # fake без drop (оригинал тоже уходит) — если дроп ломает протокол игры
    "fake_pass": {"ipset": True, "cutoff": "-d4",
                  "desync": ["--lua-desync=fake:blob=quic_google:repeats=10:payload=all"]},
    # Весь высокий UDP (проверка «дело вообще в UDP-портах?»)
    "udplen_all": {"all_udp": True,
                   "desync": ["--lua-desync=udplen:increment=5:pattern=quic_google:payload=all"]},
}


def add_wf_udp_value(args: list[str], value: str) -> None:
    for i, t in enumerate(args):
        if t == "--wf-udp-out" and i + 1 < len(args):
            if value not in args[i + 1].split(","):
                args[i + 1] = args[i + 1] + f",{value}"
            return
    args.insert(0, f"--wf-udp-out={value}")


def build_extra(cfg: dict) -> list[str]:
    """Профиль(и) для варианта: порт / ipset / весь UDP."""
    extra: list[str] = []
    if cfg.get("no_cutoff"):
        cutoff = []
    elif cfg.get("cutoff"):
        cutoff = ["--out-range", cfg["cutoff"]]
    else:
        cutoff = ["--out-range", "-d10"]
    if cfg.get("all_udp"):
        add_wf_udp_value(args, "1024-65535")
        extra += ["--new", "--filter-udp=1024-65535"] + cutoff
    elif cfg.get("ipset"):
        import tempfile
        from core.utils import short_path
        f = Path(tempfile.gettempdir()) / "z2_game_ipset.txt"
        f.write_text("\n".join(IPSET_CIDRS) + "\n", encoding="ascii")
        add_wf_udp_value(args, "1024-65535")
        extra += ["--new", "--filter-udp=1024-65535",
                  f"--ipset={short_path(f)}"] + cutoff
    else:
        for p in cfg.get("ports", []):
            add_wf_udp_value(args, str(p))
        port_csv = ",".join(str(p) for p in cfg.get("ports", []))
        extra += ["--new", f"--filter-udp={port_csv}"] + cutoff
    return extra + list(cfg["desync"])


name = sys.argv[1] if len(sys.argv) > 1 else ""
if name not in VARIANTS:
    print("варианты:", ", ".join(VARIANTS))
    raise SystemExit(1)

args = build_args_from_preset(
    MIR, MIR / "lua", MIR / "blobs", MIR / "presets" / "default-alt.txt",
    lists_dir=MIR / "lists", windivert_dir=MIR / "windivert",
    debug=False, game_filter_mode="off", discord_voice=False,
    discord_voice_mode="", autohostlist=False, ipset_catchall=False)
args += build_extra(VARIANTS[name])

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
print(f"variant={name} winws2={'RUNNING' if alive else 'NOT RUNNING'}")
