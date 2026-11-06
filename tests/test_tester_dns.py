from __future__ import annotations

from core import tester_probes


def test_curl_test_uses_doh_after_system_dns_failure(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_curl(_url, head, timeout, resolve=None):
        calls.append(bool(resolve))
        if resolve:
            return 200, 0, 10.0, ""
        return None, 6, 10.0, "Could not resolve host: www.youtube.com"

    monkeypatch.setattr(tester_probes, "curl_attempt", fake_curl)
    monkeypatch.setattr(tester_probes, "doh_resolve_ips",
                        lambda _domain: ["142.250.1.1"])

    result = tester_probes.curl_test("www.youtube.com", "http", 1.0)

    assert result.status == "OK"
    assert result.status_code == 200
    assert "DoH" in result.error
    assert True in calls
