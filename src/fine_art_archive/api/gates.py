"""Every place in the archive where progress is held up on a human.

One surface, so that "nothing is happening" can never again be indistinguishable
from "the exit is welded shut". Each gate reports two numbers in the same place:

  * ``blocking``  — how many items the gate is holding right now.
  * ``drainable`` — how many of those a person could clear today.

That pairing is the whole point. ``128 blocking`` reads as "be patient" for five
weeks; ``128 blocking, 0 drainable`` is instantly a deadlock. A gate that cannot
compute its drainable count returns ``None`` and says so — ``None`` is never
rendered as ``0``, because "we could not measure" and "we measured, it is empty"
are opposite findings and only one of them is good news.

None of these gates blocks anything Tim has to attend to on a schedule. Growth
does not wait on this surface, nothing here expires, and an unread list has no
consequence — the same property that makes grant G55 safe to hold. Acting on a
row is always optional; the surface exists so the *option* is visible.
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import REPO_ROOT, env_path

# The discovery frontier lives in the acquisition workspace, outside this repo.
# Configurable because the repo and the workspace are separate trees and CI has
# neither.
DEFAULT_FRONTIER = (
    Path.home()
    / "Library"
    / "CloudStorage"
    / "Dropbox"
    / "Pictures"
    / "Claude Project"
    / "discovery_frontier.json"
)
FRONTIER_JSON = env_path("FAA_FRONTIER_JSON", DEFAULT_FRONTIER)

# Artists a person has approved for acquisition despite not yet being
# represented in the archive. This file is the DRAIN for the new-artist gate:
# without it that gate has no exit that does not run through Tim's attention on
# someone else's schedule.
ARTIST_ALLOWLIST = env_path("FAA_ARTIST_ALLOWLIST", REPO_ROOT / "data" / "artist_allowlist.jsonl")

#: Sentinel for "this gate could not measure itself". Distinct from 0.
UNMEASURED = None


@dataclass
class Gate:
    """One place where progress waits on a person."""

    name: str
    label: str
    blocking: int
    #: How many of the blocked items a person could clear right now. ``None``
    #: means the count could not be computed — never conflate it with zero.
    drainable: int | None
    #: The named mechanism that clears this gate. "Time passes" is not one.
    clears_by: str
    #: True when leaving this gate untouched costs nothing at all.
    advisory: bool = True
    #: True when the gate drains on its own without anyone acting. Such a gate
    #: has ``drainable == 0`` by a person's reckoning and yet is NOT stuck, so
    #: it must not be reported as a deadlock — a surface that cries wolf on a
    #: healthy gate teaches you to ignore the one real alarm.
    auto_clears: bool = False
    note: str = ""
    #: What an item's ``id`` refers to, so a viewer never has to guess which
    #: image endpoint serves it. Guessing is how the unreviewed-acquisitions
    #: list came to request every one of its 103 pictures from the CANDIDATE
    #: proxy, which only answers to Wikidata Q-IDs -- 103 broken images on a
    #: screen whose entire purpose is looking at pictures.
    item_kind: str = "candidate"  # "candidate" (Wikidata Q-ID) | "held_work"
    items: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "blocking": self.blocking,
            "drainable": self.drainable,
            "drainable_measured": self.drainable is not UNMEASURED,
            "clears_by": self.clears_by,
            "advisory": self.advisory,
            "auto_clears": self.auto_clears,
            "item_kind": self.item_kind,
            "note": self.note,
            "deadlocked": (self.blocking > 0 and self.drainable == 0 and not self.auto_clears),
        }


def _read_json(path: Path) -> dict | None:
    """Return parsed JSON, or None if it cannot be read.

    None means "could not read" and is propagated as an unmeasured gate rather
    than being flattened into an empty result.
    """
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def decisions_sources() -> list[dict[str, Any]]:
    """Where the owner's decisions are being read from, and whether they exist.

    Both loaders below return an empty set for a file they cannot open, which
    is correct as a value and catastrophic as a report: "you have decided
    nothing" and "I could not find your decisions" then look identical, and the
    review surface silently re-presents everything already ruled on.

    That is not hypothetical and it is not old. On 2026-09-02 the app was
    launched so that `fine_art_archive` resolved to the ~/.faa-lib checkout
    instead of the companion repo. REPO_ROOT moved with it, both files
    vanished, and 129 artist decisions and 120 work decisions became invisible:
    the routed queue went from 16 items to 116, new-artist from 23 to 132, and
    the owner was asked again for feedback he had already given. Nothing in the
    app said so, because nothing asked whether the record could be read.

    So this reports the paths and their existence, and callers surface it. It
    deliberately does NOT guess at another location: a decisions file found by
    searching is how you end up writing to one copy and reading another.
    """
    return [
        {
            "name": "artist_allowlist",
            "path": str(ARTIST_ALLOWLIST),
            "exists": ARTIST_ALLOWLIST.exists(),
            "env_var": "FAA_ARTIST_ALLOWLIST",
            "records": _count_lines(ARTIST_ALLOWLIST),
        },
        {
            "name": "work_decisions",
            "path": str(WORK_DECISIONS),
            "exists": WORK_DECISIONS.exists(),
            "env_var": "FAA_WORK_DECISIONS",
            "records": _count_lines(WORK_DECISIONS),
        },
    ]


def _count_lines(path: Path) -> int | None:
    """Non-blank lines, or None when the file cannot be read.

    None is "not measured". It must never be rendered as 0.
    """
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return None


def _artist_decisions(path: Path | None = None) -> tuple[set[str], set[str]]:
    """Return approved and refused artist Q-IDs from one append-log pass."""
    p = path or ARTIST_ALLOWLIST
    approved: set[str] = set()
    refused: set[str] = set()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return approved, refused

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        qid = rec.get("artist_qid")
        decision = rec.get("decision")
        if not qid or not decision:
            continue
        qid = str(qid)
        if decision == "reject":
            approved.discard(qid)
            refused.add(qid)
        else:
            refused.discard(qid)
            approved.add(qid)
    return approved, refused


def load_allowlisted_artists(path: Path | None = None) -> set[str]:
    """Artist Q-IDs a person has approved for acquisition."""
    approved, _ = _artist_decisions(path)
    return approved


def load_refused_artists(path: Path | None = None) -> set[str]:
    """Artist Q-IDs explicitly refused. Decided — not awaiting anything.

    `load_allowlisted_artists` discards a refusal, which correctly keeps the
    artist out of the approved set but loses the fact that a decision was made
    at all. Without this the gate cannot tell "not yet considered" from
    "considered and declined".
    """
    _, refused = _artist_decisions(path)
    return refused


def append_allowlist(
    artist_qid: str,
    *,
    decision: str,
    artist_name: str = "",
    note: str = "",
    reviewer: str = "tim",
    ts: str,
    path: Path | None = None,
) -> None:
    """Record an approve/reject for one artist. Append-only."""
    p = path or ARTIST_ALLOWLIST
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": ts,
        "artist_qid": artist_qid,
        "artist_name": artist_name,
        "decision": decision,
        "note": note,
        "reviewer": reviewer,
    }
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _candidates(frontier: dict) -> list[dict]:
    raw = frontier.get("candidates")
    if isinstance(raw, dict):
        return [c for c in raw.values() if isinstance(c, dict)]
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict)]
    return []


def _gates_all_pass(cand: dict) -> bool:
    """True when every declared screening gate returned `pass`.

    An `unevaluated` gate is not a pass: "we did not check" must never read as
    "it cleared". A candidate with no gate verdicts at all is not passing.
    """
    gates = (cand.get("screen_scores") or {}).get("gates") or {}
    if not gates:
        return False
    return all(v == "pass" for v in gates.values())


def _integer_dimensions(value: Any) -> tuple[int, int] | None:
    """Return one JSON-safe pixel pair, rejecting floats, booleans, and malformed values."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if not all(
        isinstance(dimension, int) and not isinstance(dimension, bool) for dimension in value
    ):
        return None
    return value[0], value[1]


