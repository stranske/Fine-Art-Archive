"""The deep-zoom tile allowlist must compare hosts, not search strings.

Audit finding 33 (2026-08-08). The guard was::

    if _DZ_TILE_HOST not in tile_base:

a substring test over the whole URL, so the allowed host appearing anywhere —
path, query, or as a prefix of a longer domain — satisfied it.

Why it matters more than a stray outbound request: the fetched bytes are
returned to the caller *and written to the tile cache*, so a bypass is a read
primitive. And `tile_base` originates in sidecar data whose provenance is
third-party museum APIs, so the suffix-domain case needs no hand-edited file to
reach — a hostile or compromised upstream is enough.
"""

from __future__ import annotations

import pytest

from fine_art_archive.api.main import _DZ_TILE_HOST, _tile_source_allowed

LEGIT = f"https://{_DZ_TILE_HOST}/tiles"


class TestBypassesAreRejected:
    """Each string below passed the old substring guard."""

    def test_path_injected_host_is_rejected(self) -> None:
        ok, why = _tile_source_allowed(f"https://evil.example/{_DZ_TILE_HOST}/x")
        assert ok is False
        assert "host not allowed" in why

    def test_query_injected_host_is_rejected(self) -> None:
        ok, _ = _tile_source_allowed(f"https://evil.example/?x={_DZ_TILE_HOST}")
        assert ok is False

    def test_suffix_domain_is_rejected(self) -> None:
        """The one reachable from a hostile upstream rather than a hand edit."""
        ok, _ = _tile_source_allowed(f"https://{_DZ_TILE_HOST}.evil.example/t")
        assert ok is False

    def test_credentials_in_url_are_rejected(self) -> None:
        ok, why = _tile_source_allowed(f"https://user:pw@{_DZ_TILE_HOST}/t")
        assert ok is False
        assert "credentials" in why

    def test_plain_http_is_rejected(self) -> None:
        ok, why = _tile_source_allowed(f"http://{_DZ_TILE_HOST}/t")
        assert ok is False
        assert "https" in why

    @pytest.mark.parametrize(
        "url",
        [
            "https://localhost/t",
            "https://127.0.0.1/t",
            "https://[::1]/t",
            "https://169.254.169.254/latest/meta-data/",  # cloud metadata
        ],
    )
    def test_other_hosts_are_rejected(self, url: str) -> None:
        assert _tile_source_allowed(url)[0] is False


class TestLegitimateSourceStillWorks:
    """Proving the capability was constrained, not disabled."""

    def test_legitimate_tile_host_is_allowed(self) -> None:
        assert _tile_source_allowed(LEGIT)[0] is True

    def test_host_comparison_is_case_insensitive(self) -> None:
        assert _tile_source_allowed(f"https://{_DZ_TILE_HOST.upper()}/t")[0] is True

    def test_explicit_port_is_allowed(self) -> None:
        """`hostname` strips the port; `netloc` would not, and would reject this."""
        assert _tile_source_allowed(f"https://{_DZ_TILE_HOST}:8443/t")[0] is True


def test_rejection_happens_before_any_fetch_or_cache_write() -> None:
    """The check is pure — it cannot itself touch the network or the cache.

    Asserting on the *decision* rather than a status code matters: a test that
    only checked the response would pass even if the request had been issued.
    """
    import inspect

    src = inspect.getsource(_tile_source_allowed)
    for forbidden in ("urlopen", "Request(", "write_bytes", "mkdir"):
        assert forbidden not in src, f"{forbidden} must not appear in the guard"
