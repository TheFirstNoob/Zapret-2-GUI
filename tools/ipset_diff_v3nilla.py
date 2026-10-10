"""Сравнение ipset-базы с V3nilla/IPSets-For-Bypass-in-Russia (coverage-diff).

Зачем: строковое сравнение врёт (у них /12 там, где у нас набор /16..), нужен
честный дифф «какие АДРЕСА есть у них и не покрыты нами» и наоборот.

ВНИМАНИЕ: инструмент только ПОКАЗЫВАЕТ расхождения. Не вливать целиком:
слепое слияние ломает break-класс (DO/Hetzner/OVH) - см.
AI_DOCS/IPSETS_V3NILLA.md (правила) и CDN A/B после любого применения.

Запуск:  python tools/ipset_diff_v3nilla.py [--refresh] [--top 30]
Выход:   stdout-отчёт + файлы в %TEMP%/opencode/ipset_diff_v3nilla/:
         report.txt, theirs_only.txt, ours_only.txt
"""
from __future__ import annotations

import argparse
import gzip
import ipaddress
import pathlib
import re
import sys
import urllib.request

_REPO = pathlib.Path(__file__).resolve().parent.parent
_CACHE = pathlib.Path.home() / "AppData/Local/Temp/opencode/ipset_diff_v3nilla"
_V3_BASE = ("https://cdn.jsdelivr.net/gh/V3nilla/"
            "IPSets-For-Bypass-in-Russia@main/")
_UA = {"User-Agent": "Zapret2GUI-ipset-diff"}
_C4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")


def _download(name: str, refresh: bool) -> pathlib.Path:
    dest = _CACHE / name
    if dest.exists() and not refresh:
        return dest
    _CACHE.mkdir(parents=True, exist_ok=True)
    print(f"  [download] {name}")
    req = urllib.request.Request(_V3_BASE + name, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())
    return dest


def _load_cidrs(path: pathlib.Path, gz: bool = False) -> set[str]:
    if gz:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    out = set()
    for ln in text.splitlines():
        ln = ln.split("#", 1)[0].strip()
        if _C4.match(ln):
            out.add(ln)
    return out


def _to_intervals(cidrs: set[str]) -> list[tuple[int, int]]:
    iv = []
    for c in cidrs:
        n = ipaddress.ip_network(c, strict=False)
        iv.append((int(n.network_address), int(n.broadcast_address)))
    iv.sort()
    merged: list[list[int]] = []
    for s, e in iv:
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _subtract(a: list[tuple[int, int]],
              b: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """A минус B (интервалы отсортированы и слиты)."""
    out: list[tuple[int, int]] = []
    j = 0
    for s, e in a:
        cur = s
        while j < len(b) and b[j][1] < cur:
            j += 1
        k = j
        while k < len(b) and b[k][0] <= e:
            bs, be = b[k]
            if bs > cur:
                out.append((cur, min(bs - 1, e)))
            cur = max(cur, be + 1)
            if cur > e:
                break
            k += 1
        if cur <= e:
            out.append((cur, e))
    return out


def _intervals_to_cidrs(iv: list[tuple[int, int]]) -> list[str]:
    out: list[str] = []
    for s, e in iv:
        out += [str(n) for n in ipaddress.summarize_address_range(
            ipaddress.ip_address(s), ipaddress.ip_address(e))]
    return out


def _exclude_domains_diff(refresh: bool) -> list[str]:
    lines: list[str] = []
    try:
        theirs = {ln.strip().lower() for ln in _download(
            "exclude-domains.txt", refresh).read_text(
            encoding="utf-8", errors="replace").splitlines()
            if ln.strip() and not ln.strip().startswith("#")}
        ours = {ln.split("#", 1)[0].strip().lower()
                for ln in (_REPO / "lists" / "list-exclude.txt").read_text(
                    encoding="utf-8", errors="replace").splitlines()
                if ln.split("#", 1)[0].strip()}
        lines.append("=== exclude-domains: есть у них, нет у нас ===")
        for d in sorted(theirs - ours):
            lines.append(f"  {d}")
        lines.append(f"=== в наших list-exclude нет их у нас: {len(ours - theirs)} "
                     "доменов (свои банки/сервисы - норм) ===")
    except Exception as e:  # noqa: BLE001
        lines.append(f"exclude-domains: не сравнить ({e})")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="перекачать v3nilla-файлы, игнорируя кэш")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    print("== загрузка ==")
    theirs_cidrs = _load_cidrs(_download("ipset-all.txt", args.refresh))
    ours_cidrs = _load_cidrs(_REPO / "lists" / "ipset-all.txt.gz", gz=True)
    print(f"  V3nilla: {len(theirs_cidrs)} CIDR | наш: {len(ours_cidrs)} CIDR")

    ti = _to_intervals(theirs_cidrs)
    oi = _to_intervals(ours_cidrs)
    theirs_only = _subtract(ti, oi)
    ours_only = _subtract(oi, ti)

    tc = _intervals_to_cidrs(theirs_only)
    oc = _intervals_to_cidrs(ours_only)
    t_addr = sum(e - s + 1 for s, e in theirs_only)
    o_addr = sum(e - s + 1 for s, e in ours_only)

    report: list[str] = []
    report.append("=== coverage-diff (адреса, а не строки) ===")
    report.append(f"у них есть, нами НЕ покрыто:  {t_addr:>12,} адр. "
                  f"в {len(tc)} CIDR")
    report.append(f"у нас есть, ими НЕ покрыто:   {o_addr:>12,} адр. "
                  f"в {len(oc)} CIDR")
    report.append("")
    report.append(f"--- топ-{args.top} «у них есть, у нас нет» ---")
    for n in sorted((ipaddress.ip_network(c) for c in tc),
                    key=lambda x: x.num_addresses, reverse=True)[:args.top]:
        report.append(f"  {str(n):<20} {n.num_addresses:>10,} адр.")
    report.append("")
    report.append(f"--- топ-{args.top} «у нас есть, у них нет» ---")
    for n in sorted((ipaddress.ip_network(c) for c in oc),
                    key=lambda x: x.num_addresses, reverse=True)[:args.top]:
        report.append(f"  {str(n):<20} {n.num_addresses:>10,} адр.")
    report.append("")
    report += _exclude_domains_diff(args.refresh)

    out_dir = _CACHE
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.txt").write_text("\n".join(report) + "\n",
                                        encoding="utf-8")
    (out_dir / "theirs_only.txt").write_text("\n".join(tc) + "\n",
                                             encoding="utf-8")
    (out_dir / "ours_only.txt").write_text("\n".join(oc) + "\n",
                                           encoding="utf-8")
    print("\n".join(report))
    print(f"\nфайлы: {out_dir}\\report.txt | theirs_only.txt | ours_only.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
