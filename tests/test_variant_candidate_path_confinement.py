"""The variant-upgrade candidate path, which is read from a CSV this app does not write.

`variant_candidate_image` serves a LOCAL FILE whose path comes from the detector's CSV. Its own
docstring says why that matters — *"this endpoint reads local files, so an unchecked path would be
an arbitrary-file-read"* — and nothing tested the check.

The CSV is the untrusted input here, not the URL. It is produced by a separate detector, sits on
the same Dropbox volume as everything else, and is not validated on write. A row pointing at
`/etc/passwd` or `~/.ssh/id_rsa` would otherwise be served to whoever opens the upgrade view.

`_variant_candidate_path` applies the same confinement for the listing, and the two must agree:
a path the listing shows as available but the image endpoint refuses is a broken row in the UI,
and the reverse is the hole.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive.api import main as api_main
from fine_art_archive.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A permitted works root, a permitted staging root, and somewhere outside both."""
    art = tmp_path / "Art" / "works"
    staging = tmp_path / "Art" / "staging_acquisitions"
    outside = tmp_path / "elsewhere"
    for directory in (art, staging, outside):
        directory.mkdir(parents=True)

    monkeypatch.setattr(api_main, "VARIANT_CANDIDATE_ROOTS", (art, staging))
    monkeypatch.setattr(
        api_main, "VARIANT_UPGRADE_CSV", tmp_path / "variant_upgrade_candidates.csv"
    )
    monkeypatch.setattr(api_main, "IMAGE_CACHE_DIR", tmp_path / "image_cache")
    return {"art": art, "staging": staging, "outside": outside, "root": tmp_path}


def _image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), (10, 20, 30)).save(path, "JPEG")
    return path


def _csv_rows(roots: dict[str, Path], *rows: tuple[str, str]) -> None:
    with open(api_main.VARIANT_UPGRADE_CSV, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["existing_wid", "candidate_path"])
        writer.writeheader()
        for wid, path in rows:
            writer.writerow({"existing_wid": wid, "candidate_path": path})


_WID = "abc1234-a-painting-someone"


# ---------------------------------------------------------------------------------------------
# Paths inside a permitted root.
# ---------------------------------------------------------------------------------------------


def test_a_candidate_inside_the_works_root_is_served(client, roots):
    candidate = _image(roots["art"] / _WID / "candidate.jpg")
    _csv_rows(roots, (_WID, str(candidate)))

    response = client.get(f"/variant_upgrades/{_WID}/candidate_image")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"


def test_a_candidate_inside_the_staging_root_is_served(client, roots):
    """Upgrades are staged before promotion, so staging is a legitimate location — and listing it
    as permitted is what keeps the guard from blocking the normal path."""
    candidate = _image(roots["staging"] / "incoming.jpg")
    _csv_rows(roots, (_WID, str(candidate)))

    assert client.get(f"/variant_upgrades/{_WID}/candidate_image").status_code == 200


def test_the_same_path_resolves_the_same_way_for_the_listing_helper(roots):
    """`_variant_candidate_path` and the endpoint must agree. A path the listing offers but the
    image endpoint refuses is a broken row; the reverse is the hole."""
    candidate = _image(roots["art"] / _WID / "candidate.jpg")
    _csv_rows(roots, (_WID, str(candidate)))

    assert api_main._variant_candidate_path(_WID) == candidate.resolve()


# ---------------------------------------------------------------------------------------------
# Paths outside every permitted root.
# ---------------------------------------------------------------------------------------------


def test_a_candidate_outside_every_root_is_refused(client, roots):
    """The whole guard, stated plainly."""
    candidate = _image(roots["outside"] / "secret.jpg")
    _csv_rows(roots, (_WID, str(candidate)))

    response = client.get(f"/variant_upgrades/{_WID}/candidate_image")

    assert response.status_code == 403
    assert "permitted roots" in response.json()["detail"]


