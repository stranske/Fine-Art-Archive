"""Shared helpers for collection source adapters."""

from __future__ import annotations

import shlex


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
    return f"""set -e
mkdir -p "$(dirname {out_q})"
python3 <<'PYEOF'
{python_body.rstrip()}
PYEOF
URL=$(cat {temp_url_path})
curl -sL -A {shlex.quote(curl_user_agent)} -w 'HTTP %{{http_code}} %{{size_download}} bytes in %{{time_total}}s\\n' \\
     -o {out_q} "$URL"
rm -f {temp_url_path}
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
