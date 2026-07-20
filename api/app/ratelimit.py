"""Rate limiting for the LLM-backed /ask endpoint (Phase 6 public hardening).

Two layers, both in-memory (the API runs as a single instance):
  - per-IP sliding window: stops one client hammering the endpoint
  - global daily budget: caps worst-case LLM spend no matter how many IPs

Read endpoints are cheap DB queries and stay unlimited.
"""
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

ASK_PER_MINUTE = int(os.environ.get("ASK_RATE_PER_MINUTE", "6"))
ASK_GLOBAL_PER_DAY = int(os.environ.get("ASK_RATE_GLOBAL_PER_DAY", "500"))

_lock = threading.Lock()
_by_ip: dict[str, deque] = defaultdict(deque)
_day = {"date": "", "count": 0}


def client_ip(request: Request) -> str:
    # Fly terminates TLS and passes the real client address in this header
    return (request.headers.get("fly-client-ip")
            or (request.client.host if request.client else "unknown"))


def check_ask_rate(request: Request) -> None:
    ip = client_ip(request)
    now = time.time()
    with _lock:
        # day rollover FIRST — clearing _by_ip after taking the window
        # reference would orphan this request's record
        today = time.strftime("%Y-%m-%d")
        if _day["date"] != today:
            _day["date"], _day["count"] = today, 0
            _by_ip.clear()

        window = _by_ip[ip]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= ASK_PER_MINUTE:
            raise HTTPException(429, "Too many questions — try again in a minute.")
        if _day["count"] >= ASK_GLOBAL_PER_DAY:
            raise HTTPException(429, "The hound is napping — daily question limit reached. Come back tomorrow.")

        window.append(now)
        _day["count"] += 1


SUBSCRIBE_PER_HOUR = int(os.environ.get("SUBSCRIBE_RATE_PER_HOUR", "10"))

_sub_lock = threading.Lock()
_sub_by_ip: dict[str, deque] = defaultdict(deque)


def check_subscribe_rate(request: Request) -> None:
    """Follow-a-topic signups send email, so they get their own (laxer)
    per-IP window to stop confirmation-mail abuse."""
    ip = client_ip(request)
    now = time.time()
    with _sub_lock:
        window = _sub_by_ip[ip]
        while window and window[0] < now - 3600:
            window.popleft()
        if len(window) >= SUBSCRIBE_PER_HOUR:
            raise HTTPException(429, "Too many signups from this address — try again later.")
        window.append(now)
