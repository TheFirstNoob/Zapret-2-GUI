# -*- mode: python ; coding: utf-8 -*-
"""Spec exe-сборки Zapret2GUI (onefile).

Зачем свой spec: PyInstaller сканирует наши bin/*.exe/.dll (они добавляются
как data) как PE и подтягивает их импорты — winws2.exe требует cygwin1.dll и
WinDivert.dll, и они попадают в корень архива ВТОРОЙ копией (первые уже лежат
в bin\\ через datas). Выкидываем корневые дубликаты и документацию pythonnet.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

# Версия exe-файла — из core.config.VERSION (единый источник; статический
# version_info.txt больше не протухает)
def _gen_version_file() -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from core.config import VERSION as ver
    except Exception:
        return str(ROOT / "version_info.txt")
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", ver or "")
    n = [int(x) if x else 0 for x in (m.groups() if m else (0, 0, 0))]
    quad = tuple((n + [0, 0, 0, 0])[:4])
    out = ROOT / "build" / "version_info.gen"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers={quad},\n"
        f"    prodvers={quad},\n"
        "    mask=0x3f,\n    flags=0x0,\n    OS=0x40004,\n"
        "    fileType=0x1,\n    subtype=0x0,\n    date=(0, 0)\n  ),\n"
        "  kids=[\n    StringFileInfo([\n      StringTable('040904B0', [\n"
        "        StringStruct('CompanyName', 'Zapret 2 GUI'),\n"
        "        StringStruct('FileDescription', 'Zapret 2 DPI bypass GUI'),\n"
        f"        StringStruct('FileVersion', '{'.'.join(map(str, quad))}'),\n"
        "        StringStruct('InternalName', 'Zapret2GUI'),\n"
        "        StringStruct('LegalCopyright', 'Open source (MIT)'),\n"
        "        StringStruct('OriginalFilename', 'Zapret2GUI.exe'),\n"
        "        StringStruct('ProductName', 'Zapret 2 GUI'),\n"
        f"        StringStruct('ProductVersion', {ver!r})\n"
        "      ])\n    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n)\n", encoding="utf-8")
    return str(out)


VERSION_FILE = _gen_version_file()
NAME = "Zapret2GUI"

DATAS = []
for d in ("bin", "blobs", "lua", "windivert", "frontend"):
    DATAS.append((str(ROOT / d), d))
DATAS.append((str(ROOT / "build" / "presets_release"), "presets"))
DATAS.append((str(ROOT / "build" / "lists_release"), "lists"))

EXCLUDES = [
    # pywebview статически упоминает cryptography (try/except), а проверка
    # подписи у нас на stdlib: ~15 МБ мусора в exe.
    "cryptography",
    "bcrypt",
    "numpy",
    "PIL",
    "pygments",
    "setuptools",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    "starlette",
    "starlette.websockets",
    "fastapi",
    "pydantic",
    "pydantic.v1",
    "pydantic_core",
    "h11",
    "httptools",
    "anyio",
    "sniffio",
    "multipart",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=[],
    hookspath=[],
    excludes=EXCLUDES,
    noarchive=False,
)

# Корневые дубликаты зависимостей winws2 (в bin\ они уже есть как data)
DROP_ROOT = {"cygwin1.dll", "WinDivert.dll"}
a.binaries = [
    b for b in a.binaries
    if b[0] not in DROP_ROOT
]
# Документация pythonnet (xml) не нужна в рантайме — она в datas
a.datas = [
    d for d in a.datas
    if not d[0].replace("\\", "/").endswith("Python.Runtime.xml")
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "frontend" / "logo.ico"),
    version=VERSION_FILE,
)
