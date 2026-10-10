"""Staged-слияние ipset-базы: наша + кандидаты V3nilla -> НЕ трогая релиз.

Пишет только в staging:
  %TEMP%/opencode/ipset_diff_v3nilla/ipset-all-staged.txt.gz
и НЕ заменяет lists/ipset-all.txt.gz. Замена в релиз - только после A/B
(CDN-сканер, ipset_mode, «IP-обход ВКЛ/ВЫКЛ») со сравнением fix/break,
см. AI_DOCS/IPSETS_V3NILLA.md.

Запуск: python tools/ipset_merge_staged.py
"""
from __future__ import annotations

import gzip
import ipaddress
import pathlib

_REPO = pathlib.Path(__file__).resolve().parent.parent
_DIR = (pathlib.Path.home() / "AppData/Local/Temp/opencode/"
        "ipset_diff_v3nilla")
_OURS = _REPO / "lists" / "ipset-all.txt.gz"
_CAND = _DIR / "candidates.txt"
_OUT = _DIR / "ipset-all-staged.txt.gz"


def _load_zip_gz(path: pathlib.Path) -> list[ipaddress.IPv4Network]:
    nets = []
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for ln in f:
            ln = ln.split("#", 1)[0].strip()
            if not ln or "." not in ln:
                continue
            try:
                nets.append(ipaddress.ip_network(ln, strict=False))
            except ValueError:
                pass
    return nets


def main() -> int:
    ours = _load_zip_gz(_OURS)
    cand = [ipaddress.ip_network(ln.strip(), strict=False)
            for ln in _CAND.read_text(encoding="utf-8").splitlines()
            if ln.strip()]

    merged = list(ipaddress.collapse_addresses(ours + cand))
    merged.sort(key=lambda n: (int(n.network_address), n.prefixlen))

    with gzip.open(_OUT, "wt", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(str(n) for n in merged) + "\n")

    a_ours = sum(n.num_addresses for n in ipaddress.collapse_addresses(ours))
    a_merged = sum(n.num_addresses for n in merged)
    size = _OUT.stat().st_size
    print(f"наша база:   {len(ours)} CIDR -> collapse {len(list(ipaddress.collapse_addresses(ours)))}"
          f", {a_ours:,} адресов")
    print(f"кандидаты:   {len(cand)} CIDR, "
          f"{sum(n.num_addresses for n in cand):,} адресов")
    print(f"staged база: {len(merged)} CIDR, {a_merged:,} адресов "
          f"(+{a_merged - a_ours:,} к нашей)")
    print(f"файл: {_OUT} ({size/1024:.0f} KB, gz)")
    print("\nA/B: подменить lists/ipset-all.txt.gz в ЗЕРКАЛЕ на staged, прогнать")
    print("CDN-сканер с ipset_mode (IP-обход), сравнить fix/break с текущей")
    print("базой. Только после этого - замена в репо/релиз.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
