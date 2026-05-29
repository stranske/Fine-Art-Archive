"""Google Arts & Culture collector — wraps dezoomify-rs.

Background: many partner-museum works are available on Google Arts & Culture
at high deep-zoom resolution, even when the holding museum's own direct
endpoints serve only moderate resolution (Met, National Gallery London) or
no public direct access at all (NGL post-2024). For those works, GAC +
dezoomify-rs is the realistic path to museum-quality high-res.

Requires `dezoomify-rs` to be installed locally:

    brew install dezoomify-rs        # macOS
    cargo install dezoomify-rs       # any platform with Rust

Asset URL pattern: https://artsandculture.google.com/asset/<slug>/<asset-id>

The dezoomify-rs CLI is interactive by default (prompts for which zoom
level); we always pass `--largest` to skip the prompt and grab the maximum
available. Typical maximum is 5000-10000 px on the long edge — comparable
to a real museum master and a major upgrade over the Met's primaryImage.
"""

from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class GACAsset:
    """A handle for a single Google Arts & Culture asset.

    The asset_url is the public viewing page URL; dezoomify-rs walks the
    page's embedded tile metadata to discover and download the pyramid.
    """

    asset_url: str  # e.g. https://artsandculture.google.com/asset/<slug>/<id>


def acquire_command(asset: GACAsset, out_path: str, retries: int = 3) -> list[str]:
    """Build the dezoomify-rs command for an asset.

    Returns the command line as a list of arguments suitable for subprocess
    or for shlex.join into a shell string.
    """
    return [
        "dezoomify-rs",
        "--largest",
        "--retries",
        str(retries),
        asset.asset_url,
        out_path,
    ]


def acquire_shell_script(asset: GACAsset, out_path: str) -> str:
    """Shell script for osascript+curl-style invocation.

    Includes a check for dezoomify-rs presence and an install hint if absent.
    Driven via osascript do shell script from the orchestrator host.
    """
    cmd = " ".join(shlex.quote(p) for p in acquire_command(asset, out_path))
    return f"""set -e
if ! command -v dezoomify-rs >/dev/null 2>&1; then
  echo "dezoomify-rs not installed. Install with: brew install dezoomify-rs" >&2
  exit 4
fi
mkdir -p "$(dirname {shlex.quote(out_path)})"
{cmd}
file {shlex.quote(out_path)}
shasum -a 256 {shlex.quote(out_path)}
"""


def is_dezoomify_available() -> bool:
    """Check whether dezoomify-rs is on the PATH (sandbox-safe; just calls which)."""
    return shutil.which("dezoomify-rs") is not None


# Known partner museums (informational, used by discovery to know when to
# attempt GAC route). Updated alongside config/host_registry.yaml.
KNOWN_PARTNERS = {
    # museum Wikidata Q-ID: human label
    "Q180788": "National Gallery, London",
    "Q160236": "The Metropolitan Museum of Art",
    "Q190804": "Rijksmuseum",
    "Q239303": "Art Institute of Chicago",
    "Q214867": "National Gallery of Art (Washington)",
    "Q657415": "Cleveland Museum of Art",
    "Q23402": "Musée du Louvre",
    "Q15981": "Tate",
    "Q188740": "The British Museum",
    # ... extend as the discovery process surfaces more.
}
