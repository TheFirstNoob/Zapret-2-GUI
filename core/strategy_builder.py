"""Personal strategy builder — aggregate the best-scoring preset segments.

After the tester sweeps all presets, each probe domain is attributed to a
target family (discord / google / general via the hostlists).  The segment
that covers a family is taken from the preset with the highest family rate,
and a merged "custom" preset is written: Discord <- P_a, Google <- P_b,
General <- P_c.  Untestable segments (voice / media ports / QUIC) always
come from default.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

FAMILIES = ("discord", "google", "general")

# Tester-probeable segments and the family each one scores.
SEGMENT_FAMILY = {
    "Discord TCP tls": "discord",
    "Google TCP tls": "google",
    "General TCP": "general",
}

# Segments the tester cannot probe (UDP voice, media ports, QUIC):
# keep them from default, where they are proven.
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
        line = line.lstrip("^")  # zapret "^" = exact domain; same family mapping
        out.add(line)
    return out


def make_family_fn(root: Path) -> Callable[[str], Optional[str]]:
    """domain -> family ("discord"/"google"/"general"/None) by hostlist membership."""
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
    """(header_lines, {segment_name: lines}) — segments split on '--new'."""
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
        for l in b:
            if l.strip().startswith("--comment="):
                name = l.strip().split("=", 1)[1]
                break
        segments[name] = b
    return header, segments


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
    """Pick the best segment per family and write presets/custom.txt.

    Returns {"sources": {family: preset}, "rates": {profile: {family: rate}},
    "preset": "custom", "error": None}.
    """
    fam_fn = make_family_fn(root)
    rates = _family_rates(results_by_profile, fam_fn)
    profiles = [p for p in results_by_profile if p]

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

    # Header must satisfy ALL source presets: a segment may rely on its own
    # preset's global flags — auto's --wf-tcp-in (for --in-range) AND its
    # --lua-init @lua/zapret-auto.lua (for circular).  Union of the complete
    # header (exact-line dedup) of every non-default source preset.
    extra_header: list[str] = []
    for fam, src in sources.items():
        if src == default_name:
            continue
        src_header = parse_preset(root / "presets" / f"{src}.txt")[0]
        for l in src_header:
            s = l.strip()
            if not s:
                continue
            if s in [x.strip() for x in header] or s in [x.strip() for x in extra_header]:
                continue
            extra_header.append(l)
    if extra_header:
        insert_at = len(header)
        for i, l in enumerate(header):
            if l.strip().startswith("--lua-init"):
                insert_at = i
                break
        header[insert_at:insert_at] = extra_header

    lines: list[str] = list(header)
    for seg_name, fam in SEGMENT_FAMILY.items():
        src = sources[fam]
        src_segs = parse_preset(root / "presets" / f"{src}.txt")[1]
        block = src_segs.get(seg_name) or def_segs.get(seg_name)
        if block is None:
            continue
        lines.append(f"--comment={seg_name} (из {src})")
        lines.extend(l for l in block if not l.strip().startswith("--comment="))
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