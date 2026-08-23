import subprocess
import time
from pathlib import Path
from typing import Optional


SERVICE_NAME = "zapret2"


def _sc(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["sc"] + args,
            capture_output=True, text=True, encoding="oem", errors="replace", timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return -1, "sc not found"


def _taskkill_winws2():
    subprocess.run(
        ["taskkill", "/F", "/IM", "winws2.exe"],
        capture_output=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _winws2_running() -> bool:
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq winws2.exe"],
        capture_output=True, text=True, encoding="oem", errors="replace", timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    # if winws2.exe appears in output (not just the header), it's running
    return "winws2.exe" in r.stdout and "No tasks" not in r.stdout


def is_installed() -> bool:
    code, _ = _sc(["query", SERVICE_NAME])
    return code == 0


def status() -> str:
    code, out = _sc(["query", SERVICE_NAME])
    if code != 0:
        return "not_installed"
    # Parse SCM state from sc query output
    for line in out.splitlines():
        if "STATE" in line:
            if "RUNNING" in line:
                return "running"
            return "stopped"
    return "stopped"


def _zapret1_service_exists() -> bool:
    code, _ = _sc(["query", "zapret"])
    return code == 0


def install(root_dir: Optional[Path] = None) -> tuple[bool, str]:
    if _zapret1_service_exists():
        return False, ("Обнаружена служба Zapret 1 (zapret). "
            "Пожалуйста, удалите её через service.bat от Zapret 1 перед установкой службы Zapret 2.")
    remove()
    time.sleep(0.5)
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent
    bat = root_dir / "_zapret_service.bat"
    if not bat.exists():
        return False, "Сначала создайте _zapret_service.bat"
    binpath = f'"cmd.exe" /C "{bat}"'
    code, out = _sc(["create", SERVICE_NAME,
        "binPath=", binpath,
        "DisplayName=", "Zapret 2 DPI Bypass",
        "start=", "auto",
    ])
    if code != 0:
        return False, f"sc create failed: {out.strip()}"
    _sc(["description", SERVICE_NAME, "zapret DPI bypass (Zapret 2)"])
    start()
    return True, "Служба zapret2 установлена"


def remove():
    _taskkill_winws2()
    time.sleep(0.5)
    _sc(["delete", SERVICE_NAME])
    return True, "Служба zapret2 удалена"


def start():
    _taskkill_winws2()
    time.sleep(0.5)
    code, out = _sc(["start", SERVICE_NAME])
    if code != 0:
        return False, f"sc start failed: {out.strip()}"
    return True, "winws2 запущен"


def stop():
    _taskkill_winws2()
    return True, "winws2 остановлен"


def build_service_bat(root_dir: Path, exe_path: Path, args: list[str]) -> Path:
    root_dir = Path(root_dir)
    args_str = subprocess.list2cmdline(args)
    bat_path = root_dir / "_zapret_service.bat"
    lines = [
        "@echo off",
        'cd /d "%~dp0"',
        f'start /b /wait "" "{exe_path}" {args_str} > nul 2>&1',
    ]
    bat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bat_path
