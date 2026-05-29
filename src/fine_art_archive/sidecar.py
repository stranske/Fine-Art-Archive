"""Sidecar (meta.json) loader, validator, and minimal writer."""

from __future__ import annotations

import json
from pathlib import Path

# We import jsonschema lazily so the module is usable for plain read/write
# even when jsonschema isn't installed. Validation requires it.

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "meta.schema.json"


class SchemaNotFound(RuntimeError):  # noqa: N818  -- stable public name for importers
    pass


def load_schema() -> dict:
    """Load the JSON Schema document from the canonical schemas/ folder."""
    if not SCHEMA_PATH.exists():
        raise SchemaNotFound(f"schema not found at {SCHEMA_PATH}")
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def validate(meta: dict) -> None:
    """Raise jsonschema.ValidationError if meta is invalid; silent if valid."""
    import jsonschema  # imported lazily

    schema = load_schema()
    jsonschema.validate(instance=meta, schema=schema, format_checker=jsonschema.FormatChecker())


def is_valid(meta: dict) -> bool:
    """Boolean wrapper around validate()."""
    try:
        validate(meta)
    except Exception:
        return False
    return True


def load(path: Path | str) -> dict:
    """Read and return a sidecar dict from disk. Does NOT validate."""
    p = Path(path)
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def load_validated(path: Path | str) -> dict:
    """Read, validate, and return a sidecar dict."""
    meta = load(path)
    validate(meta)
    return meta


def write(path: Path | str, meta: dict, *, validate_first: bool = True) -> None:
    """Write a sidecar dict to disk as pretty JSON. Validates by default."""
    if validate_first:
        validate(meta)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")


def merge_history(meta: dict, event: dict) -> dict:
    """Append an event to meta.history. Mutates and returns the dict."""
    meta.setdefault("history", []).append(event)
    return meta


def get_master_sha256(meta: dict) -> str:
    """Convenience accessor for files.master.sha256."""
    return meta["files"]["master"]["sha256"]


def derive_work_id(master_sha256: str, slug: str) -> str:
    """Combine a 7-char hash prefix with a kebab-cased slug to form work_id.

    The schema pattern is ^[0-9a-f]{7}-[a-z0-9-]+$, so the slug must already
    be lower-cased and dash-separated. See slugify() helper if needed.
    """
    if len(master_sha256) < 7:
        raise ValueError("master_sha256 must be at least 7 chars")
    prefix = master_sha256[:7].lower()
    return f"{prefix}-{slug}"


def slugify(title: str, *, artist_surname: str | None = None, max_words: int = 6) -> str:
    """Slugify a title and optional artist surname into work_id-safe form.

    Examples:
        slugify("After the Bullfight", artist_surname="Cassatt")
            -> "after-the-bullfight-cassatt"
        slugify("Self-Portrait", artist_surname="Rembrandt")
            -> "self-portrait-rembrandt"
        slugify("Portrait of a Spanish Prince as Hunter (Philip II?)")
            -> "portrait-of-a-spanish-prince-as-hunter"
    """
    import re

    # Lower, replace non-alphanumeric with spaces, collapse whitespace
    cleaned = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    words = cleaned.split()[:max_words]
    slug = "-".join(words)
    if artist_surname:
        sur = re.sub(r"[^a-z0-9]+", "", artist_surname.lower())
        if sur:
            slug = f"{slug}-{sur}"
    # Guard against pathological empty slugs
    return slug or "untitled"