#: The three genuinely different situations behind a "deferral", which the old
#: single label ("deferred on image quality") described wrongly for half of
#: them. Ten of twenty were transfer failures on the BEST images in the pool --
#: Pastoral Concert at 356 MP, Castiglione at 301 MP -- and three were files
#: that never decoded, reported as "0px long edge" as though measured.
DEFER_UNDECODED = "undecoded"
DEFER_BELOW_FLOOR = "below_floor"
DEFER_TRANSFER = "transfer_failed"
DEFER_OTHER = "other"


def classify_deferral(reason: str | None) -> dict[str, Any]:
    """What actually happened, and the numbers a person needs to judge it.

    Returns the kind plus, where the reason states them, the pixels obtained
    and the pixels required — so the page can say "7 px short of the floor"
    instead of showing a truncated sentence.
    """
    text = reason or ""
    got = need = None
    match = re.search(r"(\d+)px long edge, need (\d+)px", text)
    if match:
        got, need = int(match.group(1)), int(match.group(2))

    if got == 0:
        kind = DEFER_UNDECODED
    elif match:
        kind = DEFER_BELOW_FLOOR
    elif "throughput" in text or "wall-clock" in text or "timed out" in text:
        kind = DEFER_TRANSFER
    else:
        kind = DEFER_OTHER

    out: dict[str, Any] = {"kind": kind, "reason": text, "got_px": got, "need_px": need}
    if kind == DEFER_BELOW_FLOOR and got and need:
        out["shortfall_px"] = need - got
        out["percent_of_floor"] = round(100 * got / need)
    return out