def test_a_traversal_out_of_a_permitted_root_is_refused(client, roots):
    """`resolve()` before the check is what makes this work: the literal string starts inside the
    works root, and only resolution reveals that it does not stay there."""
    _image(roots["outside"] / "secret.jpg")
    traversal = str(roots["art"] / ".." / ".." / "elsewhere" / "secret.jpg")
    _csv_rows(roots, (_WID, traversal))

    assert client.get(f"/variant_upgrades/{_WID}/candidate_image").status_code == 403


@pytest.mark.parametrize("target", ["/etc/passwd", "/etc/hosts"])
def test_an_absolute_system_path_is_refused(client, roots, target):
    """The row the CSV would have to contain for this to be an arbitrary-file-read."""
    _csv_rows(roots, (_WID, target))

    assert client.get(f"/variant_upgrades/{_WID}/candidate_image").status_code == 403


def test_a_tilde_path_is_expanded_before_it_is_checked(client, roots, monkeypatch):
    """`expanduser()` has to run BEFORE the confinement check, and the only way to see that is to
    make expansion change the answer.

    HOME is pointed at a directory containing a permitted root, so `~/Art/works/...` expands to a
    path inside one. Without expansion the same string resolves to `<cwd>/~/Art/...` — outside
    every root, refused for the wrong reason. A test that only fed it `~/.ssh/id_rsa` would see
    403 either way and prove nothing, which is what the first version of this test did.
    """
    monkeypatch.setenv("HOME", str(roots["root"]))
    _image(roots["art"] / _WID / "candidate.jpg")
    _csv_rows(roots, (_WID, f"~/Art/works/{_WID}/candidate.jpg"))

    assert client.get(f"/variant_upgrades/{_WID}/candidate_image").status_code == 200


def test_the_listing_helper_expands_a_tilde_too(roots, monkeypatch):
    """The endpoint and the helper must resolve a path the SAME way, or the listing and the image
    disagree about which candidates exist. Mirrored deliberately, since one expanding and the
    other not is exactly the drift that produces a row you can see and cannot open."""
    monkeypatch.setenv("HOME", str(roots["root"]))
    candidate = _image(roots["art"] / _WID / "candidate.jpg")
    _csv_rows(roots, (_WID, f"~/Art/works/{_WID}/candidate.jpg"))

    assert api_main._variant_candidate_path(_WID) == candidate.resolve()


def test_a_home_relative_path_outside_the_roots_is_still_refused(client, roots, monkeypatch):
    """Expansion is not permission. `~/.ssh/id_rsa` expands to a real path and is still outside
    every permitted root."""
    monkeypatch.setenv("HOME", str(roots["root"]))
    _image(roots["outside"] / "secret.jpg")
    _csv_rows(roots, (_WID, "~/elsewhere/secret.jpg"))

    assert client.get(f"/variant_upgrades/{_WID}/candidate_image").status_code == 403


def test_the_listing_helper_refuses_the_same_paths(roots):
    _image(roots["outside"] / "secret.jpg")
    _csv_rows(roots, (_WID, str(roots["outside"] / "secret.jpg")))

    assert api_main._variant_candidate_path(_WID) is None


# ---------------------------------------------------------------------------------------------
# Malformed and missing inputs.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("wid", ["%2E%2E", "%2E%2E%5Cmeta", "with space", "nul%00byte"])
def test_a_malformed_work_id_is_refused_by_the_validator(client, roots, wid):
    """The work id indexes the CSV. Validating it first keeps a traversal out of the lookup as
    well as out of the path.

    Sent URL-ENCODED on purpose: a raw `../etc` changes the request path and never reaches this
    route, so testing it would prove only that FastAPI routes. These forms arrive as a single
    path segment — the shape an attacker actually gets to choose — and reach `validate_work_id`.
    """
    _csv_rows(roots, (_WID, str(_image(roots["art"] / _WID / "c.jpg"))))

    response = client.get(f"/variant_upgrades/{wid}/candidate_image")

    assert response.status_code == 400


@pytest.mark.parametrize("wid", ["..%2Fetc", "a%2Fb"])
def test_an_embedded_slash_never_reaches_the_route_at_all(client, roots, wid):
    """`%2F` decodes to a path separator before routing, so these become a different URL and
    404 rather than 400.

    Asserted as its own case rather than folded into an `in (400, 404)`: the two refusals come
    from different layers, and a test that accepts either would still pass if the VALIDATOR
    stopped working and only the router was left.
    """
    _csv_rows(roots, (_WID, str(_image(roots["art"] / _WID / "c.jpg"))))

    assert client.get(f"/variant_upgrades/{wid}/candidate_image").status_code == 404


