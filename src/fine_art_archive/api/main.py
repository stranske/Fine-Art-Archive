"""FastAPI app — browse + rate the Fine Art Archive.

Rating writes go to `data/ratings_log.jsonl` (append-only). The JSONL
schema matches `preference_model_design.md`'s event-log spec, so the
Parquet rollup later can read these straight in.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import tempfile
import threading
import urllib.request
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import store
from .config import DEFAULT_ART_WORKS_ROOT, REPO_ROOT, env_path

UI_FILE = REPO_ROOT / "src" / "fine_art_archive" / "ui" / "index.html"
HTMX_VERSION = "1.9.10"
HTMX_FILE = REPO_ROOT / "src" / "fine_art_archive" / "ui" / "vendor" / "htmx.min.js"
VARIANT_UPGRADE_DECISIONS = REPO_ROOT / "data" / "variant_upgrade_decisions.jsonl"
VARIANT_UPGRADE_CSV = REPO_ROOT / "variant_upgrade_candidates.csv"

# Canonical archive root where promoted masters live: Art/works/<wid>/master.<ext>
ART_WORKS_ROOT = env_path("FAA_ART_WORKS_ROOT", DEFAULT_ART_WORKS_ROOT)
IMAGE_CACHE_DIR = env_path("FAA_IMAGE_CACHE_DIR", REPO_ROOT / "data" / "image_cache")
# DeepZoom tiles are proxied from the source pyramid and cached here on first
# view. Kept OFF the (Dropbox-synced) archive by default — hundreds of thousands
# of tiny tile files must not hit cloud-sync. Override with FAA_TILES_CACHE_DIR.
TILES_CACHE_DIR = env_path("FAA_TILES_CACHE_DIR", Path.home() / ".faa-tiles")

app = FastAPI(
    title="Fine Art Archive — Companion API",
    description="Browse + rate the canonical Fine Art Archive.",
    version="0.2.0",
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(_json_safe(exc.errors()))},
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _bad_work_id(exc: ValueError) -> HTTPException:
    return HTTPException(400, str(exc))


def _get_work_checked(work_id: str) -> dict | None:
    try:
        return store.get_work(work_id)
    except ValueError as exc:
        raise _bad_work_id(exc) from exc


def _sidecar_path_checked(work_id: str) -> Path:
    try:
        return store.sidecar_path(work_id)
    except ValueError as exc:
        raise _bad_work_id(exc) from exc


def _archive_work_dir_checked(work_id: str) -> Path:
    try:
        return store.contained_work_path(ART_WORKS_ROOT, work_id)
    except ValueError as exc:
        raise _bad_work_id(exc) from exc


def _contained_master_filename(work_dir: Path, filename: str) -> Path:
    work_root = work_dir.resolve(strict=False)
    candidate = (work_root / filename).resolve(strict=False)
    if not candidate.is_relative_to(work_root):
        raise HTTPException(400, "master filename escapes work directory")
    return candidate


def _manifest_placeholder_work(work_id: str) -> dict | None:
    row = store.get_manifest_row(work_id)
    if row is None:
        return None
    return {
        "work_id": work_id,
        "title": row.get("title", ""),
        "artist": {
            "name": row.get("artist_name", ""),
            "wikidata_q": row.get("artist_wikidata_q", ""),
        },
        "year": row.get("year", ""),
        "medium": row.get("medium", ""),
        "files": {"variants": []},
        "_sidecar_status": "missing",
        "_sidecar_message": "Metadata is not staged yet for this work.",
    }


# --------------------------------------------------------------------------
# Browse endpoints (unchanged)
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def root() -> FileResponse:
    if not UI_FILE.exists():
        raise HTTPException(404, "UI not found")
    # Tell the browser never to cache index.html so UI edits show up on a
    # plain reload (no Cmd+Shift+R needed). The JS/CSS are inline in the
    # file so there are no separate cached assets to worry about.
    return FileResponse(
        UI_FILE,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get(f"/ui/vendor/htmx-{HTMX_VERSION}.min.js")
def htmx_vendor() -> FileResponse:
    if not HTMX_FILE.exists():
        raise HTTPException(404, "htmx asset not found")
    return FileResponse(
        HTMX_FILE,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/healthz")
def healthz() -> dict:
    corrupt_line_count = store.ratings_corrupt_line_count()
    queues_invalid_count = _queue_invalid_count()
    return {
        "ok": corrupt_line_count == 0 and queues_invalid_count == 0,
        "manifest_loaded": len(store.load_manifest()),
        "ratings_count": store.count_ratings(),
        "ratings_corrupt_line_count": corrupt_line_count,
        "queues_invalid_count": queues_invalid_count,
    }


@app.get("/works")
def list_works(
    q: str | None = None,
    artist: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    return store.list_works(q=q, artist=artist, limit=limit, offset=offset)


@app.get("/works/{work_id}")
def get_work(work_id: str) -> dict:
    w = _get_work_checked(work_id)
    if w is None:
        placeholder = _manifest_placeholder_work(work_id)
        if placeholder is None:
            raise HTTPException(404, f"no sidecar for {work_id}")
        w = placeholder
    # Attach the latest rating for this work, if any
    latest = store.latest_rating(work_id)
    if latest is not None:
        w = {**w, "_latest_rating": latest}
    return w


@app.get("/artists")
def list_artists(limit: int = Query(100, ge=1, le=2000)) -> list[dict]:
    return store.list_artists(limit=limit)


@app.get("/dossiers")
def list_dossiers() -> dict:
    """work_ids that have a populated dossier — lets the library grid mark them."""
    ids = sorted(store.work_ids_with_dossier())
    return {"total": len(ids), "work_ids": ids}


# --------------------------------------------------------------------------
# Dossier page + research depth
# --------------------------------------------------------------------------
DOSSIER_UI_FILE = REPO_ROOT / "src" / "fine_art_archive" / "ui" / "dossier.html"
RESEARCH_REQUESTS = env_path(
    "FAA_RESEARCH_REQUESTS", REPO_ROOT / "data" / "research_requests.jsonl"
)
# A request is a standing hint, not an obligation: anything older than this is
# treated as expired so an un-actioned backlog cannot accumulate.
RESEARCH_REQUEST_TTL_DAYS = 30
# Section weights for the depth score — what a reader actually gets, not raw
# source count. A dossier heavy on provenance but empty on close-looking is
# shallow for our purposes however many footnotes it carries.
_DEPTH_SECTIONS = {"reading": 22, "stories": 22, "composition": 18, "context": 8, "provenance": 6}


@app.get("/works/{work_id}/dossier")
def dossier_page(work_id: str) -> FileResponse:
    """Standalone dossier page, linked from the work detail.

    Kept off the rating view deliberately: the dossier is long-form reading and
    competes with rating for attention when inlined.
    """
    _get_work_checked(work_id)  # 400 on a malformed id before we serve anything
    if not DOSSIER_UI_FILE.exists():
        raise HTTPException(404, "dossier UI not found")
    return FileResponse(
        DOSSIER_UI_FILE,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def _depth_report(dossier: dict | None) -> dict:
    """Score how well-developed a dossier is, and say what is missing.

    Exists so a viewer can judge whether commissioning deeper research looks
    promising *before* paying for it — an empty `reading` section plus a stack
    of unread promising leads is a much better bet than a dossier that has
    already mined everything available.
    """
    if not dossier:
        return {"score": 0, "n_sources": 0, "n_high_authority": 0,
                "n_promising_unread": 0, "kinds_covered": [], "gaps": ["no dossier yet"],
                "sections": {}, "last_developed_at": None, "design_version": None}
    refs = dossier.get("references") or []
    research = dossier.get("research") or {}
    pool = research.get("source_pool") or []
    kinds = sorted({str(r.get("kind")) for r in refs if r.get("kind")})
    high = sum(1 for r in refs if (r.get("authority_score") or 0) >= 8)
    promising = sum(1 for s in pool if str(s.get("status", "")).lower() in
                    {"promising", "paywalled", "unread"})

    score = 0.0
    sections, gaps = {}, []
    for name, weight in _DEPTH_SECTIONS.items():
        n = len(dossier.get(name) or [])
        sections[name] = n
        # Saturating: the first few items carry most of the value.
        score += weight * min(n, 5) / 5
        if n == 0:
            gaps.append(f"no {name}")
    score += 12 * min(len(refs), 8) / 8            # breadth of citation
    score += 12 * min(len(kinds), 5) / 5           # variety of source type
    if not high:
        gaps.append("no high-authority source")
    if len(kinds) <= 2:
        gaps.append("narrow source mix")
    return {"score": round(min(score, 100.0), 1), "n_sources": len(refs),
            "n_high_authority": high, "n_promising_unread": promising,
            "kinds_covered": kinds, "gaps": gaps, "sections": sections,
            "last_developed_at": research.get("last_developed_at"),
            "design_version": research.get("design_version")}


@app.get("/works/{work_id}/research")
def work_research(work_id: str) -> dict:
    """Depth report for a work. Deliberately does NOT return `source_pool`:
    the leads are the raw material for a deeper pass, not viewer-facing."""
    w = _get_work_checked(work_id)
    if w is None:
        raise HTTPException(404, f"no sidecar for {work_id}")
    report = _depth_report(w.get("dossier"))
    report["work_id"] = work_id
    report["requested"] = _open_research_request(work_id) is not None
    return report


def _open_research_request(work_id: str) -> dict | None:
    """Most recent non-expired request for this work, if any."""
    cutoff = datetime.now(UTC).timestamp() - RESEARCH_REQUEST_TTL_DAYS * 86400
    with _sidecar_file_lock(RESEARCH_REQUESTS):
        records = _active_research_requests(cutoff)
    return next((rec for rec in reversed(records) if rec.get("work_id") == work_id), None)


def _active_research_requests(cutoff: float) -> list[dict]:
    """Read valid, unexpired request records while the caller holds the lock."""
    if not RESEARCH_REQUESTS.exists():
        return []
    active: list[dict] = []
    try:
        for line in RESEARCH_REQUESTS.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(str(rec.get("ts"))).timestamp()
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if ts >= cutoff:
                active.append(rec)
    except OSError:
        return []
    return active


def _replace_research_requests(records: list[dict]) -> None:
    """Atomically compact the request log; caller must hold its file lock."""
    payload = "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in records)
    tmp = RESEARCH_REQUESTS.with_suffix(f"{RESEARCH_REQUESTS.suffix}.{os.getpid()}.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(RESEARCH_REQUESTS)


class ResearchRequestIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    focus: str | None = Field(default=None, max_length=100)


@app.post("/works/{work_id}/research_request")
def request_research(work_id: str, body: ResearchRequestIn) -> dict:
    """Record that a viewer wants this work researched further.

    Advisory and bounded. A maintainer runs the deepening pass with whatever
    model they have connected; expired requests are compacted on each write so
    an unattended queue cannot grow without limit.
    """
    w = _get_work_checked(work_id)
    if w is None:
        raise HTTPException(404, f"no sidecar for {work_id}")
    report = _depth_report(w.get("dossier"))
    rec = {"ts": datetime.now(UTC).isoformat(), "work_id": work_id,
           "title": w.get("title"), "note": body.note, "focus": body.focus,
           "depth_at_request": report["score"],
           "promising_unread": report["n_promising_unread"]}
    with _sidecar_file_lock(RESEARCH_REQUESTS):
        active = _active_research_requests(
            datetime.now(UTC).timestamp() - RESEARCH_REQUEST_TTL_DAYS * 86400
        )
        active.append(rec)
        _replace_research_requests(active)
    return {"ok": True, "expires_days": RESEARCH_REQUEST_TTL_DAYS, "request": rec}


# --------------------------------------------------------------------------
# Named queues — ordered lists of work_ids the user can load into the
# rating UI to walk a curated set (e.g. the subject-tagger v1 sample).
# Queues live as JSON files under data/queues/<name>.json with shape:
#   {"name": str, "description": str, "work_ids": [...]}
# --------------------------------------------------------------------------
QUEUES_DIR = REPO_ROOT / "data" / "queues"
_queue_invalid_count_cache: tuple[tuple[tuple[str, int, int], ...], int] | None = None


def _safe_queue_file_message(exc: OSError | UnicodeDecodeError) -> str:
    if isinstance(exc, UnicodeDecodeError):
        return str(exc)
    return exc.strerror or exc.__class__.__name__


def _queue_error_detail(
    path: Path, message: str, *, error: str = "invalid_queue_json"
) -> dict[str, object]:
    return {
        "error": error,
        "file": path.name,
        "message": message,
    }


def _queue_error(path: Path, message: str, *, error: str = "invalid_queue_json") -> HTTPException:
    return HTTPException(422, _queue_error_detail(path, message, error=error))


def _load_queue_file(path: Path) -> dict:
    try:
        queue = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        detail = _queue_error_detail(path, exc.msg)
        detail.update({"line": exc.lineno, "column": exc.colno})
        raise HTTPException(422, detail) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise _queue_error(path, _safe_queue_file_message(exc), error="invalid_queue_file") from exc
    if not isinstance(queue, dict):
        raise _queue_error(
            path, "queue file must contain a JSON object", error="invalid_queue_shape"
        )
    return queue


def _queue_files_with_signature() -> tuple[list[Path], tuple[tuple[str, int, int], ...]]:
    if not QUEUES_DIR.exists():
        return [], ()
    paths = sorted(QUEUES_DIR.glob("*.json"))
    signature: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat_result = path.stat()
        except OSError:
            signature.append((str(path), -1, -1))
            continue
        signature.append((str(path), stat_result.st_mtime_ns, stat_result.st_size))
    return paths, tuple(signature)


def _queue_invalid_count() -> int:
    global _queue_invalid_count_cache
    paths, signature = _queue_files_with_signature()
    if not signature:
        _queue_invalid_count_cache = (signature, 0)
        return 0
    if _queue_invalid_count_cache is not None and _queue_invalid_count_cache[0] == signature:
        return _queue_invalid_count_cache[1]
    invalid = 0
    for path in paths:
        try:
            _load_queue_file(path)
        except HTTPException:
            invalid += 1
    _queue_invalid_count_cache = (signature, invalid)
    return invalid


@app.get("/queues")
def list_queues() -> dict:
    """List named queues available for the rating UI."""
    out = []
    invalid_queues = []
    if QUEUES_DIR.exists():
        for p in sorted(QUEUES_DIR.glob("*.json")):
            try:
                q = _load_queue_file(p)
            except HTTPException as exc:
                invalid_queues.append(exc.detail)
                continue
            out.append(
                {
                    "name": q.get("name", p.stem),
                    "description": q.get("description", ""),
                    "n_works": len(q.get("work_ids", [])),
                }
            )
    return {
        "queues": out,
        "queues_invalid_count": len(invalid_queues),
        "invalid_queues": invalid_queues,
    }


@app.get("/queues/{name}")
def get_queue(name: str) -> dict:
    """Return a named queue and the works it contains, in order.

    The works list mirrors /works rows so the UI can render them with
    the same renderer used for the regular list (badges, etc.).
    """
    p = QUEUES_DIR / f"{name}.json"
    if not p.exists():
        raise HTTPException(404, f"no queue named {name!r}")
    q = _load_queue_file(p)
    wids_ordered = q.get("work_ids", [])
    # Fetch each work via the store. Preserve queue order.
    works_out = []
    for wid in wids_ordered:
        w_full = store.get_work(wid)
        if w_full is None:
            continue
        # Look up the inventory row for badge data (n_ratings, last quality/fit)
        # by fetching one matching work via list_works' search index. Simpler:
        # build a minimal row from the sidecar.
        latest = store.latest_rating(wid)
        works_out.append(
            {
                "work_id": wid,
                "title": w_full.get("title", ""),
                "artist_name": (w_full.get("artist") or {}).get("name", ""),
                "artist_wikidata_q": (w_full.get("artist") or {}).get("wikidata_q", ""),
                "year": w_full.get("year", ""),
                "n_variants": len((w_full.get("files") or {}).get("variants") or []),
                "_last_rating": (latest or {}).get("rating"),
                "_last_quality": (latest or {}).get("quality"),
                "_last_fit": (latest or {}).get("fit"),
                "_n_ratings": store.count_ratings_for(wid),
            }
        )
    return {
        "name": q.get("name", name),
        "description": q.get("description", ""),
        "total": len(works_out),
        "works": works_out,
    }


# --------------------------------------------------------------------------
# Subject-tag reviewer actions — confirm / reject / add / freetext_review.
# Mutates the sidecar's subject.content_tags (idempotent) AND appends an
# audit event to data/subject_tag_events.jsonl so we can reconstruct the
# review history later.
# --------------------------------------------------------------------------
SUBJECT_TAG_EVENTS = REPO_ROOT / "data" / "subject_tag_events.jsonl"


class SubjectActionIn(BaseModel):
    action: str  # confirm | reject | add | reset | freetext_review
    tag: str = ""
    text: str = ""
    reviewer: str = "tim"


@contextmanager
def _sidecar_file_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            with suppress(NameError, OSError):
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_sidecar_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(encoded)
        if path.exists():
            tmp_path.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _append_subject_tag_event(event: dict) -> None:
    SUBJECT_TAG_EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with open(SUBJECT_TAG_EVENTS, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


@app.post("/works/{work_id}/subject_action")
def subject_action(work_id: str, body: SubjectActionIn) -> dict:
    if body.action not in {"confirm", "reject", "add", "reset", "freetext_review"}:
        raise HTTPException(400, f"unknown action: {body.action!r}")
    tag_action = body.action in {"confirm", "reject", "add", "reset"}
    if tag_action and (not body.tag or ":" not in body.tag):
        raise HTTPException(400, "tag required (format 'group:id')")
    sc_path = _sidecar_path_checked(work_id)
    if not sc_path.exists():
        raise HTTPException(404, f"no sidecar for {work_id}")
    event = {
        "ts": _now(),
        "work_id": work_id,
        "action": body.action,
        "tag": body.tag or None,
        "text": body.text or None,
        "reviewer": body.reviewer,
    }

    with _sidecar_file_lock(sc_path):
        original_sc = json.loads(sc_path.read_text())
        sc = json.loads(json.dumps(original_sc))
        if body.action == "freetext_review":
            subj = sc.setdefault("subject", {})
            notes = subj.setdefault("reviewer_notes", [])
            notes.append({"ts": _now(), "reviewer": body.reviewer, "text": body.text})
            _write_sidecar_atomic(sc_path, sc)
        else:
            subj = sc.setdefault(
                "subject",
                {
                    "content_tags": [],
                    "genre": "unknown",
                    "tag_method_version": "reviewer",
                    "last_tagged_at": _now(),
                },
            )
            tags = subj.setdefault("content_tags", [])
            idx = next((i for i, t in enumerate(tags) if t.get("id") == body.tag), None)
            now_ts = _now()
            if body.action == "confirm":
                if idx is None:
                    tags.append(
                        {
                            "id": body.tag,
                            "state": "confirmed",
                            "source": "reviewer",
                            "reviewer": body.reviewer,
                            "ts": now_ts,
                        }
                    )
                else:
                    tags[idx]["state"] = "confirmed"
                    tags[idx]["reviewer"] = body.reviewer
                    tags[idx]["ts"] = now_ts
            elif body.action == "reject":
                if idx is None:
                    tags.append(
                        {
                            "id": body.tag,
                            "state": "rejected",
                            "source": "reviewer",
                            "reviewer": body.reviewer,
                            "ts": now_ts,
                        }
                    )
                else:
                    tags[idx]["state"] = "rejected"
                    tags[idx]["reviewer"] = body.reviewer
                    tags[idx]["ts"] = now_ts
            elif body.action == "add":
                if idx is None:
                    tags.append(
                        {
                            "id": body.tag,
                            "state": "added",
                            "source": "reviewer",
                            "reviewer": body.reviewer,
                            "ts": now_ts,
                        }
                    )
                else:
                    tags[idx]["state"] = "added"
                    tags[idx]["reviewer"] = body.reviewer
                    tags[idx]["ts"] = now_ts
            elif body.action == "reset" and idx is not None:
                tags[idx]["state"] = "proposed"
                tags[idx].pop("reviewer", None)
            subj["needs_review"] = any(t.get("state") == "proposed" for t in tags)
            _write_sidecar_atomic(sc_path, sc)
        try:
            _append_subject_tag_event(event)
        except Exception:
            _write_sidecar_atomic(sc_path, original_sc)
            raise

    return {"ok": True, "event": event}


# --------------------------------------------------------------------------
# Image serving — masters can be 100+ MB so we always go through a resizer
# and cache. /works/{wid}/image?max=N returns a JPEG with longest side <= N.
# /works/{wid}/full returns the original master untouched (for download).
# --------------------------------------------------------------------------
def _master_path(work_id: str) -> Path | None:
    """Find the master file for a work_id. Tries Art/works/<wid>/master.*
    first (canonical post-Phase-3 location), then the sidecar's filename
    field as a fallback."""
    work_dir = _archive_work_dir_checked(work_id)
    if work_dir.is_dir():
        for f in work_dir.iterdir():
            if f.is_file() and f.name.startswith("master."):
                return _contained_master_filename(work_dir, f.name)
    # Fallback: read filename from sidecar (handles staging-only works)
    sc = _get_work_checked(work_id)
    if sc:
        fname = (sc.get("files") or {}).get("master", {}).get("filename")
        if fname:
            p = _contained_master_filename(work_dir, fname)
            if p.is_file():
                return p
    return None


def _serve_resized(src: Path, cache_stem: str, max: int) -> FileResponse:
    """Return a cached, resized JPEG of ``src`` (longest side ``max`` px)."""
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    mtime = int(src.stat().st_mtime)  # mtime in key so a re-promote invalidates
    cache_p = IMAGE_CACHE_DIR / f"{cache_stem}_{max}_{mtime}.jpg"
    if not cache_p.exists():
        try:
            from PIL import Image
        except ImportError:
            raise HTTPException(500, "Pillow not installed") from None
        Image.MAX_IMAGE_PIXELS = None  # gigapixel Bruegel scans
        try:
            with Image.open(src) as im:
                im.thumbnail((max, max), Image.Resampling.LANCZOS)
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")  # type: ignore[assignment]
                im.save(cache_p, "JPEG", quality=85, optimize=True)
        except Exception as e:
            raise HTTPException(500, f"resize failed: {e}") from e
    return FileResponse(
        cache_p, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"}
    )


@app.get("/works/{work_id}/image")
def work_image(
    work_id: str, max: int = Query(1600, ge=64, le=12288, description="Longest side in pixels")
):
    """Serve a resized JPEG of the master. Cached on disk."""
    master = _master_path(work_id)
    if master is None:
        raise HTTPException(404, f"no master image for {work_id}")
    return _serve_resized(master, work_id, max)


@app.get("/works/{work_id}/modality/{modality}/image")
def modality_image(
    work_id: str, modality: str,
    max: int = Query(1600, ge=64, le=12288, description="Longest side in pixels"),
):
    """Serve a resized JPEG of an imaging modality (VIS/IRR/XR/RS/UV). Cached."""
    w = _get_work_checked(work_id)
    if w is None:
        raise HTTPException(404, f"no sidecar for {work_id}")
    entry = next(
        (m for m in (w.get("modalities") or [])
         if str(m.get("modality", "")).lower() == modality.lower()),
        None,
    )
    if entry is None or not entry.get("filename"):
        raise HTTPException(404, f"no {modality} modality for {work_id}")
    work_dir = _archive_work_dir_checked(work_id)
    src = _contained_master_filename(work_dir, str(entry["filename"]))
    if not src.is_file():
        raise HTTPException(404, f"{modality} file missing for {work_id}")
    return _serve_resized(src, f"{work_id}_mod_{modality.lower()}", max)


# --- DeepZoom gigapixel viewer -------------------------------------------
# The source tile pyramids (insidebruegel.net) are proxied through the app and
# cached locally on first view, so the browser can pan/zoom to full resolution
# (OpenSeadragon) without ever downloading a gigapixel flat file. Only the tiles
# a viewer actually looks at are fetched — polite to the source, and the cache
# becomes a durable local copy of what's been seen.
_DZ_TILE_HOST = "khmdata01.universumdigitalis.com"  # SSRF allowlist: the source
_FID_RE = re.compile(r"^[A-Za-z0-9_]+$")
_TILE_RE = re.compile(r"^(\d{1,4})_(\d{1,4})\.jpe?g$")


@app.get("/works/{work_id}/deepzoom")
def deepzoom_manifest(work_id: str) -> dict:
    """Layer descriptors (id, label, full pixel size) for the zoom viewer."""
    w = _get_work_checked(work_id)
    if w is None:
        raise HTTPException(404, f"no sidecar for {work_id}")
    dz = w.get("deepzoom") or {}
    layers = [
        {"layer": e.get("layer"), "label": e.get("label"),
         "width": (e.get("dimensions_px") or [0, 0])[0],
         "height": (e.get("dimensions_px") or [0, 0])[1],
         "source": e.get("source"), "license": e.get("license")}
        for e in (dz.get("layers") or [])
        if e.get("dimensions_px") and e.get("fid")
    ]
    return {"work_id": work_id, "tile_size": dz.get("tile_size") or 256,
            "layers": layers}


def _dz_layer_entry(work_id: str, layer: str) -> tuple[dict, dict]:
    w = _get_work_checked(work_id)
    if w is None:
        raise HTTPException(404, f"no sidecar for {work_id}")
    dz = w.get("deepzoom") or {}
    entry = next((e for e in (dz.get("layers") or [])
                  if str(e.get("layer", "")).lower() == layer.lower()), None)
    if entry is None or not entry.get("fid"):
        raise HTTPException(404, f"no {layer} deepzoom layer for {work_id}")
    return dz, entry


@app.get("/works/{work_id}/dz/{layer}/{level}/{tile}")
def deepzoom_tile(work_id: str, layer: str, level: int, tile: str) -> FileResponse:
    """Serve one DeepZoom tile, proxying + caching from the source pyramid."""
    dz, entry = _dz_layer_entry(work_id, layer)
    fid = str(entry["fid"])
    tile_base = str(dz.get("tile_base") or "")
    m = _TILE_RE.match(tile)
    if not m or not _FID_RE.match(fid) or not (0 <= level <= 24):
        raise HTTPException(404, "bad tile request")
    col, row = m.group(1), m.group(2)
    if _DZ_TILE_HOST not in tile_base:  # SSRF guard: only the known source host
        raise HTTPException(502, "tile source not allowed")

    cache_p = TILES_CACHE_DIR / fid / str(level) / f"{col}_{row}.jpg"
    if not cache_p.exists():
        url = f"{tile_base.rstrip('/')}/{fid}/{level}/{col}_{row}.jpg"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Fine-Art-Archive/0.1 (private-archive)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (host-pinned)
                data = r.read()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"tile fetch failed: {type(exc).__name__}") from exc
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_p.with_suffix(f".tmp{os.getpid()}")
        tmp.write_bytes(data)
        tmp.replace(cache_p)
    return FileResponse(cache_p, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/works/{work_id}/full")
def work_full(work_id: str):
    """Serve the original master file as a download. Gigapixel masters (up to
    ~1.2 GP for the Bruegel scans) can't be rendered inline by any browser, so
    this is a download of the true original; use /works/{id}/image?max=8192 for
    an in-browser high-resolution view."""
    master = _master_path(work_id)
    if master is None:
        raise HTTPException(404, f"no master image for {work_id}")
    return FileResponse(
        master,
        filename=f"{work_id}{master.suffix}",
        headers={"Content-Disposition": f'attachment; filename="{work_id}{master.suffix}"'},
    )


# --------------------------------------------------------------------------
# Rating endpoints
# --------------------------------------------------------------------------
RATING_SCALE = {-2, -1, 0, 1, 2}

# Rating-reason taxonomy. Groups of toggleable chips that the UI renders.
# Single source of truth — UI fetches via /rating_taxonomy and renders
# dynamically. Add a chip here and the next page refresh shows it.
#
# Each chip selected by the user is stored as "group:chip" in the event
# log so the model can treat each group as a separate feature axis without
# name collisions.
RATING_TAXONOMY: list[dict] = [
    {
        "key": "image",
        "label": "Image quality",
        "help": "About the file itself (not the artwork)",
        "exclusive": False,
        "chips": [
            {"id": "low-res", "label": "Low resolution"},
            {"id": "color-cast", "label": "Color cast"},
            {"id": "scan-artifacts", "label": "Scan artifacts"},
            {"id": "crop-issue", "label": "Crop issue"},
            {"id": "watermark", "label": "Has watermark"},
            {"id": "looks-clean", "label": "Looks clean"},
        ],
    },
    {
        "key": "affect",
        "label": "Affect / mood",
        "help": "Pick all that apply — overlap is good signal",
        "exclusive": False,
        "has_freetext": True,
        "freetext_placeholder": "Other moods (free text — comma-separated is fine)",
        "chips": [
            {"id": "contemplative", "label": "Contemplative"},
            {"id": "joyful", "label": "Joyful"},
            {"id": "somber", "label": "Somber"},
            {"id": "melancholy", "label": "Melancholy"},
            {"id": "dramatic", "label": "Dramatic"},
            {"id": "peaceful", "label": "Peaceful"},
            {"id": "energetic", "label": "Energetic"},
            {"id": "kinetic", "label": "Kinetic"},
            {"id": "intimate", "label": "Intimate"},
            {"id": "mysterious", "label": "Mysterious"},
            {"id": "foreboding", "label": "Foreboding"},
            {"id": "surreal", "label": "Surreal"},
            {"id": "transcendent", "label": "Transcendent"},
            {"id": "monumental", "label": "Monumental"},
            {"id": "nostalgic", "label": "Nostalgic"},
            {"id": "austere", "label": "Austere"},
            {"id": "ornate", "label": "Ornate"},
            {"id": "whimsical", "label": "Whimsical"},
        ],
    },
    {
        "key": "familiarity",
        "label": "Familiarity",
        "help": "How well I already know this",
        "exclusive": True,
        "chips": [
            {"id": "iconic", "label": "Iconic"},
            {"id": "well-known", "label": "Well-known"},
            {"id": "under-known", "label": "Under-known"},
            {"id": "new-to-me", "label": "New to me"},
            {"id": "too-familiar", "label": "Too familiar"},
        ],
    },
    # NOTE: surface-fit chips removed from rate-time UI per Tim's feedback —
    # raters typically don't know aspect / contrast fit for a specific surface
    # when rating. This belongs to the automated display-fit pipeline (future
    # phase: aspect detection, auto-crop, contrast eval, per-surface scoring).
    {
        "key": "direction",
        "label": "What to do next",
        "help": "Signals to the recommender",
        "exclusive": False,
        "chips": [
            {"id": "more-by-artist", "label": "More by this artist"},
            {"id": "less-by-artist", "label": "Less by this artist"},
            {"id": "more-this-mood", "label": "More like this mood"},
            {"id": "learn-more", "label": "I'd like to learn more"},
            {"id": "skip-for-now", "label": "Skip in rotation"},
        ],
    },
    {
        "key": "data",
        "label": "Data concern",
        "help": "Routes to a fix queue, not the preference model",
        "exclusive": False,
        "chips": [
            {"id": "wrong-artist", "label": "Wrong artist"},
            {"id": "wrong-title", "label": "Wrong title"},
            {"id": "wrong-date", "label": "Wrong date"},
            {"id": "prefer-different-file", "label": "Want different file"},
        ],
    },
]

_VALID_CHIP_IDS = {f"{g['key']}:{c['id']}" for g in RATING_TAXONOMY for c in g["chips"]}

# Kept for backwards compatibility with older single-select reason_codes.
LEGACY_REASON_CODES = {
    "",
    "poor_image_quality",
    "wrong_mood",
    "too_familiar",
    "not_for_this_surface",
    "love_it",
    "discover_more_like_this",
    "fits_e_ink",
    "fits_frame_tv",
}

SURFACES = {
    "companion-app",
    "eink-tela-285",
    "eink-inky-13",
    "frame-tv-65",
    "frame-tv-55",
    "ipad",
    "sd-card-batch",
    "review",
}


class RatingIn(BaseModel):
    """Single rating event.

    Per DECISIONS.md D004, default scheme is two-axis: subject quality +
    fit-for-me, each 1-5. Both are optional so a rater can record one axis
    without the other. The single-axis `rating` field (-2..+2) is kept for
    backwards compatibility with the brief unified-scale experiment; new
    UI submissions should send quality + fit instead.
    """

    # NOTE: per-axis range is 1-10 today (two-axis-10 scheme). Events log the
    # `scheme` field so older two-axis-5 events stay readable and a future
    # per-rater precision picker can let one rater use 5 while another uses 10.
    # Validation here is intentionally permissive (1-10) — the UI enforces
    # whatever precision the active scheme says.
    quality: int | None = Field(
        default=None,
        ge=1,
        le=10,
        strict=True,
        description="1-N (N from active scheme), 'how good this is as art'",
    )
    fit: int | None = Field(
        default=None,
        ge=1,
        le=10,
        strict=True,
        description="1-N (N from active scheme), 'want to see this in rotation'",
    )
    rating: int | None = Field(
        default=None,
        description="DEPRECATED single-axis -2..+2 (use quality + fit instead)",
    )
    rater: str = Field(default="tim")
    scheme: str = Field(
        default="two-axis-10",
        description="Records the precision in use (two-axis-5, two-axis-10, etc.) so the model can normalize across schemes",
    )
    surface: str = Field(default="companion-app")
    reason_code: str = Field(default="", description="DEPRECATED — use selected_reasons")
    selected_reasons: list[str] = Field(
        default_factory=list,
        description='Toggled chip ids, format "group:chip" (e.g. "affect:somber")',
    )
    dwell_seconds: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
        description="Seconds on the work before rating (signal, not ground truth)",
    )
    notes: str = Field(
        default="", max_length=1000, description="General 'what strikes you' free-text"
    )
    freetext_by_group: dict[str, str] = Field(
        default_factory=dict,
        description='Per-chip-group free-text (e.g. {"affect": "ironic, sublime"}) for moods/etc. not in the chip set',
    )


@app.get("/rating_taxonomy")
def rating_taxonomy() -> dict:
    """Chip groups the UI uses to render the rating panel.
    Single source of truth — edit RATING_TAXONOMY in api/main.py."""
    return {"groups": RATING_TAXONOMY}


@app.post("/works/{work_id}/rate")
def rate_work(work_id: str, body: RatingIn) -> dict:
    # At least one of {quality, fit, rating} must be provided.
    if body.quality is None and body.fit is None and body.rating is None:
        raise HTTPException(400, "must provide quality, fit, or rating")
    if body.rating is not None and body.rating not in RATING_SCALE:
        raise HTTPException(400, f"rating must be in {sorted(RATING_SCALE)}")
    if body.surface not in SURFACES:
        raise HTTPException(400, f"surface must be in {sorted(SURFACES)}")
    if body.reason_code and body.reason_code not in LEGACY_REASON_CODES:
        raise HTTPException(400, f"reason_code must be in {sorted(LEGACY_REASON_CODES)}")
    bad_chips = [r for r in body.selected_reasons if r not in _VALID_CHIP_IDS]
    if bad_chips:
        raise HTTPException(400, f"unknown chip ids: {bad_chips}")

    # Verify the work exists
    if _get_work_checked(work_id) is None:
        raise HTTPException(404, f"no sidecar for {work_id}")

    event = {
        "work_id": work_id,
        "rater": body.rater,
        "scheme": body.scheme,
        "surface": body.surface,
        "ts": _now(),
        "event_kind": "rating",
        "quality": body.quality,  # 1-N from scheme, or None
        "fit": body.fit,  # 1-N from scheme, or None
        "rating": body.rating,  # legacy single-axis -2..+2 or None
        "dwell_seconds": body.dwell_seconds,
        "reason_code": body.reason_code or None,  # legacy
        "selected_reasons": body.selected_reasons or [],
        "freetext_by_group": body.freetext_by_group or {},
        "notes": body.notes or None,
    }
    store.append_rating(event)
    return {"ok": True, "event": event, "total_ratings_for_work": store.count_ratings_for(work_id)}


# --------------------------------------------------------------------------
# Debug telemetry — used by the UI to report client-side state to the server
# without needing a working browser-side debugger. Append-only, gitignored.
# --------------------------------------------------------------------------
DEBUG_LOG = REPO_ROOT / "automation_logs" / "ui_debug.log"
DEBUG_LOG_MAX_BYTES = 256 * 1024
DEBUG_LOG_MAX_EVENT_BYTES = 16 * 1024
DEBUG_LOG_MAX_REQUEST_BYTES = 24 * 1024
_debug_log_lock = threading.Lock()


class DebugIn(BaseModel):
    where: str
    info: dict = Field(default_factory=dict)


async def _read_capped_debug_log_body(request: Request) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > DEBUG_LOG_MAX_REQUEST_BYTES:
            raise HTTPException(
                413,
                (
                    "debug log request exceeds size limit "
                    f"({total_bytes} bytes > {DEBUG_LOG_MAX_REQUEST_BYTES} bytes)"
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_debug_log_body(raw_body: bytes) -> DebugIn:
    try:
        payload = json.loads(raw_body)
        if hasattr(DebugIn, "model_validate"):
            return DebugIn.model_validate(payload)
        return DebugIn.parse_obj(payload)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        raise HTTPException(422, "invalid debug log payload") from exc


@app.post("/debug/log")
async def debug_log(request: Request) -> dict:
    body = _parse_debug_log_body(await _read_capped_debug_log_body(request))
    DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    event = {"ts": _now(), "where": body.where, **body.info}
    line = json.dumps(event, ensure_ascii=False)
    line_bytes = len((line + "\n").encode("utf-8"))
    if line_bytes > DEBUG_LOG_MAX_EVENT_BYTES:
        raise HTTPException(
            413,
            f"debug log event exceeds size limit ({line_bytes} bytes > {DEBUG_LOG_MAX_EVENT_BYTES} bytes)",
        )
    with _debug_log_lock:
        if DEBUG_LOG.exists() and DEBUG_LOG.stat().st_size + line_bytes > DEBUG_LOG_MAX_BYTES:
            rotated = DEBUG_LOG.with_suffix(".log.1")
            if rotated.exists():
                rotated.unlink()
            DEBUG_LOG.replace(rotated)
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return {"ok": True}


@app.get("/works/{work_id}/ratings")
def work_ratings(work_id: str) -> dict:
    try:
        store.validate_work_id(work_id)
    except ValueError as exc:
        raise _bad_work_id(exc) from exc
    return {"work_id": work_id, "ratings": store.list_ratings_for(work_id)}


@app.api_route("/works/{work_path:path}", methods=["GET", "POST"])
def reject_invalid_nested_work_path(work_path: str) -> None:
    work_id = work_path.split("/", 1)[0]
    try:
        store.validate_work_id(work_id)
    except ValueError as exc:
        raise _bad_work_id(exc) from exc
    raise HTTPException(404, f"no route for work path {work_path}")


@app.get("/ratings/recent")
def recent_ratings(limit: int = Query(20, ge=1, le=200)) -> dict:
    return {"ratings": store.recent_ratings(limit=limit)}


@app.get("/ratings/summary")
def ratings_summary() -> dict:
    return store.ratings_summary()


# --------------------------------------------------------------------------
# Variant upgrade review (#95) — surface candidates Tim can accept/reject;
# actual master swap is gated behind a per-decision grant in permissions.md.
# --------------------------------------------------------------------------
import csv as _csv  # noqa: E402  -- kept beside its only use (variant-upgrade endpoint)


@app.get("/variant_upgrades")
def variant_upgrades() -> dict:
    if not VARIANT_UPGRADE_CSV.exists():
        return {"candidates": [], "decisions": []}
    with open(VARIANT_UPGRADE_CSV, encoding="utf-8", newline="") as _f:
        candidates = list(_csv.DictReader(_f))
    # Attach prior decisions
    decisions: dict[str, dict] = {}
    if VARIANT_UPGRADE_DECISIONS.exists():
        for line in VARIANT_UPGRADE_DECISIONS.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                decisions[d.get("existing_wid")] = d
            except json.JSONDecodeError:
                continue
    for c in candidates:
        d = decisions.get(c.get("existing_wid"))  # type: ignore[arg-type]
        c["decision"] = d.get("decision") if d else None
        c["decision_ts"] = d.get("ts") if d else None
    return {"candidates": candidates}


def _variant_upgrade_fallback_work(existing_wid: str) -> dict | None:
    if store.get_manifest_row(existing_wid) is not None:
        return _manifest_placeholder_work(existing_wid)
    return store.get_work(existing_wid)


def _known_variant_upgrade_work_id(existing_wid: str) -> bool:
    if VARIANT_UPGRADE_CSV.exists():
        with open(VARIANT_UPGRADE_CSV, encoding="utf-8", newline="") as _f:
            for candidate in _csv.DictReader(_f):
                if candidate.get("existing_wid") == existing_wid:
                    return True
    try:
        return _variant_upgrade_fallback_work(existing_wid) is not None
    except ValueError as exc:
        raise _bad_work_id(exc) from exc


class UpgradeDecisionIn(BaseModel):
    decision: str = Field(..., description="accept | reject | defer")
    note: str = Field(default="", max_length=500)


@app.post("/variant_upgrades/{existing_wid}/decision")
def variant_upgrade_decision(existing_wid: str, body: UpgradeDecisionIn) -> dict:
    if body.decision not in {"accept", "reject", "defer"}:
        raise HTTPException(400, "decision must be accept/reject/defer")
    if not _known_variant_upgrade_work_id(existing_wid):
        raise HTTPException(404, f"unknown variant upgrade work: {existing_wid}")
    event = {
        "existing_wid": existing_wid,
        "decision": body.decision,
        "note": body.note or None,
        "ts": _now(),
    }
    VARIANT_UPGRADE_DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with open(VARIANT_UPGRADE_DECISIONS, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "event": event,
        "next_steps": (
            "Decision logged. Promotion is gated — to actually swap the "
            "current master with the candidate, add a per-decision grant "
            "in permissions.md and run scripts/promote_variant_upgrade.py."
            if body.decision == "accept"
            else "Decision logged; no file changes."
        ),
    }
