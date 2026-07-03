from __future__ import annotations

from fine_art_archive.collect.sources import artic, cleveland, met, rijksmuseum
from fine_art_archive.collect.sources._shared import render_image_acquire_shell


def test_artic_acquire_shell_keeps_direct_lookup_search_and_iiif_download() -> None:
    script = artic.acquire_shell_script(
        artic.ARTICObject("11723"), "/tmp/master image.jpg", "The Child's Bath", "Cassatt"
    )

    assert "OBJ_ID = '11723'" in script
    assert "fetch_artwork(OBJ_ID)" in script
    assert "artworks/search?" in script
    assert "is_public_domain" in script
    assert "/iiif/2/{image_id}/full/max/0/default.jpg" in script
    assert "URL=$(cat /tmp/artic_master_url)" in script
    assert "rm -f /tmp/artic_master_url" in script
    assert "-o '/tmp/master image.jpg' \"$URL\"" in script


def test_cleveland_acquire_shell_keeps_fallback_and_print_image_preference() -> None:
    script = cleveland.acquire_shell_script(
        cleveland.ClevelandObject("1942.647"), "/tmp/cle.jpg", "Head", "Rouault"
    )

    assert "ACC = '1942.647'" in script
    assert "import json, sys, urllib.error, urllib.parse, urllib.request" in script
    assert "fetch_artwork(ACC)" in script
    assert "title+artist search" in script
    assert "openaccess-api.clevelandart.org/api/artworks/?" in script
    assert "(images.get('print') or {}).get('url')" in script
    assert "URL=$(cat /tmp/cle_master_url)" in script
    assert "rm -f /tmp/cle_master_url" in script


def test_acquire_shell_quotes_temp_url_path() -> None:
    script = render_image_acquire_shell(
        out_path="/tmp/master image.jpg",
        python_body="print('ready')",
        temp_url_path="/tmp/source url.txt",
    )

    assert "URL=$(cat '/tmp/source url.txt')" in script
    assert "rm -f '/tmp/source url.txt'" in script
    assert "-o '/tmp/master image.jpg' \"$URL\"" in script


def test_holder_and_year_fields_are_preserved_for_museum_normalizers() -> None:
    artic_meta = artic.normalize_metadata(
        {
            "data": {
                "id": 11723,
                "title": "The Child's Bath",
                "date_display": "1893",
                "date_start": 1893,
                "date_end": 1893,
                "is_public_domain": True,
            }
        }
    )
    cleveland_meta = cleveland.normalize_metadata(
        {
            "data": {
                "accession_number": "1942.647",
                "title": "Head",
                "creation_date": "1907",
                "creation_date_earliest": 1907,
                "creation_date_latest": 1907,
                "share_license_status": "CC0",
            }
        }
    )
    met_meta = met.normalize_metadata(
        {
            "objectID": 12127,
            "title": "Madame X",
            "objectDate": "1883-84",
            "objectBeginDate": "1883",
            "objectEndDate": "1884",
            "isPublicDomain": True,
            "objectURL": "https://www.metmuseum.org/art/collection/search/12127",
        }
    )
    rijks_meta = rijksmuseum.normalize_metadata(
        {
            "artObject": {
                "title": "The Little Street",
                "dating": {
                    "presentingDate": "c. 1658",
                    "yearEarly": 1657,
                    "yearLate": 1661,
                },
            }
        }
    )

    assert artic_meta["holder_name"] == "Art Institute of Chicago"
    assert artic_meta["holder_wikidata_q"] == "Q239303"
    assert artic_meta["year_min"] == 1893
    assert cleveland_meta["holder_name"] == "Cleveland Museum of Art"
    assert cleveland_meta["holder_ror"] == "04em7w569"
    assert cleveland_meta["year"] == "1907"
    assert met_meta["holder_name"] == "The Metropolitan Museum of Art"
    assert met_meta["year_max"] == 1884
    assert rijks_meta["year"] == "c. 1658"
    assert rijks_meta["year_min"] == 1657