@pytest.mark.parametrize("wid", ["..", "../etc", "a/b", "with space", "nul\x00byte", "~/x"])
def test_the_listing_helper_refuses_a_malformed_work_id_directly(roots, wid):
    """The same vocabulary, checked without the HTTP layer — some of these cannot be expressed as
    a URL at all, and the guard is in the function rather than the router.

    The CSV holds a row KEYED BY THE MALFORMED ID pointing at a real file inside a permitted
    root, so the helper would happily return that path if the validation were removed. Without
    that row the test passes for the wrong reason: no match, therefore None, whatever the guard
    does — which is how the first version of this test survived a deliberate break.
    """
    reachable = _image(roots["art"] / _WID / "c.jpg")
    _csv_rows(roots, (wid, str(reachable)))

    assert api_main._variant_candidate_path(wid) is None


def test_a_missing_csv_is_a_404_not_a_crash(client, roots):
    """The detector may never have run. That is "nothing to review", not an error."""
    response = client.get(f"/variant_upgrades/{_WID}/candidate_image")

    assert response.status_code == 404
    assert "no variant upgrade candidates" in response.json()["detail"]


def test_a_work_with_no_row_is_a_404(client, roots):
    _csv_rows(roots, ("other-wid-here-ok", str(_image(roots["art"] / "x" / "c.jpg"))))

    response = client.get(f"/variant_upgrades/{_WID}/candidate_image")

    assert response.status_code == 404
    assert _WID in response.json()["detail"]


def test_a_row_with_a_blank_path_is_a_404(client, roots, monkeypatch):
    """An empty cell is not a path.

    `Path("").resolve()` is the CURRENT WORKING DIRECTORY, so a blank cell becomes a real,
    existing directory. Whether that is refused then depends on where the process happens to be
    running — which is why the permitted roots here include the cwd: with the guard the row is a
    404, and without it the blank resolves inside a permitted root and is served.
    """
    monkeypatch.setattr(
        api_main, "VARIANT_CANDIDATE_ROOTS", (roots["art"], roots["staging"], Path.cwd())
    )
    _csv_rows(roots, (_WID, "   "))

    assert client.get(f"/variant_upgrades/{_WID}/candidate_image").status_code == 404


def test_the_listing_helper_refuses_a_blank_path_for_the_same_reason(roots, monkeypatch):
    monkeypatch.setattr(
        api_main, "VARIANT_CANDIDATE_ROOTS", (roots["art"], roots["staging"], Path.cwd())
    )
    _csv_rows(roots, (_WID, "   "))

    assert api_main._variant_candidate_path(_WID) is None


def test_a_permitted_path_that_is_not_on_disk_is_a_404(client, roots):
    """Distinct from 403: the row is legitimate and the file has moved. Reporting it as forbidden
    would send the operator looking for a permissions problem that does not exist."""
    _csv_rows(roots, (_WID, str(roots["art"] / _WID / "gone.jpg")))

    response = client.get(f"/variant_upgrades/{_WID}/candidate_image")

    assert response.status_code == 404
    assert "not on disk" in response.json()["detail"]


def test_a_directory_inside_a_permitted_root_is_not_served_as_a_file(client, roots):
    (roots["art"] / _WID).mkdir(parents=True, exist_ok=True)
    _csv_rows(roots, (_WID, str(roots["art"] / _WID)))

    assert client.get(f"/variant_upgrades/{_WID}/candidate_image").status_code == 404


def test_the_listing_helper_is_quiet_about_every_malformed_input(roots):
    """It feeds a listing, so it returns None rather than raising — but the confinement is the
    same, which is the property that matters."""
    assert api_main._variant_candidate_path("") is None
    assert api_main._variant_candidate_path("../etc") is None

    _csv_rows(roots, (_WID, ""))
    assert api_main._variant_candidate_path(_WID) is None
