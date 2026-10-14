"""preset_parse.py - .txt пресет -> плоские токены (аудит #4).

Подстановки: @lists/ -> абсолютный путь без @ (--hostlist/--ipset);
@lua|@blobs|@windivert -> абсолютный путь С @ (значения --lua-init/--blob);
%GameFilter% -> порты при включённом GameFilter (иначе строка вырезается);
ipset_catchall заменяет SNI-блоки list-general на IP-catch-all;
строки # и --comment пропускаются; autohostlist дописывает --hostlist-auto
в блоки list-general. Постобработки - в core/args_transforms.py.
"""
from __future__ import annotations

from pathlib import Path

HIGH_PORTS = "1024-65535"


def parse_preset(preset_path: Path, *, lists_base: str, lua_dir: Path,
                 blobs_dir: Path, windivert_dir: Path, game_on: bool,
                 ipset_catchall: bool, autohostlist: bool, auto_path: str,
                 ipset_inc_path: str, ipset_excl_path: str) -> list[str]:
    """Читает пресет и возвращает токены до постобработок (порядок строк сохранён)."""
    lines = preset_path.read_text(encoding="utf-8-sig").strip().splitlines()
    tokens: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("--comment"):
            continue
        # Targeted-mode override: SNI-блоки list-general -> IP catch-all.
        # winws2 AND-ит ipset с hostlist - включение обнулило бы catch-all;
        # list-exclude и юзер-исключения продолжают действовать.
        if ipset_catchall and line.startswith("--hostlist=") and "list-general.txt" in line:
            tokens.append(f"--ipset={lists_base}\\ipset-all.txt.gz")
            if ipset_inc_path:
                # Несколько --ipset OR-ятся ("multiple ipsets allowed") -
                # юзер-подсети десинкаются тоже.
                tokens.append(f"--ipset={ipset_inc_path}")
            tokens.append(f"--ipset-exclude={lists_base}\\ipset-exclude.txt")
            if ipset_excl_path:
                # Несколько exclude коллекций поддерживаются; юзер-сети
                # сильнее ipset-all.
                tokens.append(f"--ipset-exclude={ipset_excl_path}")
            if autohostlist:
                # catch-all заменяет hostlist на ipset, но --hostlist-auto
                # должен остаться: иначе тумблер молча холостой (аудит 2026-10).
                tokens.append(f"--hostlist-auto={auto_path}")
            continue
        if "@lists/" in line:
            line = line.replace("@lists/", str(lists_base) + "\\")
        for dir_name, dir_path in (("@lua/", lua_dir), ("@blobs/", blobs_dir),
                                   ("@windivert/", windivert_dir)):
            if dir_name in line:
                line = line.replace(dir_name, "@" + str(dir_path) + "\\")
        if "%GameFilter%" in line:
            port = HIGH_PORTS if game_on else ""
            cleaned = line.replace("%GameFilter%", port).strip(",").strip()
            if not cleaned:
                continue
            line = cleaned
        tokens.append(line)
        # --autohostlist добавляется в блоки фильтра list-general
        if autohostlist and "--hostlist=" in line and "list-general" in line:
            tokens.append(f"--hostlist-auto={auto_path}")
    return tokens
