"""Публикация релиза на GitHub (политика ассетов с 0.11: только pretty-имена).

Почему pretty-only (решение 2026-10-10, дубли 0.10 больше не повторяем):
- клиенты 0.10+ пробуют primary-кандидатов [pretty -> каноническое]:
  pretty на релизе — попадание с первого раза;
- канонические имена остаются в git (`Windows build/` в теге) и доступны
  через jsDelivr-зеркало: страховка для старых клиентов/сетей;
- 0.8/0.9 автообновлением не пользуются (кнопка там мертва) — их primary-
  фолбэк не нужен, ручные скачивания видят только pretty.

Сборка архива НЕ здесь: сначала build.py / build_portable.py / build_lite.py
и sign_release.py, потом этот инструмент.

Запуск:
  python tools/release_publish.py --version 0.11 --tag Pre-Release-0.11 \
      --notes "C:\\path\\changelog.md" [--keep-draft]

Пайплайн: draft -> загрузка 8 ассетов -> проверка комплектности -> publish.
Публикация только после успешной проверки (релиз immutable после publish).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OWNER_REPO = "TheFirstNoob/Zapret-2-GUI"
API = "https://api.github.com"

# kind -> (файл в Windows build, pretty-имя на релизе)
ASSETS = {
    "exe": ("Zapret2GUI.zip", "Zapret2GUI-Full-PyInstaller.zip"),
    "portable": ("Zapret2GUI-portable.zip",
                 "Zapret2GUI-portable-Recommended.zip"),
    "lite": ("Zapret2GUI-lite.zip", "Zapret2GUI-lite-CMD.zip"),
}


def _sha256(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_version(text: str) -> str:
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text or "")
    return m.group(1) if m else ""


def _verify_release_inputs(version: str, tag: str) -> list[str]:
    """Fail-closed проверка ПЕРЕД публикацией (аудит 2026-11-14, P1).

    Раньше stale release.json 0.10 под тегом 0.11 уезжал в immutable-релиз
    (dry-run exit 0). Проверяем: VERSION/tag/manifest согласованы, подпись
    валидна, sha256/size артефактов совпадают с manifest и файлами."""
    errors: list[str] = []
    ver = _norm_version(version)
    if not ver or _norm_version(tag) != ver:
        errors.append(f"версия и тег не согласованы: {version} / {tag}")
    try:
        vtext = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as e:
        errors.append(f"нет VERSION: {e}")
        vtext = ""
    if vtext and _norm_version(vtext) != ver:
        errors.append(f"VERSION в репо ({vtext!r}) != {version!r}")
    man_path = REPO / "release.json"
    sig_path = REPO / "release.json.sig"
    if not man_path.exists() or not sig_path.exists():
        return errors + ["нет release.json/release.json.sig - сначала sign_release.py"]
    raw = man_path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return errors + [f"release.json повреждён: {e}"]
    if _norm_version(manifest.get("version", "")) != ver:
        errors.append(f"release.json.version={manifest.get('version')!r} != {version!r}")
    if manifest.get("tag") != tag:
        errors.append(f"release.json.tag={manifest.get('tag')!r} != {tag!r}")
    try:
        sys.path.insert(0, str(REPO))
        from core.update_verify import verify as _verify_sig
        if not _verify_sig(raw, sig_path.read_text(encoding="ascii").strip()):
            errors.append("подпись release.json не проходит проверку")
    except Exception as e:  # noqa: BLE001
        errors.append(f"не удалось проверить подпись: {e}")
    arts = manifest.get("artifacts") or {}
    for kind, (canon, _pretty) in ASSETS.items():
        art = arts.get(kind)
        if not art:
            errors.append(f"в manifest нет артефакта {kind}")
            continue
        src = REPO / "Windows build" / canon
        if not src.exists():
            errors.append(f"нет {src}")
            continue
        if art.get("sha256") != _sha256(src):
            errors.append(f"sha256 {canon} не совпадает с manifest")
        if int(art.get("size", -1)) != src.stat().st_size:
            errors.append(f"size {canon} не совпадает с manifest")
    return errors


def _token() -> str:
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, cwd=str(REPO)).stdout
    m = re.search(r"password=(.+)", out)
    if not m:
        raise SystemExit("нет токена в git credential fill")
    return m.group(1).strip()


def _api(token: str, method: str, url: str, data=None,
         ctype: str = "application/json"):
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("User-Agent", "Zapret2GUI-release")
    req.add_header("Accept", "application/vnd.github+json")
    if body is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        print(f"HTTP {e.code} {method} {url}: {detail}")
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help='например "0.11"')
    ap.add_argument("--tag", required=True, help="например Pre-Release-0.11")
    ap.add_argument("--notes", type=Path, default=None,
                    help="файл описания релиза (ченджлог)")
    ap.add_argument("--keep-draft", action="store_true",
                    help="остановиться после проверки ассетов (без publish)")
    ap.add_argument("--dry-run", action="store_true",
                    help="только собрать stage и показать список (без GitHub)")
    args = ap.parse_args()

    verify_errors = _verify_release_inputs(args.version, args.tag)
    if verify_errors:
        print("ПРОВАЛ: входные данные релиза не готовы к публикации:")
        for e in verify_errors:
            print("  -", e)
        return 1

    stage = REPO / "build" / "release_stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    sha_lines = []
    files: list[Path] = []
    for _kind, (canon, pretty) in ASSETS.items():
        src = REPO / "Windows build" / canon
        if not src.exists():
            raise SystemExit(f"нет {src} — сначала сборка")
        sha = (REPO / "Windows build" / f"{canon}.sha256").read_text(
            encoding="ascii").strip()
        (stage / pretty).write_bytes(src.read_bytes())
        (stage / f"{pretty}.sha256").write_text(sha + "\n", encoding="ascii")
        files += [stage / pretty, stage / f"{pretty}.sha256"]
        sha_lines.append(f"{pretty:36s} {sha}")
    for n in ("release.json", "release.json.sig"):
        if not (REPO / n).exists():
            raise SystemExit(f"нет {n} — сначала sign_release.py")
        (stage / n).write_bytes((REPO / n).read_bytes())
        files.append(stage / n)

    body = ""
    if args.notes and args.notes.exists():
        body = args.notes.read_text(encoding="utf-8") + "\n\n"
    body += "---\n\n### SHA256\n\n```\n" + "\n".join(sha_lines) + "\n```\n"

    if args.dry_run:
        print(f"dry-run: {len(files)} ассетов (pretty-only):")
        for p in files:
            print(f"  {p.name} ({p.stat().st_size} B)")
        print(f"body: {len(body)} символов")
        return 0

    token = _token()

    existing = None
    try:
        existing = _api(token, "GET",
                        f"{API}/repos/{OWNER_REPO}/releases/tags/{args.tag}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    if existing:
        if not existing.get("draft"):
            print("ПРОВАЛ: релиз уже опубликован (immutable) — менять нельзя")
            return 1
        print(f"удаляю старый draft id={existing['id']}")
        _api(token, "DELETE",
             f"{API}/repos/{OWNER_REPO}/releases/{existing['id']}")

    rel = _api(token, "POST", f"{API}/repos/{OWNER_REPO}/releases", {
        "tag_name": args.tag,
        "name": (f"Pre-Release {args.version}"
                 if args.tag.startswith("Pre-Release") else args.tag),
        "body": body, "draft": True, "prerelease": True,
        "target_commitish": "main",
    })
    rid = rel["id"]
    print(f"draft id={rid} (prerelease=True)")

    up = rel["upload_url"].split("{", 1)[0]
    for p in files:
        _api(token, "POST", f"{up}?name={urllib.parse.quote(p.name)}",
             p.read_bytes(), ctype="application/octet-stream")
        print(f"  uploaded: {p.name} ({p.stat().st_size} B)")

    chk = _api(token, "GET", f"{API}/repos/{OWNER_REPO}/releases/{rid}")
    got = sorted(a["name"] for a in chk["assets"])
    want = sorted(p.name for p in files)
    if got != want:
        print("ПРОВАЛ комплектности — draft оставлен, publish НЕ делаю")
        print("нет:", sorted(set(want) - set(got)))
        print("лишние:", sorted(set(got) - set(want)))
        return 1
    print(f"комплектность OK ({len(got)}/{len(want)}, pretty-only)")

    if args.keep_draft:
        print("--keep-draft: публикацию не делаю")
        return 0
    pub = _api(token, "PATCH", f"{API}/repos/{OWNER_REPO}/releases/{rid}",
               {"draft": False})
    print(f"ОПУБЛИКОВАН: prerelease={pub['prerelease']} "
          f"assets={len(pub['assets'])}")
    print("url:", pub["html_url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