#: Subjects the screener flags for a person to look at. 92 of the 100 works in
#: the routed queue are there for one of these, and the card never said so --
#: it asked "keep or not?" about a picture without stating the question. An
#: unknown flag renders as its bare Q-ID rather than disappearing: a flag we
#: cannot name is still a flag, and silence would read as "nothing flagged".
DEPICTS_FLAG_LABELS = {
    "Q10791": "nudity",
    "Q22808839": "naked woman",
}


def _norm_title(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split())


def _held_by_artist_index() -> dict[str, list[dict[str, str]]] | None:
    """artist Q-ID -> the works the archive already holds by them.

    Returns None when the archive directory cannot be read. None is not an
    empty archive: the card must say the comparison could not be made rather
    than showing an empty space, which reads as "nothing similar is held" --
    the exact opposite of what an unreadable index means.
    """
    try:
        from fine_art_archive.api import store

        # glob silently converts an unreadable root into an empty result.  Probe
        # the root first so an unavailable comparison is never presented as an
        # empty archive.
        with os.scandir(store.WORKS):
            pass
        paths = sorted(glob.glob(str(store.WORKS / "*/meta.json")))
    except Exception:  # noqa: BLE001 - any failure here means "cannot compare"
        return None
    if not paths:
        # An archive which is readable but has no works is a valid empty index.
        # Only an exception above means the comparison itself was unavailable.
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    for path in paths:
        try:
            meta = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        artist = meta.get("artist") or {}
        qid = (artist.get("canonical") or {}).get("wikidata_q") or artist.get("wikidata_q")
        title = meta.get("title") or ""
        wid = meta.get("id") or Path(path).parent.name
        if not qid:
            continue
        out.setdefault(str(qid), []).append(
            {"id": str(wid), "title": str(title), "norm": _norm_title(str(title))}
        )
    return out


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def held_lookalikes(
    artist_qid: str, near_title: str, index: dict[str, list[dict[str, str]]] | None
) -> dict[str, Any]:
    """The works already held that a candidate's title resembles.

    "Looks like one you already hold" is unanswerable without the picture you
    already hold beside it. Naming the title and stopping there asks you to
    remember a painting.
    """
    if index is None:
        return {"lookup": "unavailable"}
    want = _norm_title(near_title)
    held = index.get(artist_qid or "", [])
    scored = sorted(
        ((_jaccard(want, h["norm"]), h) for h in held), key=lambda t: t[0], reverse=True
    )
    matches = [
        {"work_id": h["id"], "title": h["title"], "overlap": round(score, 2)}
        for score, h in scored
        if score >= 0.5
    ][:4]
    return {"lookup": "ok", "matches": matches}


