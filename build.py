from __future__ import annotations

import os
import shutil
import PyInstaller.__main__
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
NAME = "Zapret2GUI"

# Экспериментальные пресеты и генерируемый custom не попадают в дистрибутив
RELEASE_PRESETS = lambda name: not name.startswith(
    ("exp-", "cand-", "test-", "custom"))

# presets попадают в onefile отфильтрованными через build/presets_release.
REL_PRESETS = ROOT / "build" / "presets_release"
if REL_PRESETS.exists():
    shutil.rmtree(REL_PRESETS)
REL_PRESETS.mkdir(parents=True)
for pf in sorted((ROOT / "presets").glob("*.txt")):
    if RELEASE_PRESETS(pf.stem):
        shutil.copy2(pf, REL_PRESETS / pf.name)

ADD_DATA = []
for d in ("bin", "blobs", "lua", "lists", "windivert", "frontend"):
    src = str(ROOT / d)
    dst = d
    ADD_DATA.append(f"{src}{os.pathsep}{dst}")
ADD_DATA.append(f"{str(REL_PRESETS)}{os.pathsep}presets")

# Packages not needed at runtime – pulled in by PyInstaller hooks/build-time deps
EXCLUDE = [
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

PyInstaller.__main__.run([
    "--onefile",
    "--noconsole",
    "--name", NAME,
    "--distpath", str(DIST),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
    "--noconfirm",
    "--clean",
    "--icon", str(ROOT / "frontend" / "logo.ico"),
    "--version-file", str(ROOT / "version_info.txt"),
    "--log-level", "WARN",
    *[f"--exclude-module={e}" for e in EXCLUDE],
    *[f"--add-data={a}" for a in ADD_DATA],
    str(ROOT / "main.py"),
])

out = DIST / f"{NAME}.exe"
print(f"OK: {out}  ({out.stat().st_size / 1024 / 1024:.1f} MB)")

# sha256 + zip рядом (для авто-обновления из программы: exe-версия
# обновляется заменой exe-файла, архив скачивается из release-ассетов)
import hashlib
import zipfile
out_zip = ROOT / "Windows build" / "Zapret2GUI.zip"
with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write(out, f"{NAME}.exe")
    for src_name, dst_name in (("LICENSE", "LICENSE.txt"),
                               ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.txt")):
        src = ROOT / src_name
        if src.exists():
            zf.write(src, dst_name)
sha = hashlib.sha256(out_zip.read_bytes()).hexdigest()
(ROOT / "Windows build" / "Zapret2GUI.zip.sha256").write_text(sha + "\n", encoding="ascii")
print(f"OK: {out_zip}  ({out_zip.stat().st_size / 1024 / 1024:.1f} MB)")
print(f"SHA256: {sha}")
