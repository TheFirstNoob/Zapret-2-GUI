r"""Golden-слепок конвейера аргументов (аудит #4; страховка распила launcher).

  python tools/args_golden.py snapshot   # записать слепок (tools/args_golden.json)
  python tools/args_golden.py compare    # сверить текущий build_args со слепком

Слепок: матрица «все пресеты x ключевые тоглы»; пути корня нормализуются в
<ROOT> (переносимо между машинами). Побайтовое сравнение токенов - движок и
служба НЕ трогаются (build_args - чистая сборка списка, пишутся только
генерируемые файлы: union-список, пулы игр).
Exit code compare: 0 совпало, 1 расхождения (печатает первые diffs).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.launcher import build_args_from_preset  # noqa: E402
from core.utils import short_path  # noqa: E402

GOLDEN = pathlib.Path(__file__).resolve().parent / "args_golden.json"


def _norm(tokens: list[str]) -> list[str]:
    root = str(ROOT)
    short = str(short_path(ROOT))
    out = []
    for t in tokens:
        t = t.replace(root, "<ROOT>")
        if short != root:
            t = t.replace(short, "<ROOT>")
        out.append(t)
    return out


def _matrix() -> list[tuple[str, dict]]:
    blob_keys = sorted(
        p.stem.removeprefix("tls_clienthello_")
        for p in (ROOT / "blobs").glob("tls_clienthello_*.bin")
        if not p.stem.endswith("_kyber"))
    fake = blob_keys[0] if blob_keys else ""
    d = ROOT / "presets" / "default.txt"
    cases: list[tuple[str, dict]] = [
        (f"preset:{p.stem}", {"preset": p})
        for p in sorted((ROOT / "presets").glob("*.txt"))
        if p.stem != "custom"
    ]
    cases += [
        ("debug", {"preset": d, "debug": True}),
        ("game:udp", {"preset": d, "game_filter_mode": "udp"}),
        ("game:tcp", {"preset": d, "game_filter_mode": "tcp"}),
        ("game:both", {"preset": d, "game_filter_mode": "both"}),
        ("voice:fake", {"preset": d, "discord_voice": True}),
        ("voice:udplen", {"preset": d, "discord_voice_mode": "udplen"}),
        ("autohostlist", {"preset": d, "autohostlist": True}),
        ("ipset_catchall", {"preset": d, "ipset_catchall": True}),
        ("fake_blob", {"preset": d, "fake_blob": fake}),
        ("discord_alt", {"preset": d, "discord_alt": True}),
        ("combo:both+udplen+alt+debug",
         {"preset": d, "game_filter_mode": "both",
          "discord_voice_mode": "udplen", "discord_alt": True, "debug": True}),
    ]
    return cases


def _build(case: dict) -> list[str]:
    kw = dict(case)
    preset = kw.pop("preset")
    return build_args_from_preset(ROOT, ROOT / "lua", ROOT / "blobs", preset,
                                  lists_dir=ROOT / "lists",
                                  windivert_dir=ROOT / "windivert", **kw)


def _all(normalize: bool) -> dict[str, list[str]]:
    out = {}
    for label, case in _matrix():
        toks = _build(case)
        out[label] = _norm(toks) if normalize else toks
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("snapshot", "compare"))
    args = ap.parse_args()
    if args.mode == "snapshot":
        data = _all(normalize=True)
        GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print(f"snapshot: {len(data)} кейсов -> {GOLDEN.name}")
        return 0
    if not GOLDEN.exists():
        print("нет слепка - сначала snapshot")
        return 1
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    got = _all(normalize=True)
    bad = 0
    for label in sorted(set(want) | set(got)):
        a, b = want.get(label), got.get(label)
        if a == b:
            continue
        bad += 1
        print(f"FAIL {label}: слепок={len(a) if a else None} "
              f"токенов, сейчас={len(b) if b else None}")
        for i, (x, y) in enumerate(zip(a or [], b or [])):
            if x != y:
                print(f"  первый diff #{i}:\n    было: {x!r}\n    стало: {y!r}")
                break
    print("ИТОГ:", "OK" if bad == 0 else f"FAIL ({bad})")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
