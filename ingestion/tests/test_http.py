"""HTTP download header + throttle behavior. Three guarantees worth pinning:
media on archive-video.granicus.com is behind hotlink protection that 403s any
cross-host Referer (so download() omits the session's granicus Referer for that
host); that host rate-limits bursty access with 403s (so download() backs off
through the full ladder once it has seen the host succeed); and its CDN also
hard-blocks datacenter IPs with the same 403 (so a COLD 403 — before any
success this process — fails after one short retry instead of sleeping through
the throttle ladder every night)."""
import pytest
import requests

from councilhound import http


class _FakeResp:
    def __init__(self, status=206):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)

    def iter_content(self, chunk_size=0):
        return iter([b"data"])

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses) if responses else None

    def get(self, url, stream=False, timeout=0, headers=None):
        self.calls.append({"url": url, "headers": headers})
        if self._responses:
            return self._responses.pop(0)
        return _FakeResp(206)


@pytest.fixture(autouse=True)
def _cold_archive(monkeypatch):
    """Each test starts with the process never having reached archive-video."""
    monkeypatch.setattr(http, "_archive_ok", False)


def _patch(monkeypatch, session):
    monkeypatch.setattr(http, "get_http_session", lambda: session)
    monkeypatch.setattr(http, "_throttle", lambda: None)
    sleeps = []
    monkeypatch.setattr(http.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


ARCHIVE_URL = "https://archive-video.granicus.com/fairfax/x.mp3"


def test_download_drops_referer_for_archive_video(monkeypatch, tmp_path):
    fake = _FakeSession()
    _patch(monkeypatch, fake)
    http.download(ARCHIVE_URL, str(tmp_path / "o.bin"))
    assert fake.calls[0]["headers"] == {"Referer": None}  # None drops the granicus Referer


def test_download_keeps_default_headers_for_other_hosts(monkeypatch, tmp_path):
    fake = _FakeSession()
    _patch(monkeypatch, fake)
    http.download("https://fairfax.granicus.com/DocumentViewer.php?file=a.pdf", str(tmp_path / "o.bin"))
    assert fake.calls[0]["headers"] is None  # session defaults (incl. Referer) unchanged


def test_download_cold_403_then_success_still_recovers(monkeypatch, tmp_path):
    # a single cold 403 could still be throttling: one short retry is kept
    fake = _FakeSession([_FakeResp(403), _FakeResp(206)])
    _patch(monkeypatch, fake)
    http.download(ARCHIVE_URL, str(tmp_path / "o.bin"))
    assert len(fake.calls) == 2  # retried past the first 403


def test_download_cold_403_fails_fast(monkeypatch, tmp_path):
    # before any success, persistent 403 means an IP block: seconds, not the
    # 30/60/90 ladder that used to burn 180s per meeting per night on Fly
    fake = _FakeSession([_FakeResp(403)] * (len(http.ARCHIVE_COLD_WAITS) + 1))
    sleeps = _patch(monkeypatch, fake)
    with pytest.raises(requests.exceptions.HTTPError):
        http.download(ARCHIVE_URL, str(tmp_path / "o.bin"))
    assert len(fake.calls) == len(http.ARCHIVE_COLD_WAITS) + 1
    assert sleeps == list(http.ARCHIVE_COLD_WAITS)


def test_download_success_arms_throttle_ladder(monkeypatch, tmp_path):
    fake = _FakeSession()
    _patch(monkeypatch, fake)
    http.download(ARCHIVE_URL, str(tmp_path / "o.bin"))
    assert http._archive_ok is True


def test_download_warm_403_uses_full_ladder(monkeypatch, tmp_path):
    # once the host has succeeded, 403 really is throttling: full back-off
    monkeypatch.setattr(http, "_archive_ok", True)
    fake = _FakeSession([_FakeResp(403), _FakeResp(403), _FakeResp(403), _FakeResp(206)])
    sleeps = _patch(monkeypatch, fake)
    http.download(ARCHIVE_URL, str(tmp_path / "o.bin"))
    assert len(fake.calls) == len(http.ARCHIVE_THROTTLE_WAITS) + 1
    assert sleeps == list(http.ARCHIVE_THROTTLE_WAITS)


def test_download_warm_gives_up_after_persistent_403(monkeypatch, tmp_path):
    # 403 on every attempt (1 initial + len(waits) retries) → raises, leaving it
    # for the next daily run rather than looping forever
    monkeypatch.setattr(http, "_archive_ok", True)
    fake = _FakeSession([_FakeResp(403)] * (len(http.ARCHIVE_THROTTLE_WAITS) + 1))
    _patch(monkeypatch, fake)
    with pytest.raises(requests.exceptions.HTTPError):
        http.download(ARCHIVE_URL, str(tmp_path / "o.bin"))
    assert len(fake.calls) == len(http.ARCHIVE_THROTTLE_WAITS) + 1
