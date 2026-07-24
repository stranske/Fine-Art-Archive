"""Best-effort metadata enrichment for archive sidecars."""

from fine_art_archive.enrichment.holder import (
    HolderClient,
    HolderLookup,
    WikidataClient,
    complete_holder,
)

__all__ = [
    "HolderClient",
    "HolderLookup",
    "WikidataClient",
    "complete_holder",
]
