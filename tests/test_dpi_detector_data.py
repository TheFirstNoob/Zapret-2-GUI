"""Pin данных dpi-detector (MIT): молчаливая подмена должна падать в CI."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBES_SHA256 = "546c14d6d3fd120884111bbc37da4a3367ee98f42716d58c6bb6d932a2dc7b12"
WHITELIST_SHA256 = "0f85b93e7a15c8d5f53aa1abb02f81eade6d5645217f6cf155dbecbea73ffa41"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_asn_probes_snapshot():
    assert _sha(ROOT / "lists" / "cdn-asn-probes.json") == PROBES_SHA256


def test_whitelist_sni_snapshot():
    assert _sha(ROOT / "lists" / "whitelist-sni.txt") == WHITELIST_SHA256
