"""Saved playlists, and serving them to a device over HTTP.

Two delivery paths, one selection
---------------------------------
The survey found exactly two ingest routes that work without a vendor cloud:
push a file onto an SD card, or let the device pull over the LAN. Both are fed
from the same saved playlist here, so a card and a feed can never disagree about
what "Dutch landscapes, rated 8+" means.

The pull side is shaped around what the real devices actually do, which is less
than an API suggests:

* **Frame Labs** frames pull from an image-server URL *you* set.
* **BLOOMIN8** has a documented schedule-pull mode: the device wakes on a cron,
  calls your `/eink_pull` for an image URL, displays it, sleeps again.
* **CREA** panels FTP-poll a directory.
* Several cheap panels can only fetch **one fixed URL** on a timer.

That last case is the binding constraint, and it is why `current` exists. A
device too dumb to track position still shows a rotating gallery if the same URL
returns a different image as time passes. Rotation is therefore computed from
the clock, not from server-side cursor state: it is idempotent, survives a
reboot at either end, and two devices pointed at the same feed stay in step
without talking to each other.

Playlists are stored resolved-at-serve-time, not frozen: a feed re-runs its
query on each request, so works that gain tags later appear automatically. That
is the point of saving the *spec* rather than the resulting list of work_ids.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Rotation intervals a device might poll on. Seconds.
INTERVALS: dict[str, int] = {
    "hourly": 3600,
    "6h": 6 * 3600,
    "12h": 12 * 3600,
    "daily": 86400,
    "weekly": 7 * 86400,
}


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return s or "playlist"


@dataclass
class SavedPlaylist:
    """A named selection plus how to render it for a particular panel."""

    id: str
    name: str
    spec: dict[str, Any]
    target: str = "gooddisplay-315-diy"
    dither: str = "floyd-steinberg"
    fit: str | None = None
    interval: str = "daily"
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def new(cls, name: str, spec: dict, **kw: Any) -> SavedPlaylist:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        # A short uuid suffix keeps two playlists called "Winter" distinct while
        # leaving the id readable in a device's config field, where a bare uuid
        # would be impossible to check by eye.
        pid = f"{slugify(name)}-{uuid.uuid4().hex[:6]}"
        return cls(id=pid, name=name, spec=spec, created_at=now, updated_at=now, **kw)

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat(timespec="seconds")

    def as_dict(self) -> dict:
        return asdict(self)


class PlaylistStore:
    """A tiny JSON-file store. One user, a handful of playlists."""

    def __init__(self, path: Path):
        self.path = path

    def _load_raw(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            # A corrupt store must not take the whole app down; an empty result
            # is recoverable, an exception on every page load is not.
            return {}
        return data.get("playlists", {}) if isinstance(data, dict) else {}

    def _write(self, raw: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.partial")
        tmp.write_text(json.dumps({"_schema": "faa-eink-playlists/1", "playlists": raw}, indent=2))
        tmp.replace(self.path)

    def list(self) -> list[SavedPlaylist]:
        playlists = []
        for value in self._load_raw().values():
            try:
                playlists.append(SavedPlaylist(**value))
            except TypeError:
                continue
        return sorted(playlists, key=lambda p: p.name.lower())

    def get(self, pid: str) -> SavedPlaylist | None:
        raw = self._load_raw().get(pid)
        if not raw:
            return None
        try:
            return SavedPlaylist(**raw)
        except TypeError:
            return None

    def save(self, pl: SavedPlaylist) -> SavedPlaylist:
        raw = self._load_raw()
        pl.touch()
        raw[pl.id] = pl.as_dict()
        self._write(raw)
        return pl

    def delete(self, pid: str) -> bool:
        raw = self._load_raw()
        if pid not in raw:
            return False
        del raw[pid]
        self._write(raw)
        return True


def rotation_index(
    n_items: int, interval: str, *, now: datetime | None = None, offset: int = 0
) -> int:
    """Which item a clock-driven feed should be showing.

    Deterministic from the wall clock so that a device with no memory, and two
    devices that never talk to each other, all agree. `offset` lets a second
    frame in the same room show a different work from the same playlist.
    """
    if n_items <= 0:
        return 0
    secs = INTERVALS.get(interval, INTERVALS["daily"])
    now = now or datetime.now(UTC)
    return (int(now.timestamp()) // secs + offset) % n_items


def item_etag(work_id: str, target_key: str, dither: str, mtime: float | int) -> str:
    """Stable identity for one rendered image.

    Includes the master's mtime so re-mastering a work invalidates the cached
    render, and the render settings so switching panel or dither does too —
    otherwise a device would keep showing a stale image that no longer matches
    the playlist it is pointed at.
    """
    h = hashlib.sha256(f"{work_id}|{target_key}|{dither}|{mtime}".encode()).hexdigest()
    return f'W/"{h[:24]}"'


def build_manifest(
    playlist: SavedPlaylist,
    items: list[dict],
    *,
    base_url: str = "",
    now: datetime | None = None,
) -> dict:
    """The document a pulling device reads to know what to fetch."""
    base = base_url.rstrip("/")
    n = len(items)
    idx = rotation_index(n, playlist.interval, now=now)
    return {
        "playlist_id": playlist.id,
        "name": playlist.name,
        "generated_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "target": playlist.target,
        "dither": playlist.dither,
        "interval": playlist.interval,
        "count": n,
        "current_index": idx,
        "current_url": f"{base}/feed/{playlist.id}/current" if n else None,
        # Resolved fresh on every request: a work that gains a matching tag
        # tomorrow joins this feed with no action from anyone.
        "resolved_live": True,
        "items": [
            {
                "index": i,
                "work_id": it["work_id"],
                "title": it.get("title") or "",
                "artist": it.get("artist") or "",
                "year": it.get("year"),
                "url": f"{base}/feed/{playlist.id}/image/{i}",
            }
            for i, it in enumerate(items)
        ],
    }
