"""The candidate-image proxy: its SSRF guard, its retries, and its cache.

Two endpoints here read something the caller did not supply — one a remote URL, one a local file —
and both say so in their own docstrings: *"an endpoint that fetches whatever URL it is handed is an
SSRF"*, and *"an unchecked path would be an arbitrary-file-read"*. Those sentences were the only
thing holding the property. Nothing tested it.

The retry logic beside them encodes a second judgement worth keeping: 429 and 503 mean "ask again
later", not "this image is unavailable". Collapsing them into a failure reports a temporary
condition as a permanent one, and the operator sees a candidate they can never review.

Everything below is offline. `urlopen` is replaced, so a test that started making real requests
would be failing in a way this suite can see.
"""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive.api import gates as api_gates
from fine_art_archive.api import main as api_main
from fine_art_archive.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test image cache, so one test's stored rendition is not another's cache hit."""
    cache = tmp_path / "image_cache"
    monkeypatch.setattr(api_main, "IMAGE_CACHE_DIR", cache)
    return cache


def _png_bytes(size: tuple[int, int] = (2000, 1200)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (120, 90, 60)).save(buffer, "PNG")
    return buffer.getvalue()


class _Body:
    """Enough of an `http.client.HTTPResponse` for `with urlopen(...) as r: r.read(n)`."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, amount: int | None = None) -> bytes:
        return self._payload if amount is None else self._payload[:amount]

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


class _Transport:
    """Records every request the proxy makes, and replies from a scripted list."""

    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.urls: list[str] = []
        self.headers: list[dict] = []
        self.timeouts: list[float | None] = []

    def __call__(self, request, timeout=None):  # noqa: ANN001 - mirrors urlopen
        self.urls.append(request.full_url)
        self.headers.append(dict(request.headers))
        self.timeouts.append(timeout)
        reply = self.replies.pop(0) if self.replies else _Body(_png_bytes())
        if isinstance(reply, Exception):
            raise reply
        return reply


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("https://example.test/x.jpg", code, "throttled", headers, None)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch):
    def install(*replies: object) -> _Transport:
        fake = _Transport(*replies)
        monkeypatch.setattr(api_main.urllib.request, "urlopen", fake)
        monkeypatch.setattr(api_main.time, "sleep", lambda seconds: None)
        return fake

    return install


@pytest.fixture
def frontier_url(monkeypatch: pytest.MonkeyPatch):
    def install(url: str | None) -> None:
        monkeypatch.setattr(api_gates, "candidate_image_url", lambda qid, **kwargs: url)
        monkeypatch.setattr(api_main.gates, "candidate_image_url", lambda qid, **kwargs: url)

    return install


# ---------------------------------------------------------------------------------------------
# The SSRF guard.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "qid",
    [
        "Q0",
        "Q01",
        "notaqid",
        "Q12345678901234",
        "Q12345 ",
        "../../etc/passwd",
        "Q1;rm -rf /",
        "",
    ],
)
def test_a_qid_that_is_not_a_qid_is_refused(client, qid, transport, frontier_url):
    """The Q-ID is the only caller-supplied input, so it is the only place an attacker can push.
    Anything that is not `Q` followed by a plain number never reaches a lookup."""
    fetches = transport()
    frontier_url("https://commons.wikimedia.org/x.jpg")

    response = client.get(f"/review/candidate/{qid}/image")

    assert response.status_code in (400, 404)
    assert fetches.urls == []


def test_a_qid_with_no_frontier_entry_is_a_404_not_a_fetch(client, transport, frontier_url):
    """The URL comes from the discovery pipeline's own frontier. A Q-ID nobody proposed has no
    URL, and inventing one is the SSRF this endpoint is shaped to prevent."""
    fetches = transport()
    frontier_url(None)

    response = client.get("/review/candidate/Q42/image")

    assert response.status_code == 404
    assert fetches.urls == []


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.test/x.jpg",
        "gopher://example.test/x",
        "data:image/png;base64,AAAA",
        "//example.test/x.jpg",
    ],
)
def test_a_frontier_url_with_a_disallowed_scheme_is_refused(client, url, transport, frontier_url):
    """Defence in depth: even a URL the pipeline chose is checked, because the frontier is a JSON
    file this app does not write. `file://` through `urlopen` is a local file read."""
    fetches = transport()
    frontier_url(url)

    response = client.get("/review/candidate/Q42/image")

    assert response.status_code == 502
    assert fetches.urls == []


