"""Polite HTTP helpers shared by all scraper code: one session with a
browser User-Agent, a global inter-request delay, retries on transient
failures, and atomic streamed downloads that skip already-fetched files."""
import logging
import os
import time

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from councillens.config import GRANICUS_BASE_URL, REQUEST_DELAY_SECONDS, USER_AGENT

log = logging.getLogger(__name__)

_session: requests.Session | None = None
_last_request_at = 0.0


def get_http_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT, "Referer": GRANICUS_BASE_URL + "/"})
    return _session


def _throttle() -> None:
    global _last_request_at
    wait = _last_request_at + REQUEST_DELAY_SECONDS - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = exc.response
        return resp is not None and (resp.status_code >= 500 or resp.status_code == 429)
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


_retry = retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, max=60),
    reraise=True,
)


@_retry
def get(url: str, timeout: int = 60, **kwargs) -> requests.Response:
    _throttle()
    resp = get_http_session().get(url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


@_retry
def download(url: str, dest_path: str, timeout: int = 120) -> str:
    """Stream url to dest_path. Skips if dest already exists non-empty;
    writes to a .part file and renames, so a killed run never leaves a
    truncated file pretending to be complete."""
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        log.debug("already downloaded: %s", dest_path)
        return dest_path
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp = dest_path + ".part"
    _throttle()
    with get_http_session().get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    os.replace(tmp, dest_path)
    return dest_path