def routing_flags(cand: dict) -> dict[str, Any]:
    """Why the screener sent this work to a person, in the screener's own terms.

    Every one of these is a question about THIS PICTURE -- is it the one you
    already hold, is its subject one you want, is its title ambiguous. None of
    them is a question about the painter, which is why presenting this queue as
    an artist decision could never answer it.
    """
    sc = cand.get("screen_scores") or {}
    out: dict[str, Any] = {}
    held = sc.get("held_titles_for_artist")
    if isinstance(held, int):
        out["held_by_artist"] = held
    variants = sc.get("candidate_variants")
    if isinstance(variants, int):
        out["variants"] = variants
    near = sc.get("fuzzy_against")
    if near:
        out["near_title"] = str(near)
        score = sc.get("fuzzy_jaccard")
        if isinstance(score, (int, float)) and math.isfinite(score):
            out["near_score"] = round(float(score), 3)
    alias = sc.get("ambiguous_short_alias")
    if alias:
        out["ambiguous_alias"] = str(alias)
    flagged = sc.get("depicts_flagged") or []
    if flagged:
        out["depicts"] = [
            {"qid": str(q), "label": DEPICTS_FLAG_LABELS.get(str(q))} for q in flagged
        ]
    return out


def _cand_row(cand: dict, why: str) -> dict[str, Any]:
    scores = cand.get("screen_scores") or {}
    dims = _integer_dimensions(scores.get("dimensions_px"))
    megapixels = round(dims[0] * dims[1] / 1e6, 1) if dims else None
    return {
        "id": cand.get("qid", ""),
        "title": cand.get("title", ""),
        "artist_qid": cand.get("artist_qid", ""),
        "artist_label": cand.get("artist_label", ""),
        "artist_description": cand.get("artist_description", ""),
        "holder_qid": cand.get("collection_qid", ""),
        "image_url": cand.get("image_url", ""),
        "sitelinks": cand.get("sitelinks"),
        "dimensions_px": scores.get("dimensions_px"),
        "why": why,
        "status": cand.get("status", ""),
        "last_defer_reason": cand.get("last_defer_reason", ""),
        # Evidence the decision actually needs, rather than an id and a name.
        "megapixels": megapixels,
        "long_edge_px": max(dims) if dims else None,
        "rights_status": scores.get("rights_status"),
        "generator": cand.get("generator", ""),
        "deferrals": cand.get("transfer_deferrals") or 0,
        "deferral": (
            classify_deferral(cand.get("last_defer_reason"))
            if cand.get("transfer_deferrals")
            else None
        ),
        # Not "no flags" -- the screener's actual reasons for asking.
        "routing_flags": routing_flags(cand),
        # A candidate that has never been probed has no size and no rights
        # determination. That is different from "small" or "unclear", and the
        # card must say which, or an absent number reads as a bad one.
        "probed": bool((cand.get("screen_scores") or {}).get("dimensions_px")),
    }


