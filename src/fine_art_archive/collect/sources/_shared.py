"""Shared helpers for collection source adapters."""

from __future__ import annotations

import shlex
from collections.abc import Mapping


def normalize_rights_status(value: object, *, fallback: str = "rights-reserved") -> str:
    """Map common source-rights values onto the sidecar status enum.

    Collection APIs use several spellings for the same public-domain
    dedication. Keeping this conversion at the adapter boundary prevents a raw
    provider value such as ``CC0`` from reaching the strict sidecar schema.
    """
    if isinstance(value, Mapping):
        value = value.get("status") or value.get("license") or value.get("name")
    if not isinstance(value, str):
        return fallback

    normalized = " ".join(value.casefold().replace("_", "-").split())
    if normalized in {
        "public-domain",
        "public domain",
        "pd",
        "cc0",
        "cc0 1.0",
        "cc0-1.0",
        "creativecommons zero",
        "creative commons zero",
    }:
        return "public-domain"
    if normalized.startswith(("cc-by", "cc by", "creative commons attribution")):
        return "rights-reserved"
    return fallback


def quoted_output_path(out_path: str) -> str:
    """Return a shell-safe output path used by acquisition scripts."""
    return shlex.quote(out_path)


def render_image_acquire_shell(
    *,
    out_path: str,
    python_body: str,
    temp_url_path: str,
    curl_user_agent: str = "Mozilla/5.0",
) -> str:
    """Render the common Python-resolve -> curl -> verify shell scaffold."""
    out_q = quoted_output_path(out_path)
    temp_url_q = shlex.quote(temp_url_path)
    return f"""set -e
mkdir -p "$(dirname {out_q})"
python3 <<'PYEOF'
{python_body.rstrip()}
PYEOF
URL=$(cat {temp_url_q})
curl -sL -A {shlex.quote(curl_user_agent)} -w 'HTTP %{{http_code}} %{{size_download}} bytes in %{{time_total}}s\\n' \\
     -o {out_q} "$URL"
rm -f {temp_url_q}
file {out_q}
shasum -a 256 {out_q}
"""


def holder_fields(
    *, name: str, wikidata_q: str, ror: str, url: str | None
) -> dict[str, str | None]:
    """Return the sidecar holder block shared across museum normalizers."""
    return {
        "holder_name": name,
        "holder_wikidata_q": wikidata_q,
        "holder_ror": ror,
        "holder_url": url,
    }


def year_fields(
    *,
    year: str | int | None,
    year_min: str | int | None,
    year_max: str | int | None,
) -> dict[str, str | int | None]:
    """Return sidecar year keys with consistent spelling."""
    return {"year": year, "year_min": year_min, "year_max": year_max}
