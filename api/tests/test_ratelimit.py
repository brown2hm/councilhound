"""Rate limiter — the only thing between the public /ask endpoint and an
unbounded LLM bill. Tests drive the module's clock and state directly."""
import pytest
from fastapi import HTTPException

from app import ratelimit


class FakeRequest:
    def __init__(self, ip="1.2.3.4"):
        self.headers = {"fly-client-ip": ip}
        self.client = None


@pytest.fixture(autouse=True)
def reset_state():
    ratelimit._by_ip.clear()
    ratelimit._day.update(date="", count=0)
    yield
    ratelimit._by_ip.clear()
    ratelimit._day.update(date="", count=0)


def test_per_ip_window_blocks_then_recovers(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    req = FakeRequest()

    for _ in range(ratelimit.ASK_PER_MINUTE):
        ratelimit.check_ask_rate(req)
    with pytest.raises(HTTPException) as exc:
        ratelimit.check_ask_rate(req)
    assert exc.value.status_code == 429

    now[0] += 61  # window slides -> allowed again
    ratelimit.check_ask_rate(req)


def test_per_ip_isolation(monkeypatch):
    monkeypatch.setattr(ratelimit.time, "time", lambda: 1000.0)
    for _ in range(ratelimit.ASK_PER_MINUTE):
        ratelimit.check_ask_rate(FakeRequest("1.1.1.1"))
    # a different IP is unaffected
    ratelimit.check_ask_rate(FakeRequest("2.2.2.2"))


def test_global_daily_budget(monkeypatch):
    now = [1000.0]
    day = ["day-1"]  # fully fake clock: never depends on the real date/timezone
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    monkeypatch.setattr(ratelimit.time, "strftime", lambda fmt: day[0])
    monkeypatch.setattr(ratelimit, "ASK_GLOBAL_PER_DAY", 3)

    for i in range(3):
        now[0] += 61  # avoid tripping the per-IP window
        ratelimit.check_ask_rate(FakeRequest(f"9.9.9.{i}"))
    now[0] += 61
    with pytest.raises(HTTPException) as exc:
        ratelimit.check_ask_rate(FakeRequest("9.9.9.99"))
    assert "napping" in exc.value.detail

    # new day -> budget resets
    day[0] = "day-2"
    ratelimit.check_ask_rate(FakeRequest("9.9.9.100"))