def test_the_caller_cannot_choose_the_url_at_all(client, transport, frontier_url):
    """There is no parameter for it. The only thing fetched is what the frontier holds — asserted
    by handing the frontier a URL and confirming that exact one is requested."""
    fetches = transport()
    frontier_url("https://images.example.test/chosen-by-the-pipeline.jpg")

    client.get("/review/candidate/Q42/image?width=300")

    assert len(fetches.urls) == 1
    assert fetches.urls[0].startswith("https://images.example.test/chosen-by-the-pipeline.jpg")


# ---------------------------------------------------------------------------------------------
# Width handling.
# ---------------------------------------------------------------------------------------------


def test_commons_is_asked_for_a_scaled_rendition(client, cache_dir, transport, frontier_url):
    """Commons honours `?width=` and returns ~127 KB instead of 1.7 MB. Without it the card
    downloads megabytes it is about to throw away, and looks empty while it does."""
    fetches = transport()
    frontier_url("https://commons.wikimedia.org/wiki/Special:FilePath/X.jpg")

    assert client.get("/review/candidate/Q42/image?width=400").status_code == 200

    assert "width=400" in fetches.urls[0]


def test_a_commons_url_that_already_names_a_width_is_left_alone(
    client, cache_dir, transport, frontier_url
):
    """Appending a second `width=` produces a URL with two, and which one wins is the server's
    choice rather than ours."""
    fetches = transport()
    frontier_url("https://commons.wikimedia.org/wiki/Special:FilePath/X.jpg?width=64")

    client.get("/review/candidate/Q42/image?width=400")

    assert fetches.urls[0].count("width=") == 1


def test_a_non_commons_url_is_fetched_unchanged(client, cache_dir, transport, frontier_url):
    """Other hosts do not implement `?width=`, and adding it to a signed URL breaks the
    signature."""
    fetches = transport()
    frontier_url("https://images.example.test/x.jpg")

    client.get("/review/candidate/Q42/image?width=400")

    assert fetches.urls[0] == "https://images.example.test/x.jpg"


@pytest.mark.parametrize(
    "requested,expected", [(10, 120), (0, 120), (-50, 120), (99999, api_main.CANDIDATE_IMAGE_MAX)]
)
def test_the_requested_width_is_clamped(
    client, cache_dir, transport, frontier_url, requested, expected
):
    """A caller-controlled width is a caller-controlled amount of work. The floor keeps the card
    legible; the ceiling keeps one request from asking for a full-resolution decode."""
    fetches = transport()
    frontier_url("https://commons.wikimedia.org/x.jpg")

    assert client.get(f"/review/candidate/Q42/image?width={requested}").status_code == 200

    assert f"width={expected}" in fetches.urls[0]


def test_the_rendition_is_no_larger_than_the_requested_width(
    client, cache_dir, transport, frontier_url
):
    """The point of the proxy: whatever the source sends, what reaches the card is small."""
    transport(_Body(_png_bytes((2000, 1200))))
    frontier_url("https://images.example.test/x.jpg")

    response = client.get("/review/candidate/Q42/image?width=300")

    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as rendition:
        assert max(rendition.size) <= 300


# ---------------------------------------------------------------------------------------------
# Retries.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("code", [429, 503])
def test_a_throttling_response_is_retried(client, cache_dir, transport, frontier_url, code):
    """ "Ask again later" is not "unavailable". Failing here reports a temporary condition as a
    permanent one, and the operator sees a candidate they can never review."""
    fetches = transport(_http_error(code), _Body(_png_bytes()))
    frontier_url("https://images.example.test/x.jpg")

    assert client.get("/review/candidate/Q42/image").status_code == 200
    assert len(fetches.urls) == 2


