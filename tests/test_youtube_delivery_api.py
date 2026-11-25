"""API проверки доставки YouTube: валидация и жизненный цикл без браузера."""
from server import api_youtube_delivery as api


class _Ctx:
    pass


def test_start_rejects_bad_urls(monkeypatch) -> None:
    out = api.youtube_delivery_start(_Ctx(), {"reference_url": "x", "problem_url": "y"})
    assert out["status"] == "error"
    assert "ссылки" in out["message"]


def test_start_rejects_same_video() -> None:
    url = "https://www.youtube.com/watch?v=-Td4It4H_Uc"
    out = api.youtube_delivery_start(_Ctx(), {"reference_url": url, "problem_url": url})
    assert out["status"] == "error"
    assert "разных" in out["message"]


def test_start_busy_when_checker_running(monkeypatch) -> None:
    monkeypatch.setattr(api, "checkers_busy", lambda: "Тестер занят")
    out = api.youtube_delivery_start(_Ctx(), {
        "reference_url": "https://youtu.be/-Td4It4H_Uc",
        "problem_url": "https://youtu.be/dQw4w9WgXcQ",
    })
    assert out["status"] == "error"
    assert "занят" in out["message"]


def test_start_runs_job_and_reports(monkeypatch) -> None:
    class _Run:
        def __init__(self, label):
            self.label = label
        def as_dict(self):
            return {"label": self.label,
                    "metrics": {"traffic_mb": 1.0},
                    "verdict": {"code": "stable", "label": "ок"}}

    monkeypatch.setattr(api, "checkers_busy", lambda: None)
    monkeypatch.setattr(api, "begin_operation", lambda name: None)
    monkeypatch.setattr(api, "end_operation", lambda name: None)
    monkeypatch.setattr(api.youtube_probe, "probe_video",
                        lambda vid, label="", **kw: _Run(label))
    out = api.youtube_delivery_start(_Ctx(), {
        "reference_url": "https://youtu.be/-Td4It4H_Uc",
        "problem_url": "https://youtu.be/dQw4w9WgXcQ",
    })
    assert out["status"] == "ok"
    import time
    for _ in range(50):
        st = api.youtube_delivery_status(_Ctx())
        if st.get("state") in ("done", "error"):
            break
        time.sleep(0.05)
    st = api.youtube_delivery_status(_Ctx())
    assert st["state"] == "done"
    assert st["comparison"]["code"] == "both_stable"
    api._reset()
