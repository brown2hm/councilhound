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
        window = _by_ip[ip]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= ASK_PER_MINUTE:
            raise HTTPException(429, "Too many questions — try again in a minute.")

        today = time.strftime("%Y-%m-%d")
        if _day["date"] != today:
            _day["date"], _day["count"] = today, 0
            _by_ip.clear()
        if _day["count"] >= ASK_GLOBAL_PER_DAY:
            raise HTTPException(429, "The hound is napping — daily question limit reached. Come back tomorrow.")

        window.append(now)
        _day["count"] += 1
