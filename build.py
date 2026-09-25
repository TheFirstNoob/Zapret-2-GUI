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

# datas/excludes живут в Zapret2GUI.spec (там же фильтр корневых дубликатов)

# lists попадают в onefile через staging: user-файлы обнуляются, чтобы данные
# разработчика не утекли в дистрибутив (как в portable/lite)
REL_LISTS = ROOT / "build" / "lists_release"
if REL_LISTS.exists():
    shutil.rmtree(REL_LISTS)
shutil.copytree(ROOT / "lists", REL_LISTS)
for name in ("list-include-user", "list-exclude-user",
             "ipset-include-user", "ipset-exclude-user",
             "list-games", "list-include-all"):
    (REL_LISTS / f"{name}.txt").write_text("", encoding="utf-8")
# Пул-файлы игр (lists/games/*) - рантайм конкретной машины, в релиз не идут
shutil.rmtree(REL_LISTS / "games", ignore_errors=True)

PyInstaller.__main__.run([
    "--noconfirm",
    "--clean",
    "--distpath", str(DIST),
    # workpath отдельно от staging (build/presets_release, build/lists_release):
    # --clean не должен трогать подготовленные данные
    "--workpath", str(ROOT / "build" / "pyi"),
    str(ROOT / "Zapret2GUI.spec"),
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
