"""HTTP download header + throttle behavior. Two guarantees worth pinning:
media on archive-video.granicus.com is behind hotlink protection that 403s any
cross-host Referer (so download() omits the session's granicus Referer for that
host), and that host rate-limits bursty access with 403s (so download() backs
off and retries rather than failing on the first 403)."""
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


def _patch(monkeypatch, session):
    monkeypatch.setattr(http, "get_http_session", lambda: session)
    monkeypatch.setattr(http, "_throttle", lambda: None)
    monkeypatch.setattr(http.time, "sleep", lambda _s: None)


def test_download_drops_referer_for_archive_video(monkeypatch, tmp_path):
    fake = _FakeSession()
    _patch(monkeypatch, fake)
    http.download("https://archive-video.granicus.com/fairfax/x.mp3", str(tmp_path / "o.bin"))
    assert fake.calls[0]["headers"] == {"Referer": None}  # None drops the granicus Referer


def test_download_keeps_default_headers_for_other_hosts(monkeypatch, tmp_path):
    fake = _FakeSession()
    _patch(monkeypatch, fake)
    http.download("https://fairfax.granicus.com/DocumentViewer.php?file=a.pdf", str(tmp_path / "o.bin"))
    assert fake.calls[0]["headers"] is None  # session defaults (incl. Referer) unchanged


def test_download_retries_archive_video_throttle(monkeypatch, tmp_path):
    # 403 (throttled) then 206: download() should back off and succeed
    fake = _FakeSession([_FakeResp(403), _FakeResp(206)])
    _patch(monkeypatch, fake)
    http.download("https://archive-video.granicus.com/fairfax/x.mp3", str(tmp_path / "o.bin"))
    assert len(fake.calls) == 2  # retried past the first 403


def test_download_gives_up_after_persistent_403(monkeypatch, tmp_path):
    # 403 on every attempt (1 initial + len(waits) retries) → raises, leaving it
    # for the next daily run rather than looping forever
    fake = _FakeSession([_FakeResp(403)] * (len(http.ARCHIVE_THROTTLE_WAITS) + 1))
    _patch(monkeypatch, fake)
    try:
        http.download("https://archive-video.granicus.com/fairfax/x.mp3", str(tmp_path / "o.bin"))
        assert False, "expected HTTPError after persistent 403"
    except requests.exceptions.HTTPError:
        pass
    assert len(fake.calls) == len(http.ARCHIVE_THROTTLE_WAITS) + 1
