# -*- mode: python ; coding: utf-8 -*-
"""Spec exe-сборки Zapret2GUI (onefile).

Зачем свой spec: PyInstaller сканирует наши bin/*.exe/.dll (они добавляются
как data) как PE и подтягивает их импорты — winws2.exe требует cygwin1.dll и
WinDivert.dll, и они попадают в корень архива ВТОРОЙ копией (первые уже лежат
в bin\\ через datas). Выкидываем корневые дубликаты и документацию pythonnet.
"""
import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve()
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
    version=str(ROOT / "version_info.txt"),
)
