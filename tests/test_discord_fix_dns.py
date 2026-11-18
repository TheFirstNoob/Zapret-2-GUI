"""DiscordFix DNS server: scoped A/NODATA без реального bind/NRPT."""
import socket
import struct

from core.discord_fix import _DnsServer


def _query(name: str, qtype: int = 1) -> bytes:
    labels = b"".join(bytes([len(p)]) + p.encode() for p in name.split("."))
    question = labels + b"\x00" + struct.pack("!HH", qtype, 1)
    return b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + question


def test_dns_answers_a_for_managed_zone():
    srv = _DnsServer("23.227.38.5")
    resp = srv._dispatch(_query("c-ams07-test.discord.media"))
    assert resp is not None
    assert resp[3] & 0x0F == 0  # NOERROR
    # последние 4 байта A-ответа
    assert socket.inet_ntoa(resp[-4:]) == "23.227.38.5"


def test_dns_answers_aaaa_as_nodata():
    srv = _DnsServer("23.227.38.5")
    resp = srv._dispatch(_query("gateway.discord.gg", qtype=28))
    assert resp is not None
    assert struct.unpack("!H", resp[6:8])[0] == 0  # ANCOUNT=0
    assert resp[3] & 0x0F == 0


def test_dns_answers_cloudflare_auth_zone():
    srv = _DnsServer("23.227.38.5")
    resp = srv._dispatch(_query("challenges.cloudflare.com"))
    assert resp is not None
    assert socket.inet_ntoa(resp[-4:]) == "23.227.38.5"
