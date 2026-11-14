"""Сборка персональной стратегии - лучшие сегменты пресетов в один custom.

После прогона тестера каждый probe-домен относится к family (discord /
google / general по hostlist).  Сегмент family берётся из пресета с лучшим
family-рейтингом, и пишется merged-пресет "custom": Discord <- P_a,
Google <- P_b, General <- P_c.  Непроверяемые сегменты (voice / media /
QUIC) всегда берутся из default.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

FAMILIES = ("discord", "google", "general")

def segment_family(name: str) -> Optional[str]:
    """Family проверяемого сегмента по его имени (--comment/--name).

    Раньше здесь был жёсткий dict с именами default: у 6/11 пресетов блоки
    называются иначе ("Discord TCP", "Google TCP", fake-disorder - через
    --name), из-за чего build_custom молча подставлял сегмент из default, но
    писал в custom "(из <другого пресета)" - стратегия не соответствовала
    измеренной. Матчим по смыслу, а не по точной строке."""
    n = name.strip().lower()
    if "discord" in n and ("tcp" in n or "tls" in n):
        return "discord"
    if "google" in n and ("tcp" in n or "tls" in n):
        return "google"
    if "general" in n and "tcp" in n:
        return "general"
    return None


# Имена сегментов тестера в UI/логе (для обратной совместимости с внешними
# потребителями результата build_custom).
SEGMENT_NAMES = {
    "discord": "Discord TCP tls",
    "google": "Google TCP tls",
    "general": "General TCP",
}

# Сегменты, недоступные тестеру (UDP voice, media-порты, QUIC):
# берутся из default, где они проверены.
KEEP_FROM_DEFAULT = ("Discord Voice", "Discord Media TCP", "QUIC Google", "QUIC General")

CUSTOM_PRESET = "custom"


def _norm(domain: str) -> str:
    return domain.strip().lower().rstrip(".")


def _load_list(path: Path) -> set[str]:
    out = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if not line:
            continue
        line = line.lstrip("^")  # "^" у zapret = точный домен; маппинг family тот же
        out.add(line)
    return out


def make_family_fn(root: Path) -> Callable[[str], Optional[str]]:
    """Домен -> family ("discord"/"google"/"general"/None) по вхождению в hostlist."""
    lists = {f: _load_list(root / "lists" / f"list-{f}.txt") for f in FAMILIES}

    def fam(domain: str) -> Optional[str]:
        d = _norm(domain)
        parts = d.split(".")
        for i in range(len(parts)):
            cand = ".".join(parts[i:])
            for f, doms in lists.items():
                if cand in doms:
                    return f
        return None

    return fam


def parse_preset(preset_path: Path) -> tuple[list[str], dict[str, list[str]]]:
    """(строки заголовка, {имя_сегмента: строки}) - сегменты делятся по '--new'."""
    text = preset_path.read_text(encoding="utf-8", errors="replace")
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in text.splitlines():
        if line.strip() == "--new":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)
    if not blocks:
        return [], {}
    header, rest = blocks[0], blocks[1:]
    segments: dict[str, list[str]] = {}
    for b in rest:
        name = "unnamed"
        for i, l in enumerate(b):
            s = l.strip()
            if s.startswith("--comment="):
                name = s.split("=", 1)[1]
                break
            if s == "--name" and i + 1 < len(b) and not b[i + 1].strip().startswith("--"):
                name = b[i + 1].strip()
                break
            if s.startswith("--name="):
                name = s.split("=", 1)[1]
                break
        segments[name] = b
    return header, segments


def _strip_meta(block: list[str]) -> list[str]:
    """Убрать --comment/--name (с их значениями) из копируемого блока."""
    out: list[str] = []
    i = 0
    while i < len(block):
        s = block[i].strip()
        if s == "--name" and i + 1 < len(block) and not block[i + 1].strip().startswith("--"):
            i += 2
            continue
        if s.startswith("--name=") or s.startswith("--comment="):
            i += 1
            continue
        out.append(block[i])
        i += 1
    return out


def _find_family_segment(segments: dict[str, list[str]], fam: str) -> tuple[str, list[str]] | tuple[None, None]:
    for name, block in segments.items():
        if segment_family(name) == fam:
            return name, block
    return None, None


def _family_rates(results_by_profile: dict[str, list[dict]], fam_fn) -> dict[str, dict[str, float]]:
    stat: dict[str, dict[str, list[int]]] = {}
    for prof, results in results_by_profile.items():
        fams: dict[str, list[int]] = {}
        for r in results:
            if r.get("test_type") == "ping":
                continue
            f = fam_fn(r.get("domain", ""))
            if not f:
                continue
            s = fams.setdefault(f, [0, 0])
            s[1] += 1
            if r.get("status") == "OK":
                s[0] += 1
        stat[prof] = {f: (ok / tot if tot else 0.0) for f, (ok, tot) in fams.items()}
    return stat


def build_custom(
    root: Path,
    results_by_profile: dict[str, list[dict]],
    default_name: str = "default",
) -> dict:
    """Выбирает лучший сегмент на family и пишет presets/custom.txt.

    Возвращает {"sources": {family: preset}, "rates": {profile: {family:
    rate}}, "preset": "custom", "error": None}.
    """
    fam_fn = make_family_fn(root)
    rates = _family_rates(results_by_profile, fam_fn)
    # Custom собирает ЛУЧШИЕ СЕГМЕНТЫ пресетов. auto - исключён: его механика
    # (circular-перебор) требует собственного lua (--lua-init zapret-auto.lua)
    # и «стратегии внутри стратегии» - это не сегмент, а режим. Притаскивание
    # circular-сегмента в custom ломало запуск (баг 2026-09-13: «desync
    # function 'circular' does not exist»). auto остаётся отдельным пресетом.
    profiles = [p for p in results_by_profile
                if p and p not in ("custom", "auto")]

    header, def_segs = parse_preset(root / "presets" / f"{default_name}.txt")
    if not def_segs:
        return {"sources": {}, "rates": rates, "preset": CUSTOM_PRESET,
                "error": f"не удалось разобрать {default_name}.txt"}

    sources: dict[str, str] = {}
    for fam in FAMILIES:
        best_p, best_rate = default_name, 0.0
        for p in profiles:
            rate = rates.get(p, {}).get(fam, 0.0)
            if rate > best_rate + 1e-9:
                best_p, best_rate = p, rate
        sources[fam] = best_p

    # Заголовок должен покрыть ВСЕ источники: сегмент может зависеть от
    # глобальных флагов своего пресета - у auto это --wf-tcp-in (для
    # --in-range) и --lua-init @lua/zapret-auto.lua (для circular). Берём
    # объединение полных заголовков всех не-default источников.
    #
    # 2026-09-13: дедуп РАНЬШЕ был по ОДИНОЧНОЙ строке - пара
    # «--lua-init + @lua/zapret-auto.lua» разваливалась: второй --lua-init
    # дедупнулся, а значение-сирота осталось без опции → zapret-auto.lua не
    # загружался → winws2 падал с «desync function 'circular' does not
    # exist». Дедуп теперь по ПАРЕ (опция + значение на следующей строке).
    def _pairwise(ls: list[str]) -> list[tuple[str, str | None]]:
        out: list[tuple[str, str | None]] = []
        i = 0
        while i < len(ls):
            s = ls[i].strip()
            if not s:
                i += 1
                continue
            nxt = ls[i + 1].strip() if i + 1 < len(ls) else ""
            if (s.startswith("--") and "=" not in s
                    and not s.startswith("--comment")
                    and nxt and not nxt.startswith("--")):
                out.append((s, nxt))
                i += 2
                continue
            out.append((s, None))
            i += 1
        return out

    def _pair_key(pair: tuple[str, str | None]) -> str:
        o, v = pair
        return o if v is None else f"{o}={v}"

    have = {_pair_key(x) for x in _pairwise(header)}
    extra_header: list[str] = []
    for fam, src in sources.items():
        if src == default_name:
            continue
        for o, v in _pairwise(parse_preset(root / "presets" / f"{src}.txt")[0]):
            k = _pair_key((o, v))
            if k in have:
                continue
            have.add(k)
            extra_header.extend([o, v] if v is not None else [o])
    if extra_header:
        # вставить после lua-init-группы (перед --blob): zapret-auto.lua
        # грузится после lib/antidpi, как в исходном auto-пресете
        insert_at = len(header)
        for i, l in enumerate(header):
            if l.strip().startswith("--blob"):
                insert_at = i
                break
        header[insert_at:insert_at] = extra_header

    # ── Сборка тела ────────────────────────────────────────────────
    # ВНИМАНИЕ (2026-10-05): parse_preset отдаёт header = всё ДО первого
    # --new, а в пресетах первый профиль идёт без разделителя (Discord
    # Voice лежит в header). Поэтому header - это «глобальные опции +
    # возможно уже готовый профиль». Если в нём есть --filter*, он сам
    # является профилем и первый family-сегмент надо от него отделять
    # --new, иначе voice-UDP и discord-TCP склеиваются в один профиль
    # (--filter-udp + --filter-tcp вместе не матчится никогда) и профилей
    # выходит 7 вместо 8 (репро в исторический аудит §2.1).
    # Если header - только глобальные опции (нет фильтров), разделитель
    # не нужен: первый сегмент сам станет первым профилем.
    lines: list[str] = list(header)
    if any(l.strip().startswith("--filter") for l in header):
        lines.append("--new")
    for fam in FAMILIES:
        src = sources[fam]
        src_segs = parse_preset(root / "presets" / f"{src}.txt")[1]
        seg_name, block = _find_family_segment(src_segs, fam)
        if block is None:
            seg_name, block = _find_family_segment(def_segs, fam)
            src = default_name if block is not None else src
        if block is None:
            continue
        lines.append(f"--comment={SEGMENT_NAMES[fam]} (из {src})")
        lines.extend(_strip_meta(block))
        lines.append("--new")
    for seg_name in KEEP_FROM_DEFAULT:
        block = def_segs.get(seg_name)
        if block is None:
            continue
        lines.append(f"--comment={seg_name}")
        lines.extend(l for l in block if not l.strip().startswith("--comment="))
        lines.append("--new")
    while lines and lines[-1].strip() == "--new":
        lines.pop()

    out = root / "presets" / f"{CUSTOM_PRESET}.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"sources": sources, "rates": rates, "preset": CUSTOM_PRESET, "error": None}