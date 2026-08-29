"""Assemble the 'portable' distribution — GUI with NO packer at all.

The GUI runs on the official Python embeddable runtime (pythonw.exe, signed
by the Python Software Foundation, white Defender reputation).  Our code
sits next to it as plain .py files — no PyInstaller bootloader, no temp
extraction, nothing for Defender's cloud heuristics to key on.

Layout:
  portable/
  ├── app/            <- our app (main.pyw, core/, server/, frontend/, data dirs)
  ├── python/         <- python-3.13.x-embed-amd64 + pywebview
  ├── install.cmd     <- one-time: creates desktop + Start menu shortcuts
  └── README.txt

Usage: python build_portable.py   (run from the repo root)
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
PORTABLE = ROOT / "portable"
APP = PORTABLE / "app"
PY = PORTABLE / "python"

PY_VER = "3.13.14"
PY_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
PY_SHORT = "".join(PY_VER.split(".")[:2])  # 3.13.14 -> 313 (dll/pth use short form)

COPY_DIRS = ("bin", "blobs", "lua", "lists", "presets", "windivert", "frontend", "core", "server")

INSTALL_CMD = r"""@echo off
setlocal
cd /d "%~dp0"

echo Creating shortcuts...
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$icon = '%~dp0app\frontend\logo.ico';" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$start = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs';" ^
  "foreach ($dir in @($desktop, $start)) {" ^
  "  $s = $ws.CreateShortcut((Join-Path $dir 'Zapret 2 GUI.lnk'));" ^
  "  $s.TargetPath = '%~dp0python\pythonw.exe';" ^
  "  $s.Arguments = 'main.pyw';" ^
  "  $s.WorkingDirectory = '%~dp0app';" ^
  "  $s.IconLocation = $icon;" ^
  "  $s.Save();" ^
  "}"

echo Done. Shortcuts 'Zapret 2 GUI' created on Desktop and in Start Menu.
pause
"""

README_TXT = """Zapret 2 GUI - portable version (no packer, official Python runtime)

Как установить:
  1. Запустите install.cmd ОДИН раз - создаст ярлык 'Zapret 2 GUI'
     на рабочем столе и в меню Пуск.
  2. Запускайте обход через ярлык (от имени администратора
     запросится автоматически).

Ничего не требует установки в систему (кроме драйвера WinDivert
при первом запуске - стандартное предупреждение Windows).

Обновление версии: замените папку app\\ новыми файлами (сохраняются
ваши правки в lists\\presets - просто не удаляйте их).
"""


def _download(url: str, dest: pathlib.Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    print(f"downloading {url}")
    urllib.request.urlretrieve(url, dest)


def main() -> None:
    if PORTABLE.exists():
        shutil.rmtree(PORTABLE)
    PORTABLE.mkdir()
    APP.mkdir()

    # 1. python embeddable runtime
    PY.mkdir()
    tmp_zip = ROOT / "build" / "python-embed.zip"
    tmp_zip.parent.mkdir(exist_ok=True)
    _download(PY_URL, tmp_zip)
    with zipfile.ZipFile(tmp_zip) as zf:
        zf.extractall(PY)
    # allow site-packages
    pth = PY / f"python{PY_SHORT}._pth"
    pth.write_text(f"python{PY_SHORT}.zip\n.\nLib\\site-packages\nimport site\n", encoding="ascii")

    # 2. pip + pywebview
    pip_script = ROOT / "build" / "get-pip.py"
    _download(PIP_URL, pip_script)
    subprocess.run([str(PY / "python.exe"), str(pip_script), "--no-warn-script-location"],
                   check=True)
    subprocess.run([str(PY / "python.exe"), "-m", "pip", "install", "--no-warn-script-location",
                    "pywebview"], check=True)

    # 3. app code
    for d in COPY_DIRS:
        shutil.copytree(ROOT / d, APP / d)
    shutil.copy2(ROOT / "main.py", APP / "main.pyw")

    # 4. trim runtime (caches, tests, pip scripts)
    for junk in (PY / "Scripts", PY / "Lib" / "site-packages" / "pip" / "_vendor" / "cache"):
        shutil.rmtree(junk, ignore_errors=True)
    for p in PY.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
    for p in APP.rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)

    # 5. installer + readme
    (PORTABLE / "install.cmd").write_text(INSTALL_CMD, encoding="ascii")
    (PORTABLE / "README.txt").write_text(README_TXT, encoding="utf-8")

    # 6. zip + sha256
    out_zip = ROOT / "Windows build" / "Zapret2GUI-portable.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(PORTABLE.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(PORTABLE))
    import hashlib
    sha = hashlib.sha256(out_zip.read_bytes()).hexdigest()
    (ROOT / "Windows build" / "Zapret2GUI-portable.zip.sha256").write_text(sha + "\n", encoding="ascii")
    print(f"OK: {out_zip}  ({out_zip.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"SHA256: {sha}")


if __name__ == "__main__":
    main()