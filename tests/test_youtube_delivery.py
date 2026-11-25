"""Проверка метрик и вердиктов YouTube-доставки (без браузера)."""
from core import youtube_delivery as yd


def _samples(times, ahead=10.0, paused=False, h=720):
    return [{"ts": float(i), "t": float(t), "ahead": ahead,
             "paused": paused, "h": h} for i, t in enumerate(times)]


def test_parse_video_id() -> None:
    assert yd.parse_video_id("https://www.youtube.com/watch?v=-Td4It4H_Uc") == "-Td4It4H_Uc"
    assert yd.parse_video_id("https://youtu.be/-Td4It4H_Uc?t=10") == "-Td4It4H_Uc"
    assert yd.parse_video_id("https://www.youtube.com/shorts/-Td4It4H_Uc") == "-Td4It4H_Uc"
    assert yd.parse_video_id("https://example.com/watch?v=-Td4It4H_Uc") is None
    assert yd.parse_video_id("not a url") is None


def test_stable_verdict() -> None:
    m = yd.compute_metrics(_samples(range(0, 31)), window_s=30)
    v = yd.verdict(m)
    assert v["code"] == "stable"
    assert m.advancement >= 0.95
    assert m.stalls == 0


def test_starvation_verdict() -> None:
    times = list(range(0, 6)) + [5] * 10 + list(range(6, 20))
    events = [{"dt": 1.0, "delta": 100000}] * 20
    m = yd.compute_metrics(_samples(times, ahead=0.0), window_s=30,
                           byte_events=events)
    v = yd.verdict(m)
    assert v["code"] == "starvation"
    assert m.stalls >= 1
    assert m.stall_total_s >= yd.STALL_MIN_S


def test_startup_failure() -> None:
    m = yd.compute_metrics(_samples([0] * 40), window_s=40)
    v = yd.verdict(m)
    assert v["code"] == "startup_failure"


def test_inconclusive_short_window() -> None:
    m = yd.compute_metrics(_samples(range(0, 8)), window_s=7)
    v = yd.verdict(m)
    assert v["code"] == "inconclusive"


def test_buffer_zero_is_valid() -> None:
    m = yd.compute_metrics(_samples(range(0, 31), ahead=0.0), window_s=30)
    assert m.buffer_ahead_min_s == 0.0


def test_compare_pairs() -> None:
    left = {"verdict": {"code": "stable"}}
    right = {"verdict": {"code": "starvation"}}
    assert yd.compare(left, right)["code"] == "difference"
    assert yd.compare(left, left)["code"] == "both_stable"
    assert yd.compare(right, right)["code"] == "both_impaired"
    assert yd.compare(left, {})["code"] == "incomplete"