def frontier_gates(
    known_artist_qids: Iterable[str],
    *,
    frontier_path: Path | None = None,
    allowlist: set[str] | None = None,
    decided: dict[str, str] | None = None,
) -> list[Gate]:
    """Gates derived from the discovery frontier."""
    path = frontier_path or FRONTIER_JSON
    data = _read_json(path)
    if data is None:
        # Could not read the frontier. Report that as unmeasured on every
        # frontier gate rather than reporting three reassuring zeroes.
        return [
            Gate(
                name=name,
                label=label,
                blocking=0,
                drainable=UNMEASURED,
                clears_by=clears,
                note=f"frontier not readable at {path}",
            )
            for name, label, clears in (
                (
                    "rights_unclear",
                    "Candidates whose rights could not be determined",
                    "recording a creator death year or work date",
                ),
                (
                    "new_artist",
                    "Candidates by artists not yet in the archive",
                    "approving the artist on this surface",
                ),
                (
                    "routed_to_review",
                    "Candidates the screener routed to review",
                    "approving the artist, or a widened auto-accept rule",
                ),
                (
                    "deferred_transfer",
                    "Candidates deferred on image quality",
                    "a re-probe when the holder re-digitises",
                ),
            )
        ]

    known = set(known_artist_qids)
    allow = allowlist if allowlist is not None else load_allowlisted_artists()
    cands = _candidates(data)

    # A work you have already ruled on is DECIDED. It must leave every gate
    # that asks you to rule on it, or the surface asks the same question
    # forever and the answers look ignored — which is exactly what happened:
    # 20 deferrals were all decided and all 20 kept being presented, because
    # this list was built from the frontier alone and never read the record.
    #
    # Applied once, here, for every gate. Filtering per-gate is how three of
    # them came to disagree about whether feedback counts.
    ruled_on = set(decided if decided is not None else load_work_decisions())
    cands = [c for c in cands if c.get("qid") not in ruled_on]

    new_artist: list[dict] = []
    drainable_new = 0
    refused_artists = load_refused_artists()
    for c in cands:
        aq = c.get("artist_qid")
        if not aq or aq in known or aq in allow:
            continue
        # An artist you refused is DECIDED, not awaiting a decision. Leaving
        # them here kept Hitler, Zárraga and Guttero in a queue labelled
        # "waiting on you" after you had already said no to all three.
        if aq in refused_artists:
            continue
        # Only `screened` candidates. This gate must count exactly the
        # population that approving an artist would release -- the tick's
        # `auto_acceptable` considers nothing else, so counting a wider set
        # here would promise a drain this gate cannot deliver, and counting
        # `review` rows in both this gate and `routed_to_review` would double
        # count them into the roll-up.
        if c.get("status") != "screened":
            continue
        row = _cand_row(c, "artist not yet represented in the archive")
        # Drainable = would be acquirable the moment the artist is approved.
        row["would_pass_now"] = _gates_all_pass(c)
        if row["would_pass_now"]:
            drainable_new += 1
        new_artist.append(row)

    reviewed = [
        _cand_row(c, "screener routed this to review") for c in cands if c.get("status") == "review"
    ]
    deferred = [
        _cand_row(c, c.get("last_defer_reason") or "deferred")
        for c in cands
        if (c.get("transfer_deferrals") or 0) > 0 and c.get("status") != "acquired"
    ]
    # Sort the near-misses first: those are the quickest calls to make, and the
    # ones where a person's judgement most obviously beats a fixed threshold.
    deferred.sort(key=lambda r: -((r.get("deferral") or {}).get("percent_of_floor") or 0))
    kinds = [(r.get("deferral") or {}).get("kind") for r in deferred]
    n_floor = kinds.count(DEFER_BELOW_FLOOR)
    n_transfer = kinds.count(DEFER_TRANSFER)
    n_undecoded = kinds.count(DEFER_UNDECODED)
    n_other = kinds.count(DEFER_OTHER)

    # Candidates whose rights could not be established. Since 2026-08-29 an
    # in-copyright work may be acquired for private display, so `unclear` is no
    # longer "probably blocked on copyright" -- it is the one rights outcome
    # nobody has decided, and a person looking up one death date clears it.
    #
    # If NO candidate carries the field, the screener has not run since this
    # was added. That is unmeasured, not zero: reporting "0 unclear" from a
    # frontier that was never asked would be the exact failure this surface
    # exists to prevent.
    assessed = [c for c in cands if (c.get("screen_scores") or {}).get("rights_status")]
    unclear = [
        _cand_row(c, "rights could not be determined — no inception or death year")
        for c in assessed
        if (c["screen_scores"]["rights_status"] == "unclear")
        and c.get("status") not in {"acquired", "rejected"}
    ]
    rights_gate = Gate(
        name="rights_unclear",
        label="Candidates whose rights could not be determined",
        blocking=len(unclear),
        drainable=len(unclear) if assessed else UNMEASURED,
        clears_by="recording a death year, or taking it anyway",
        note=(
            ""
            if assessed
            else "no candidate carries a rights determination yet — "
            "the screener has not run since rights assessment was added"
        ),
        items=unclear,
    )

    return [
        rights_gate,
        Gate(
            name="new_artist",
            label="Candidates by artists you have not decided on yet",
            blocking=len(new_artist),
            drainable=drainable_new,
            clears_by="approving the artist on this surface",
            note=(
                "Auto-accept refuses any artist the archive does not already hold, "
                "so the archive can deepen but not broaden on its own. Approving an "
                "artist here is what lets their work through."
            ),
            items=new_artist,
        ),
        Gate(
            name="routed_to_review",
            label="Candidates the screener routed to review",
            blocking=len(reviewed),
            drainable=len(reviewed),
            # Was "approving the artist". It is not: every work here is kept or
            # refused on its own, and saying otherwise made the queue unreadable
            # -- you cannot tell what you are answering.
            clears_by="keeping or refusing each work, one at a time",
            items=reviewed,
        ),
        Gate(
            name="deferred_transfer",
            label=(
                f"Deferred: {n_floor} just under the size floor, "
                f"{n_transfer} failed to download, {n_undecoded} would not decode"
                + (f", {n_other} other" if n_other else "")
            ),
            blocking=len(deferred),
            # NOT auto-clearing, and the old label was wrong for half of these.
            # Ten of twenty were transfer failures on the largest images in the
            # pool, and the below-floor ones miss by as little as SEVEN PIXELS
            # (Portrait of Wally, 3053 of 3060). Both are decisions a person can
            # make in a second given the picture and the numbers, so calling it
            # "no human action needed" was hiding a real choice.
            drainable=n_floor + n_transfer + n_other,
            auto_clears=False,
            clears_by="accepting a near-miss anyway, or asking for the transfer again",
            note=(
                "Three different situations, so judge them differently: a work just "
                "under the floor is a size call; a transfer failure says nothing about "
                "the image (these are the BIGGEST files in the pool); a file that would "
                "not decode is a defect to look at, not a quality verdict."
            ),
            items=deferred,
        ),
    ]


