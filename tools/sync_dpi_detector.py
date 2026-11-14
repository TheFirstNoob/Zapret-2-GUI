"""Синхронизация данных dpi-detector (ASN-пробы/белые SNI).

Upstream: Runnin4ik/dpi-detector (MIT). Данные меняются редко, но снимок
нужно обновлять осознанно: сначала --check (дифф), потом --apply.

  python tools/sync_dpi_detector.py            # проверить (без записи)
  python tools/sync_dpi_detector.py --apply    # обновить lists/*

Источники: jsDelivr (основной, без лимитов GitHub API) -> raw.githubusercontent
(fallback). Записываем ровно байты upstream (вместе с trailing newline) и
печатаем sha256/дифф, чтобы обновление было воспроизводимым.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "Runnin4ik/dpi-detector"
UA = {"User-Agent": "Zapret2GUI-sync"}
# local name -> (upstream file, kind)
# local name -> (upstream file, kind). domains.txt upstream НЕ бандлим:
# у нас его никто не читает, а тест 4 «sweep SNI» не реализован (P2).
FILES = {
    "lists/cdn-asn-probes.json": ("tcp16.json", "json"),
    "lists/whitelist-sni.txt": ("whitelist_sni.txt", "lines"),
}
URLS = (
    "https://cdn.jsdelivr.net/gh/{repo}@main/{name}",
    "https://raw.githubusercontent.com/{repo}/main/{name}",
)


def _fetch_all(name: str, timeout: float = 20.0) -> list[tuple[str, bytes]]:
    """Все доступные копии (jsDelivr первым): нужен cross-check от кэша CDN."""
    out: list[tuple[str, bytes]] = []
    last: Exception | None = None
    for tpl in URLS:
        url = tpl.format(repo=REPO, name=name)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if data:
                out.append((url, data))
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    if not out:
        raise RuntimeError(f"не удалось скачать {name}: {last}")
    return out


def _fetch(name: str, timeout: float = 20.0) -> bytes:
    return _fetch_all(name, timeout)[0][1]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse(data: bytes, kind: str):
    text = data.decode("utf-8-sig")
    if kind == "json":
        obj = json.loads(text)
        if not isinstance(obj, list) or not obj:
            raise ValueError("tcp16.json: ожидался непустой список")
        return obj
    return [l for l in text.splitlines() if l.strip()]


def _diff(old, new, kind: str) -> dict:
    if kind == "json":
        old_ids = {str(x.get("id")) for x in old if isinstance(x, dict)}
        new_ids = {str(x.get("id")) for x in new if isinstance(x, dict)}
        return {"added": sorted(new_ids - old_ids),
                "removed": sorted(old_ids - new_ids),
                "old_count": len(old), "new_count": len(new)}
    old_set, new_set = set(old), set(new)
    return {"added": sorted(new_set - old_set),
            "removed": sorted(old_set - new_set),
            "old_count": len(old), "new_count": len(new)}


def check(apply: bool = False) -> int:
    rc = 0
    plan = []
    for local_rel, (upstream_name, kind) in FILES.items():
        local_path = ROOT / local_rel
        sources = _fetch_all(upstream_name)
        data = sources[0][1]
        if len(sources) > 1 and _sha(sources[1][1]) != _sha(data):
            print(f"WARN {upstream_name}: jsDelivr и raw различаются "
                  f"({_sha(data)[:12]} != {_sha(sources[1][1])[:12]}) - "
                  "возможно, кэш CDN; сверяйтесь с raw")
        new = _parse(data, kind)
        old_bytes = local_path.read_bytes() if local_path.exists() else b""
        try:
            old = _parse(old_bytes, kind) if old_bytes else []
        except Exception:  # noqa: BLE001
            old = []
        same = old_bytes == data
        info = {"file": local_rel, "upstream": upstream_name,
                "upstream_sha256": _sha(data), "local_sha256": _sha(old_bytes),
                "identical": same}
        if not same:
            info.update(_diff(old, new, kind))
            rc = 1
        plan.append(info)
        print(json.dumps(info, ensure_ascii=False))
        if apply and not same:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(data)
            print(f"  записан {local_rel} ({len(data)} B)")
    if apply:
        print("ИТОГ: данные обновлены" if rc else "ИТОГ: уже актуально")
    else:
        print("ИТОГ: есть отличия (запустите с --apply)" if rc
              else "ИТОГ: локальные данные совпадают с upstream")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="Синхронизация данных dpi-detector")
    ap.add_argument("--apply", action="store_true", help="записать обновления")
    args = ap.parse_args()
    try:
        return check(args.apply)
    except Exception as e:  # noqa: BLE001
        print(f"ОШИБКА: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())