"""Artist identity / canonicalization subsystem.

See `artist_name_normalization_design.md`. Step 1: resolver + preview CSV
(no sidecar writes). Step 2 (later): schema extension + bulk update.
"""

from .artist_resolver import (
    AliasEntry,
    ResolvedArtist,
    build_alias_table,
    fold_name,
    resolve_artist,
)

__all__ = [
    "AliasEntry",
    "ResolvedArtist",
    "build_alias_table",
    "fold_name",
    "resolve_artist",
]
