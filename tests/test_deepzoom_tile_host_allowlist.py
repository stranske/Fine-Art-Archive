"""The deep-zoom tile allowlist must compare a parsed host, not a substring.

Audit finding 33 (2026-08-08). The guard was:

    if _DZ_TILE_HOST not in tile_base:

a substring test over the WHOLE URL. Three shapes defeat it, and because the
fetched bytes are returned to the caller AND cached, this is a read primitive
rather than merely an outbound request.

The suffix-domain case matters most: it needs no hand-edited sidecar, only a
hostile or compromised upstream supplying a tile base.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from fine_art_archive.api.main import _DZ_TILE_HOST, _assert_allowed_tile_host

ALLOWED = f"https://{_DZ_TILE_HOST}"

BYPASSES = {
    "host-in-path": f"https://evil.example/{_DZ_TILE_HOST}/tiles",
    "host-in-query": f"https://evil.example/tiles?x={_DZ_TILE_HOST}",
    "suffix-domain": f"https://{_DZ_TILE_HOST}.evil.example/tiles",
    "host-in-fragment": f"https://evil.example/tiles#{_DZ_TILE_HOST}",
    "userinfo-host": f"https://{_DZ_TILE_HOST}@evil.example/tiles",
}


class TestBypassesAreRejected:
    @pytest.mark.parametrize("name", sorted(BYPASSES))
    def test_substring_bypass_is_rejected(self, name: str) -> None:
        with pytest.raises(HTTPException) as excinfo:
            _assert_allowed_tile_host(BYPASSES[name])
        assert excinfo.value.status_code == 502

    def test_userinfo_cannot_smuggle_the_allowed_host(self) -> None:
        """`https://allowed@evil.example` has hostname evil.example.

        This is why the comparison must use `hostname`, not `netloc`.
        """
        with pytest.raises(HTTPException):
            _assert_allowed_tile_host(BYPASSES["userinfo-host"])


class TestTransportRequirements:
    def test_plain_http_is_rejected(self) -> None:
        with pytest.raises(HTTPException, match="https"):
            _assert_allowed_tile_host(f"http://{_DZ_TILE_HOST}/tiles")

    def test_embedded_credentials_are_rejected(self) -> None:
        with pytest.raises(HTTPException, match="credentials"):
            _assert_allowed_tile_host(f"https://user:pw@{_DZ_TILE_HOST}/tiles")


class TestLegitimateSourceStillWorks:
    """Proves the capability was constrained, not disabled."""

    @pytest.mark.parametrize(
        "url",
        [
            ALLOWED,
            f"{ALLOWED}/",
            f"{ALLOWED}/tiles/deepzoom",
            f"https://{_DZ_TILE_HOST.upper()}/tiles",  # host compare is case-insensitive
        ],
    )
    def test_allowed_host_passes(self, url: str) -> None:
        _assert_allowed_tile_host(url)