_FRONTIER_MTIME_CACHE: dict[Path, tuple[float, dict]] = {}


def _frontier_data_cached(path: Path) -> dict | None:
    """Return parsed frontier JSON, re-reading only when the file changes."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _FRONTIER_MTIME_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = _read_json(path)
    if data is not None:
        _FRONTIER_MTIME_CACHE[path] = (mtime, data)
    return data


def candidate_image_url(qid: str, *, frontier_path: Path | None = None) -> str | None:
    """The discovery image URL a frontier candidate carries, or None.

    Exists so the image proxy can resolve a Q-ID to a URL the pipeline already
    chose, rather than fetching a URL supplied by the caller.
    """
    data = _frontier_data_cached(frontier_path or FRONTIER_JSON)
    if data is None:
        return None
    for cand in _candidates(data):
        if cand.get("qid") == qid:
            url = cand.get("image_url")
            return str(url) if url else None
    return None


# Per-WORK decisions. Approving an artist says "this painter belongs in the
# archive"; it does not say "every canvas they ever produced belongs". Tim
# approved 98 artists, which released 555 works — and asked, correctly, to keep
# the painter and drop particular pictures. Artist-level consent cannot express
# that, so work-level decisions live here alongside it.
#
# A `reject` is STICKY: it is the record that this work was looked at and
# refused, so nothing re-proposes it later. A `keep` is not required for
# acquisition — silence means "no objection" — it exists so a work can be
# marked as seen and deliberately wanted.
WORK_DECISIONS = env_path("FAA_WORK_DECISIONS", REPO_ROOT / "data" / "work_decisions.jsonl")


def load_work_decisions(path: Path | None = None) -> dict[str, str]:
    """work Q-ID -> "keep" | "reject" | "force". Last decision for a work wins.

    `force` is the deferral override: take this work even though it sits under
    the size floor or downloads too slowly. It exists because those thresholds
    are blunt where a person is not — Portrait of Wally was refused for being
    3053 px against a 3060 floor, and no fixed rule can know that seven pixels
    do not matter for that picture.

    Acquisition paths outside this module and api/main.py do not read work
    decisions; `force` is consumed exclusively in frontier_gates (to exclude
    the work from the deferred gate) and in the deferred-transfer acquisition
    tick (api/main.py), so its scope is contained.
    """
    p = path or WORK_DECISIONS
    out: dict[str, str] = {}
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        qid, decision = rec.get("work_qid"), rec.get("decision")
        if qid and decision in {"keep", "reject", "force"}:
            out[str(qid)] = decision
    return out


def append_work_decision(
    work_qid: str,
    *,
    decision: str,
    title: str = "",
    note: str = "",
    reviewer: str = "tim",
    ts: str,
    path: Path | None = None,
) -> None:
    """Record a keep/reject for one work. Append-only, like every other decision."""
    p = path or WORK_DECISIONS
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": ts,
        "work_qid": work_qid,
        "title": title,
        "decision": decision,
        "note": note,
        "reviewer": reviewer,
    }
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def works_awaiting_look(
    approved_artists: set[str],
    *,
    frontier_path: Path | None = None,
    decided: dict[str, str] | None = None,
    source: str = "approved",
) -> list[dict[str, Any]]:
    """Screened works by approved artists that nobody has looked at yet.

    These are the works an artist approval released. They are acquirable now,
    which is exactly why they are worth a glance: this is the last point at
    which a particular picture can be refused without refusing its painter.
    """
    data = _read_json(frontier_path or FRONTIER_JSON)
    if data is None:
        return []
    seen = decided if decided is not None else load_work_decisions()
    out: list[dict[str, Any]] = []
    for cand in _candidates(data):
        # `approved` = works an artist approval released.
        # `routed`   = works the screener sent to review. These were being
        #              presented as ARTISTS, which cannot answer a question
        #              asked about a picture.
        if source == "routed":
            if cand.get("status") != "review":
                continue
        elif source == "rights":
            # Since the owner's 2026-08-29 exception, "rights unclear" is a
            # call a person can actually make -- in-copyright works are
            # permitted for private display -- so this gate had a decision
            # behind it and no screen on which to make it.
            if (cand.get("screen_scores") or {}).get("rights_status") != "unclear":
                continue
            if cand.get("status") in {"acquired", "rejected"}:
                continue
        else:
            if cand.get("status") != "screened":
                continue
            if cand.get("artist_qid") not in approved_artists:
                continue
        qid = cand.get("qid")
        if not qid or qid in seen:
            continue
        row = _cand_row(
            cand,
            {
                "routed": "the screener routed this picture to you",
                "rights": "the screener could not determine this work's rights",
            }.get(source, "released by approving this artist"),
        )
        row["decision"] = None
        out.append(row)
    # Named artists first. Sorting on the raw label put every UNNAMED artist at
    # the head of the queue, so the first cards were the ones showing a bare
    # Q-ID — the weakest possible opening for a judgement about a painter.
    out.sort(
        key=lambda r: (
            0 if r.get("artist_label") else 1,
            str(r.get("artist_label") or r.get("artist_qid") or "~"),
            str(r.get("title") or ""),
        )
    )
    # Where the screener said "this looks like one you already hold", resolve
    # WHICH one, so the card can put the two pictures side by side. The index
    # is built once per request and only when some row needs it.
    if any((r.get("routing_flags") or {}).get("near_title") for r in out):
        index = _held_by_artist_index()
        for row in out:
            flags = row.get("routing_flags") or {}
            if flags.get("near_title"):
                flags["near_held"] = held_lookalikes(
                    str(row.get("artist_qid") or ""), str(flags["near_title"]), index
                )

    # Attach the artist's OTHER waiting works to each row. Judging one picture
    # by a painter you do not know is easier beside the rest of what is
    # offered, and it is the difference between "is this good" and "is this
    # the one I want of theirs".
    by_artist: dict[str, list[dict[str, Any]]] = {}
    for row in out:
        aqid = row.get("artist_qid")
        if aqid:
            by_artist.setdefault(aqid, []).append(row)
    for siblings in by_artist.values():
        for position, row in enumerate(siblings, start=1):
            row["artist_work_count"] = len(siblings)
            row["artist_work_index"] = position
    for row in out:
        if row.get("artist_qid"):
            continue
        # No artist Q-ID, so it is grouped with nothing. It is still one work:
        # "0 of 0" would be a lie about a picture that is on screen.
        row["artist_work_count"] = 1
        row["artist_work_index"] = 1
    # The browser derives the other cards from this response once. Sending
    # every sibling list on every row makes a large artist queue quadratic on
    # the wire, even though the data is identical for each card.
    return out
