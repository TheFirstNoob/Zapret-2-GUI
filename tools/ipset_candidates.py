"""Отбор кандидатов для слияния в ipset-базу из theirs_only (V3nilla).

Вход:  %TEMP%/opencode/ipset_diff_v3nilla/theirs_only.txt
       (генерирует tools/ipset_diff_v3nilla.py)
Выход: candidates.txt + candidates_report.txt (в той же папке).

Правила: вычитаем ipset-exclude (приватные/служебные) и не-роутабельные
диапазоны; всё остальное — кандидаты. НИЧЕГО не вливаем автоматически:
следующий шаг — staged-слияние + A/B в режиме IP-обход (catch-all) через
CDN-сканер, см. AI_DOCS/IPSETS_V3NILLA.md.
"""
from __future__ import annotations

import ipaddress
import pathlib
import sys

_DEFAULT_DIR = (pathlib.Path.home() / "AppData/Local/Temp/opencode/"
                "ipset_diff_v3nilla")
_REPO = pathlib.Path(__file__).resolve().parent.parent

_RESERVED = [ipaddress.ip_network(x) for x in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
    "224.0.0.0/4", "240.0.0.0/4",
)]


def _load(path: pathlib.Path) -> list[ipaddress.IPv4Network]:
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if not ln or "." not in ln:  # v6 не наш кейс для catchall
            continue
        try:
            out.append(ipaddress.ip_network(ln, strict=False))
        except ValueError:
            pass
    return out


def main() -> int:
    src = _DEFAULT_DIR / "theirs_only.txt"
    if len(sys.argv) > 1:
        src = pathlib.Path(sys.argv[1])
    if not src.exists():
        print(f"нет {src} - сначала tools/ipset_diff_v3nilla.py")
        return 1

    excl = [ipaddress.ip_network(x, strict=False) for x in
            (_REPO / "lists" / "ipset-exclude.txt").read_text(
                encoding="utf-8", errors="replace").splitlines()
            if x.strip() and ":" not in x]
    excl = _RESERVED + excl

    cand: list[ipaddress.IPv4Network] = []
    src_nets = _load(src)
    for n in src_nets:
        parts: list[ipaddress.IPv4Network] = [n]
        for e in excl:
            if not parts or not e.overlaps(n):
                continue
            newp: list[ipaddress.IPv4Network] = []
            for p in parts:
                if p.subnet_of(e):
                    continue
                if e.subnet_of(p):
                    newp += list(p.address_exclude(e))
                else:
                    newp.append(p)
            parts = newp
        cand += parts
    excluded_addr = sum(n.num_addresses for n in src_nets) - \
        sum(n.num_addresses for n in cand)

    cand.sort(key=lambda n: (int(n.network_address), n.prefixlen))
    merged = list(ipaddress.collapse_addresses(cand))
    total = sum(n.num_addresses for n in merged)

    lines = []
    lines.append(f"источник: {src.name}: {len(src_nets)} CIDR")
    lines.append(f"вырезано (reserved/exclude): {excluded_addr:,} адресов")
    lines.append(f"кандидатов: {len(cand)} -> после collapse: {len(merged)} "
                 f"({total:,} адресов)")
    lines.append("")
    lines.append("=== по первым октетам (адреса / CIDR / топ-блоки) ===")
    groups: dict[int, list[ipaddress.IPv4Network]] = {}
    for n in merged:
        groups.setdefault(int(n.network_address) >> 24, []).append(n)
    for oct1 in sorted(groups):
        nets = sorted(groups[oct1], key=lambda n: n.num_addresses, reverse=True)
        addr = sum(n.num_addresses for n in nets)
        top = " ".join(str(n) for n in nets[:4])
        lines.append(f"  {oct1:>3}.x: {addr:>11,} адр. | {len(nets):>4} CIDR | "
                     f"{top}")
    lines.append("")
    big = sorted(merged, key=lambda n: n.num_addresses, reverse=True)[:25]
    lines.append("=== топ-25 блоков (ручная проверка на break-класс) ===")
    for n in big:
        lines.append(f"  {str(n):<20} {n.num_addresses:>10,}")

    (src.parent / "candidates.txt").write_text(
        "\n".join(str(n) for n in merged) + "\n", encoding="utf-8")
    (src.parent / "candidates_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nфайлы: {src.parent}\\candidates.txt | candidates_report.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
