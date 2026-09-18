"""Cold-start measurement: первый успех updates.discord.com после запуска
winws2 на выбранном пресете/варианте. Не меняет файлы репозитория — вариант
задаётся модификаторами аргументов.

Запуск: python _measure_cold.py default | default_nodrop202 | default_rep7 | ...
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

MIR = Path(r"C:\Users\TheFirstNoob\Desktop\Zapret 2 GUI\zapret2_gui")
REPO = Path(r"C:\Users\TheFirstNoob\Documents\GitHub\Zapret-2-GUI")
sys.path.insert(0, str(REPO))

from core.launcher import build_args_from_preset   # noqa: E402
from core.launcher import validate_args            # noqa: E402
from core import service_manager                   # noqa: E402

VARIANTS = {
    # как сейчас (repeats=8 nodrop Discord)
    "current": [],
    # 0.2-стиль: Discord блоки без repeats, nodrop; Google/General как сейчас
    "discord_0_2": [
        ("replace", "fake:blob=google_tls:tcp_ts=-1000:repeats=8:nodrop:tls_mod=rnd,dupsid",
         "fake:blob=google_tls:tcp_ts=-1000:nodrop"),
        ("replace", "multisplit:pos=1:seqovl=681:seqovl_pattern=google_tls:repeats=8:nodrop",
         "multisplit:pos=1:seqovl=681:seqovl_pattern=google_tls:nodrop"),
    ],
    # repeats=7 вместо 8 (порог 09-10)
    "rep7": [
        ("replace", "repeats=8", "repeats=7"),
    ],
    # A3: Discord без nodrop (drop оригинала), repeats=8
    "discord_nodropoff": [
        ("replace", "repeats=8:nodrop", "repeats=8"),
    ],
}


def build(kind: str, profile: str = "default"):
    args = build_args_from_preset(
        MIR, MIR / "lua", MIR / "blobs", MIR / "presets" / f"{profile}.txt",
        lists_dir=MIR / "lists", windivert_dir=MIR / "windivert",
        debug=False, game_filter_mode="off", discord_voice=False,
        discord_voice_mode="", autohostlist=False, ipset_catchall=False)
    for (mode, old, new) in VARIANTS.get(kind, []):
        args = [a.replace(old, new) if isinstance(a, str) else a for a in args]
    ok, err = validate_args(MIR / "bin" / "winws2.exe", args, cwd=MIR)
    if not ok:
        raise RuntimeError(f"validate fail: {err}")
    return args


def launch(args) -> subprocess.Popen:
    bat = MIR / "_measure_run.bat"
    cmd = 'start "m" /min "%~dp0bin\\winws2.exe" ' + " ".join(
        f'"{a}"' for a in args)
    bat.write_text("@echo off\r\ncd /d \"%~dp0\"\r\n" + cmd + "\r\n",
                   encoding="ascii")
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(MIR),
                     creationflags=0x08000000)
    # ждём появления winws2
    for _ in range(50):
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq winws2.exe"],
                           capture_output=True, text=True,
                           creationflags=0x08000000)
        if "winws2.exe" in (r.stdout or ""):
            return
        time.sleep(0.2)


def launch_winws2(args) -> None:
    bat = MIR / "_measure_run.bat"
    cmd = 'start "m" /min "%~dp0bin\\winws2.exe" ' + " ".join(
        f'"{a}"' for a in args)
    bat.write_text("@echo off\r\ncd /d \"%~dp0\"\r\n" + cmd + "\r\n",
                   encoding="ascii")
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(MIR),
                     creationflags=0x08000000)
    # ждём появления winws2
    for _ in range(50):
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq winws2.exe"],
                           capture_output=True, text=True,
                           creationflags=0x08000000)
        if "winws2.exe" in (r.stdout or ""):
            return
        time.sleep(0.2)


def probe_cold(host: str, attempts: int = 6) -> tuple[float, int]:
    """Первый HTTP>=100 к host; возвращает (сек, попытка)."""
    for i in range(1, attempts + 1):
        t0 = time.time()
        r = subprocess.run(
            ["curl.exe", "-4", "-s", "-o", "NUL", "-m", "8",
             "-w", "%{http_code}", f"https://{host}/"],
            capture_output=True, text=True, encoding="oem", errors="replace",
            creationflags=0x08000000)
        code = (r.stdout or "").strip()
        if code.isdigit() and int(code) >= 100:
            return time.time() - t0, i
        time.sleep(0.5)
    return -1, attempts


def main():
    kinds = sys.argv[1:] or list(VARIANTS)
    service_manager.stop()
    for kind in kinds:
        args = build(kind)
        subprocess.run(["taskkill", "/F", "/IM", "winws2.exe"],
                       capture_output=True, creationflags=0x08000000)
        time.sleep(1.5)
        launch_winws2(args)
        time.sleep(1.5)  # даём WinDivert инициализироваться
        t_cold, a_cold = probe_cold("updates.discord.com")
        # тёплый повтор (тот же пресет работает)
        t_warm, a_warm = probe_cold("updates.discord.com", attempts=2)
        print(f"[{kind}] cold={t_cold:.1f}s(#{a_cold}) warm={t_warm:.1f}s(#{a_warm})")
        subprocess.run(["taskkill", "/F", "/IM", "winws2.exe"],
                       capture_output=True, creationflags=0x08000000)
        time.sleep(1.2)
    print("=== done ===")


if __name__ == "__main__":
    main()
