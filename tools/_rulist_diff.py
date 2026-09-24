"""Сравнение нашей ipset-базы с реестром РКН (bol-van/rulist).

Что делает:
  - скачивает reestr_smart4 / reestr_ipban4 во временную папку;
  - считает, сколько записей реестра уже покрыто нашим lists/ipset-all.txt.gz;
  - показывает, что НЕ покрыто (топ /24) и сколько попадает в крупные
    облака/CDN (Cloudflare/AWS/DO/OVH/Hetzner) - это риск "задушить"
    работающее при включённом «Общем IP-обходе».

Запуск: python tools/_rulist_diff.py
Результат - для решения: добавить реестр в базу ipset или нет (обсуждать
после релиза, с A/B через CDN-стабилизацию).
"""
from __future__ import annotations

import bisect
import gzip
import ipaddress
import pathlib
import tempfile
import urllib.request
from collections import Counter

BASE = "https://raw.githubusercontent.com/bol-van/rulist/main/"
ROOT = pathlib.Path(__file__).resolve().parent.parent
IPSSET = ROOT / "lists" / "ipset-all.txt.gz"

RISKY = {
    "Cloudflare": ["104.16.0.0/12", "172.64.0.0/13", "162.158.0.0/15",
                   "188.114.96.0/20"],
    "AWS": ["3.0.0.0/9", "52.0.0.0/8", "54.0.0.0/8", "18.128.0.0/9"],
    "DigitalOcean": ["159.65.0.0/16", "165.227.0.0/16", "167.99.0.0/16",
                     "138.68.0.0/16"],
    "OVH": ["51.38.0.0/16", "51.68.0.0/16", "51.75.0.0/16", "51.83.0.0/16",
            "51.89.0.0/16", "51.91.0.0/16", "145.239.0.0/16", "178.32.0.0/15"],
    "Hetzner": ["5.9.0.0/16", "88.198.0.0/16", "116.202.0.0/16"],
}


def _download(name: str, dest: pathlib.Path) -> pathlib.Path:
    if not dest.exists():
        req = urllib.request.Request(BASE + name,
                                     headers={"User-Agent": "Zapret2GUI"})
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
    return dest


def load_nets(path: pathlib.Path, gz: bool = False) -> list:
    opener = gzip.open if gz else open
    out = []
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                n = ipaddress.ip_network(s, strict=False)
            except ValueError:
                continue
            if n.version == 4:
                out.append(n)
    return out


def main() -> None:
    tmp = pathlib.Path(tempfile.gettempdir()) / "rulist"
    tmp.mkdir(exist_ok=True)
    smart = load_nets(_download("reestr_smart4.txt", tmp / "smart4.txt"))
    ipban = load_nets(_download("reestr_ipban4.txt", tmp / "ipban4.txt"))

    ours = load_nets(IPSSET, gz=True)
    merged = list(ipaddress.collapse_addresses(ours))
    starts = [int(n.network_address) for n in merged]
    ends = [int(n.broadcast_address) for n in merged]
    print(f"наш ipset-all: {len(ours)} сетей "
          f"({len(merged)} слитых диапазонов)")

    def net_covered(n) -> bool:
        i = bisect.bisect_right(starts, int(n.network_address)) - 1
        return i >= 0 and ends[i] >= int(n.broadcast_address)

    for name, nets in (("reestr_smart4", smart), ("reestr_ipban4", ipban)):
        cov = sum(1 for n in nets if net_covered(n))
        rest = [n for n in nets if not net_covered(n)]
        print(f"\n{name}: {len(nets)} записей; уже покрыто нами: {cov} "
              f"({cov * 100 // max(len(nets), 1)}%)")
        c24 = Counter(str(ipaddress.ip_network(
            f"{n.network_address}/24", strict=False))
            for n in rest if n.prefixlen >= 24)
        print("  топ-8 /24 вне нашего ipset:")
        for net, k in c24.most_common(8):
            print("   ", net, k)

    print("\nsmart4: пересечение с облаками/CDN (сколько сетей):")
    for name, nets in RISKY.items():
        rngs = [ipaddress.ip_network(x) for x in nets]
        cnt = 0
        for n in smart:
            st, en = int(n.network_address), int(n.broadcast_address)
            if any(st <= int(r.broadcast_address)
                   and int(r.network_address) <= en for r in rngs):
                cnt += 1
        print(f"  {name}: {cnt}")


if __name__ == "__main__":
    main()
