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

from councilhound.config import GRANICUS_BASE_URL, REQUEST_DELAY_SECONDS, USER_AGENT

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
def post(url: str, timeout: int = 60, **kwargs) -> requests.Response:
    _throttle()
    resp = get_http_session().post(url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


ARCHIVE_VIDEO_HOST = "archive-video.granicus.com"
# how long to back off after each archive-video 403 (throttle) before retrying;
# anything still throttled after these falls through to the next daily run
ARCHIVE_THROTTLE_WAITS = (30, 60, 90)


@_retry
def download(url: str, dest_path: str, timeout: int = 120) -> str:
    """Stream url to dest_path. Skips if dest already exists non-empty;
    writes to a .part file and renames, so a killed run never leaves a
    truncated file pretending to be complete.

    archive-video.granicus.com rate-limits bursty access by returning 403 (not
    429), so a plain retry-on-5xx/429 doesn't cover it. When we get a 403 from
    that host we back off and retry a few times; anything still throttled is
    left for the next daily run to re-attempt — spreading downloads out is what
    keeps us under the limit."""
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        log.debug("already downloaded: %s", dest_path)
        return dest_path
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp = dest_path + ".part"
    is_archive = ARCHIVE_VIDEO_HOST in url
    # archive-video 403s any cross-host Referer; our session always sends a
    # granicus.com Referer, so omit it for that host (None drops the header).
    headers = {"Referer": None} if is_archive else None
    waits = ARCHIVE_THROTTLE_WAITS if is_archive else ()
    for attempt in range(len(waits) + 1):
        _throttle()
        resp = get_http_session().get(url, stream=True, timeout=timeout, headers=headers)
        if resp.status_code == 403 and attempt < len(waits):
            resp.close()
            log.warning("archive-video throttled (403); retrying in %ds", waits[attempt])
            time.sleep(waits[attempt])
            continue
        with resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        os.replace(tmp, dest_path)
        return dest_path
