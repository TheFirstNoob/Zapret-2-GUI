"""Stage-слияние ipset-кандидатов в НОВЫЙ gz (без замены релизной базы).

Правило проекта: слепое вливание V3nilla запрещено (fix/break-классы CDN);
сначала coverage-diff (tools/ipset_diff_v3nilla.py) + отбор
(tools/ipset_candidates.py), затем A/B в режиме IP-обхода и только потом
замена lists/ipset-all.txt.gz. Этот инструмент готовит staged-файл для A/B:

  python tools/ipset_stage_merge.py --candidates <candidates.txt> \
      --out _analysis/upstream-sync/scratch-lead/ipset-all-staged.txt.gz

Пишет staged gz (collapsed, LF, без комментариев) + печатает сводку;
релизную базу НЕ трогает. Флаг --apply-base меняет lists/ipset-all.txt.gz
ТОЛЬКО после успешного A/B (осознанное действие).
"""
from __future__ import annotations

import argparse
import gzip
import ipaddress
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "lists" / "ipset-all.txt.gz"


def load_cidrs(path: Path, gz: bool = False) -> list[ipaddress.IPv4Network]:
    if gz:
        text = gzip.open(path, "rt", encoding="utf-8", errors="replace").read()
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    out: list[ipaddress.IPv4Network] = []
    for ln in text.splitlines():
        ln = ln.split("#", 1)[0].strip()
        if not ln or "." not in ln:
            continue
        try:
            out.append(ipaddress.ip_network(ln, strict=False))
        except ValueError:
            continue
    return out


def write_gz(path: Path, nets: list[ipaddress.IPv4Network]) -> None:
    text = "".join(f"{n.with_prefixlen}\n" for n in nets)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(text.encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage ipset merge (без замены базы)")
    ap.add_argument("--candidates", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base", type=Path, default=BASE,
                    help="исходная база (gz); по умолчанию lists/ipset-all.txt.gz")
    ap.add_argument("--apply-base", action="store_true",
                    help="заменить lists/ipset-all.txt.gz (только после A/B)")
    args = ap.parse_args()
    if not args.candidates.exists():
        print(f"нет {args.candidates} - сначала tools/ipset_diff_v3nilla.py "
              "+ tools/ipset_candidates.py")
        return 1
    base = load_cidrs(args.base, gz=True)
    cand = load_cidrs(args.candidates)
    merged = list(ipaddress.collapse_addresses(base + cand))
    base_addr = sum(n.num_addresses for n in base)
    merged_addr = sum(n.num_addresses for n in merged)
    print(f"base: {len(base)} CIDR / {base_addr:,} адресов")
    print(f"candidates: {len(cand)} CIDR / {sum(n.num_addresses for n in cand):,} адресов")
    print(f"merged: {len(merged)} CIDR / {merged_addr:,} адресов "
          f"(+{merged_addr - base_addr:,})")
    write_gz(args.out, merged)
    print(f"staged -> {args.out} ({args.out.stat().st_size:,} B)")
    print("Дальше: A/B в режиме IP-обхода по правилам AI_DOCS/IPSETS_V3NILLA.md; "
          "только после этого --apply-base.")
    if args.apply_base:
        write_gz(BASE, merged)
        print(f"BASE ОБНОВЛЕНА: {BASE} ({BASE.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())