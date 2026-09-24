"""Релевантные нам домены из реестра РКН (bol-van/rulist) - справочник.

Зачем: реестр огромный и в основном это пиратка/казино/новости, но иногда
там оказываются сервисы НАШЕЙ аудитории (игры, общение, видео). Инструмент
отвечает на вопрос: «а этот сервис в реестре? и покрыт ли он нашими
списками?» - без массовых действий из дома.

Безопасность и лимиты:
  - один GET текстового списка с GitHub raw (кэшируется в %TEMP%);
  - опциональный --resolve: обычные DNS-запросы по НЕСКОЛЬКИМ десяткам имён
    (как открытие сайтов в браузере), без порт-скан-ов и без тысяч IP;
  - ничего не отправляем наружу, кроме этих запросов.

Запуск:
  python tools/_rkn_relevant.py             # фильтр + сверка с нашими списками
  python tools/_rkn_relevant.py --resolve   # + DNS по новым (до 60 доменов)
"""
from __future__ import annotations

import gzip
import ipaddress
import pathlib
import socket
import sys
import tempfile
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY_URL = ("https://raw.githubusercontent.com/bol-van/rulist/main/"
                "reestr_hostname.txt")

# Семейства доменов, которые закрывает наш продукт. Матчинг - по границам
# домена (host == family или host.endswith("." + family)), чтобы казино-спам
# вида "1wedea.com" или "1win-telegram.ru" НЕ попадал в отчёт.
FAMILIES: dict[str, list[str]] = {
    "Игры": [
        "steampowered.com", "steamcommunity.com", "steamstatic.com",
        "steamcontent.com", "steamusercontent.com", "steamserver.net",
        "steamgames.com", "valvesoftware.com", "epicgames.com",
        "unrealengine.com", "riotgames.com", "leagueoflegends.com",
        "valorant.com", "battle.net", "blizzard.com", "activision.com",
        "callofduty.com", "rockstargames.com", "ubisoft.com", "ea.com",
        "warface.com", "warthunder.com", "gaijin.net", "worldoftanks.ru",
        "wargaming.net", "roblox.com", "minecraft.net", "mojang.com",
        "escapefromtarkov.com", "battlestate.games", "albiononline.com",
        "pathofexile.com",
    ],
    "Общение": [
        "telegram.org", "telegram.me", "t.me", "web.telegram.org",
        "whatsapp.com", "whatsapp.net", "viber.com", "signal.org",
        "discord.com", "discord.gg", "discordapp.com", "discordapp.net",
        "discord.media", "discordcdn.com",
    ],
    "Видео и медиа": [
        "youtube.com", "youtu.be", "googlevideo.com", "ytimg.com",
        "youtube-nocookie.com", "youtubekids.com", "twitch.tv",
        "netflix.com", "spotify.com", "tiktok.com", "soundcloud.com",
        "deezer.com", "rutube.ru",
    ],
    "CDN и инфраструктура": [
        "akamai.net", "akamaiedge.net", "akamaized.net", "akamaihd.net",
        "cloudflare.com", "cloudflare.net", "cloudfront.net", "fastly.net",
        "llnwd.net", "edgesuite.net", "edgekey.net",
    ],
}

MAX_RESOLVE = 60


def fetch_registry() -> pathlib.Path:
    """Список хостов реестра (кэш в %TEMP%; один GET)."""
    cache = pathlib.Path(tempfile.gettempdir()) / "rulist" / "hostnames.txt"
    cache.parent.mkdir(exist_ok=True)
    if not cache.exists():
        req = urllib.request.Request(REGISTRY_URL,
                                     headers={"User-Agent": "Zapret2GUI"})
        with urllib.request.urlopen(req, timeout=120) as r:
            cache.write_bytes(r.read())
    return cache


def load_our_lists() -> set[str]:
    """Все домены наших списков (list-*.txt) - что уже в обходе."""
    names: set[str] = set()
    for p in sorted((ROOT / "lists").glob("list-*.txt")):
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip().lower()
            if s and not s.startswith("#"):
                names.add(s)
    return names


def load_our_ipset() -> list[tuple[int, int]]:
    """Наш ipset-all как отсортированные (start, end) диапазоны."""
    nets = []
    with gzip.open(ROOT / "lists" / "ipset-all.txt.gz", "rt",
                   encoding="utf-8", errors="replace") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            try:
                n = ipaddress.ip_network(s, strict=False)
            except ValueError:
                continue
            if n.version == 4:
                nets.append(n)
    return [(int(n.network_address), int(n.broadcast_address))
            for n in ipaddress.collapse_addresses(nets)]


def covered_by_lists(host: str, ours: set[str]) -> bool:
    """Домен или его родитель есть в наших списках."""
    parts = host.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in ours:
            return True
    return False


def main() -> None:
    do_resolve = "--resolve" in sys.argv
    path = fetch_registry()
    hosts = [l.strip().lower() for l in
             path.read_text(encoding="utf-8", errors="replace").splitlines()
             if l.strip() and not l.strip().startswith('"')]
    print(f"реестр: {len(hosts)} хостов")

    ours = load_our_lists()
    print(f"наши списки: {len(ours)} доменов\n")

    def in_family(host: str, fam: str) -> bool:
        return host == fam or host.endswith("." + fam)

    def covered(host: str) -> bool:
        return covered_by_lists(host, ours)

    unmatched: list[str] = []
    for cat, fams in FAMILIES.items():
        found = sorted({h for h in hosts if any(in_family(h, f) for f in fams)})
        if not found:
            continue
        cov = [h for h in found if covered(h)]
        print(f"== {cat}: найдено {len(found)}, из них в наших списках {len(cov)}")
        shows = cov[:6] + [h for h in found if not covered(h)][:12]
        for h in shows:
            mark = "уже в обходе" if covered(h) else "НЕТ в списках"
            print(f"   {'+' if covered(h) else '-'} {h}  ({mark})")
        if len(found) > len(shows):
            print(f"   ... и ещё {len(found) - len(shows)}")
        if cat in ("Игры", "Общение"):
            unmatched += [h for h in found if not covered(h)]
        print()

    if not do_resolve:
        print("(DNS-проверку можно добавить флагом --resolve)")
        return

    rngs = load_our_ipset()
    import bisect
    starts = [a for a, _ in rngs]
    ends = [b for _, b in rngs]

    def ip_in_ipset(x):
        i = bisect.bisect_right(starts, x) - 1
        return i >= 0 and x <= ends[i]

    print(f"== DNS по {min(len(unmatched), MAX_RESOLVE)} непокрытым "
          f"(игры/общение), заодно смотрим наш ipset ==")
    for h in unmatched[:MAX_RESOLVE]:
        try:
            infos = socket.getaddrinfo(h, 443, socket.AF_INET,
                                       socket.SOCK_STREAM)
            ips = sorted({i[4][0] for i in infos})
            ins = sum(1 for ip in ips
                      if ip_in_ipset(int(ipaddress.ip_address(ip))))
            print(f"   {h}: {', '.join(ips[:3])} "
                  f"| в нашем ipset: {ins}/{len(ips)}")
        except OSError as e:
            print(f"   {h}: не резолвится ({e.__class__.__name__})")
        time.sleep(0.15)  # без долбёжки DNS


if __name__ == "__main__":
    main()