@pytest.mark.parametrize("code", [400, 401, 403, 404, 410, 500])
def test_a_non_throttling_http_error_is_not_retried(
    client, cache_dir, transport, frontier_url, code
):
    """A 404 will still be a 404 in two seconds. Retrying it wastes the operator's wait and the
    source's patience."""
    fetches = transport(_http_error(code), _Body(_png_bytes()))
    frontier_url("https://images.example.test/x.jpg")

    response = client.get("/review/candidate/Q42/image")

    assert response.status_code == 502
    assert len(fetches.urls) == 1


@pytest.mark.parametrize("code", [429, 503])
def test_throttling_that_survives_every_retry_is_reported_as_temporary(
    client, cache_dir, transport, frontier_url, code
):
    """503 tells the browser to ask again; 502 would have it cache a broken image for the rest of
    the session."""
    transport(_http_error(code), _http_error(code), _http_error(code))
    frontier_url("https://images.example.test/x.jpg")

    response = client.get("/review/candidate/Q42/image")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "3"


def test_a_transport_error_is_retried_then_reported(client, cache_dir, transport, frontier_url):
    """A dropped connection is worth one more try; three is where it stops."""
    fetches = transport(OSError("connection reset"), OSError("connection reset"), OSError("nope"))
    frontier_url("https://images.example.test/x.jpg")

    response = client.get("/review/candidate/Q42/image")

    assert response.status_code == 502
    assert len(fetches.urls) == 3


def test_a_transport_error_that_clears_is_not_reported(client, cache_dir, transport, frontier_url):
    fetches = transport(OSError("connection reset"), _Body(_png_bytes()))
    frontier_url("https://images.example.test/x.jpg")

    assert client.get("/review/candidate/Q42/image").status_code == 200
    assert len(fetches.urls) == 2


def test_retry_after_is_honoured_when_the_server_sends_one(monkeypatch, transport, frontier_url):
    """The server said how long to wait. Ignoring it and using our own backoff is how a client
    gets rate-limited harder."""
    slept: list[float] = []
    monkeypatch.setattr(api_main.time, "sleep", slept.append)
    fake = _Transport(_http_error(429, retry_after="5"), _Body(_png_bytes()))
    monkeypatch.setattr(api_main.urllib.request, "urlopen", fake)

    api_main._fetch_candidate_bytes("https://images.example.test/x.jpg")

    assert slept == [5.0]


def test_an_unparseable_retry_after_falls_back_to_the_backoff(monkeypatch):
    """`Retry-After` may be an HTTP date, or absent, or nonsense. None of those may raise inside
    a retry loop."""
    slept: list[float] = []
    monkeypatch.setattr(api_main.time, "sleep", slept.append)
    fake = _Transport(_http_error(429, retry_after="Wed, 21 Oct 2026 07:28:00 GMT"), _Body(b"x"))
    monkeypatch.setattr(api_main.urllib.request, "urlopen", fake)

    api_main._fetch_candidate_bytes("https://images.example.test/x.jpg")

    assert slept == [1.5]


def test_a_retry_after_longer_than_the_cap_is_capped(monkeypatch):
    """A source asking for a five-minute wait would hold a request open for five minutes."""
    slept: list[float] = []
    monkeypatch.setattr(api_main.time, "sleep", slept.append)
    fake = _Transport(_http_error(503, retry_after="300"), _Body(b"x"))
    monkeypatch.setattr(api_main.urllib.request, "urlopen", fake)

    api_main._fetch_candidate_bytes("https://images.example.test/x.jpg")

    assert slept == [8.0]


