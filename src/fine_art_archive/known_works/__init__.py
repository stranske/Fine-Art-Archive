"""Known-works subsystem.

Per-artist reference lists of canonical works, fetched from multiple
independent sources and merged. See `known_works_sources_design.md`.
"""

from .fetchers import (
    KnownWork,
    fetch_met,
    fetch_wikidata_sparql,
    fetch_wikipedia_list,
    merge_works,
    works_to_dicts,
)

__all__ = [
    "KnownWork",
    "fetch_met",
    "fetch_wikipedia_list",
    "fetch_wikidata_sparql",
    "merge_works",
    "works_to_dicts",
]