def test_an_expired_deadline_stops_the_loop_before_another_request(monkeypatch):
    """The deadline bounds the WHOLE fetch, not each attempt. Without the check, three attempts
    at up to 30 s each could hold a request for 90 s past a 60 s budget."""
    fake = _Transport(_Body(b"x"))
    monkeypatch.setattr(api_main.urllib.request, "urlopen", fake)

    with pytest.raises(TimeoutError, match="deadline exceeded"):
        api_main._fetch_candidate_bytes(
            "https://images.example.test/x.jpg", deadline=api_main.time.monotonic() - 1
        )

    assert fake.urls == []


def test_the_per_attempt_timeout_never_outlives_the_deadline(monkeypatch):
    """A 30 s socket timeout inside a 2 s remaining budget overshoots by 28 s."""
    fake = _Transport(_Body(b"x"))
    monkeypatch.setattr(api_main.urllib.request, "urlopen", fake)

    api_main._fetch_candidate_bytes(
        "https://images.example.test/x.jpg", deadline=api_main.time.monotonic() + 2
    )

    assert fake.timeouts[0] is not None
    assert fake.timeouts[0] <= 2.0


def test_the_fetch_identifies_itself(monkeypatch):
    """Commons blocks unidentified bulk clients, and being blocked is indistinguishable from the
    image being gone."""
    fake = _Transport(_Body(b"x"))
    monkeypatch.setattr(api_main.urllib.request, "urlopen", fake)

    api_main._fetch_candidate_bytes("https://images.example.test/x.jpg")

    assert fake.headers[0].get("User-agent") == api_main.CANDIDATE_UA


# ---------------------------------------------------------------------------------------------
# Decoding and caching.
# ---------------------------------------------------------------------------------------------


def test_an_undecodable_body_is_reported_as_a_source_problem(
    client, cache_dir, transport, frontier_url
):
    """HTML error pages arrive with a 200 more often than anyone would like."""
    transport(_Body(b"<html>not an image</html>"))
    frontier_url("https://images.example.test/x.jpg")

    response = client.get("/review/candidate/Q42/image")

    assert response.status_code == 502
    assert "decode" in response.json()["detail"]


def test_a_second_request_is_served_from_cache(client, cache_dir, transport, frontier_url):
    """Six candidates per card, re-rendered on every scroll, is the load this cache exists for."""
    fetches = transport(_Body(_png_bytes()))
    frontier_url("https://images.example.test/x.jpg")

    assert client.get("/review/candidate/Q42/image?width=300").status_code == 200
    assert client.get("/review/candidate/Q42/image?width=300").status_code == 200

    assert len(fetches.urls) == 1


def test_a_different_width_is_a_different_cache_entry(client, cache_dir, transport, frontier_url):
    """Serving the 150 px rendition for a 900 px request would put a blurred image on the detail
    view."""
    fetches = transport(_Body(_png_bytes()), _Body(_png_bytes()))
    frontier_url("https://images.example.test/x.jpg")

    client.get("/review/candidate/Q42/image?width=300")
    client.get("/review/candidate/Q42/image?width=900")

    assert len(fetches.urls) == 2


def test_a_changed_source_url_is_a_different_cache_entry(
    client, cache_dir, transport, frontier_url
):
    """The frontier can re-point a candidate at a better scan. Keying on the Q-ID alone would
    serve the old picture forever."""
    fetches = transport(_Body(_png_bytes()), _Body(_png_bytes()))

    frontier_url("https://images.example.test/first.jpg")
    client.get("/review/candidate/Q42/image?width=300")
    frontier_url("https://images.example.test/second.jpg")
    client.get("/review/candidate/Q42/image?width=300")

    assert len(fetches.urls) == 2


def test_the_rendition_is_cacheable_by_the_browser(client, cache_dir, transport, frontier_url):
    transport(_Body(_png_bytes()))
    frontier_url("https://images.example.test/x.jpg")

    response = client.get("/review/candidate/Q42/image")

    assert response.headers["content-type"] == "image/jpeg"
    assert "max-age=86400" in response.headers["cache-control"]
