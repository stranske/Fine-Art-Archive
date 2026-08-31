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

import json
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


def load_allowlisted_artists(path: Path | None = None) -> set[str]:
    """Artist Q-IDs a person has approved for acquisition."""
    p = path or ARTIST_ALLOWLIST
    out: set[str] = set()
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
        qid = rec.get("artist_qid")
        if not qid:
            continue
        if rec.get("decision") == "reject":
            out.discard(qid)
        else:
            out.add(qid)
    return out


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


def _cand_row(cand: dict, why: str) -> dict[str, Any]:
    scores = cand.get("screen_scores") or {}
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
    }


def frontier_gates(
    known_artist_qids: Iterable[str],
    *,
    frontier_path: Path | None = None,
    allowlist: set[str] | None = None,
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

    new_artist: list[dict] = []
    drainable_new = 0
    for c in cands:
        aq = c.get("artist_qid")
        if not aq or aq in known or aq in allow:
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
        clears_by="recording a creator death year or work date",
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
            label="Candidates by artists not yet in the archive",
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
            clears_by="approving the artist, or a widened auto-accept rule",
            items=reviewed,
        ),
        Gate(
            name="deferred_transfer",
            label="Candidates deferred on image quality",
            blocking=len(deferred),
            # These clear when a holder re-digitises, not by anything a person
            # does here. Honest zero for a human drain — but the gate is not
            # stuck, so it is flagged auto_clears rather than deadlocked.
            drainable=0,
            auto_clears=True,
            clears_by="re-proposed automatically on a later tick; no human action needed",
            note=(
                "Deferrals are not sticky rejects — each is re-proposed on a later "
                "tick. Listed so a persistent deferral is visible rather than silent."
            ),
            items=deferred,
        ),
    ]


def candidate_image_url(qid: str, *, frontier_path: Path | None = None) -> str | None:
    """The discovery image URL a frontier candidate carries, or None.

    Exists so the image proxy can resolve a Q-ID to a URL the pipeline already
    chose, rather than fetching a URL supplied by the caller.
    """
    data = _read_json(frontier_path or FRONTIER_JSON)
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
    """work Q-ID -> "keep" | "reject". Last decision for a work wins."""
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
        if qid and decision in {"keep", "reject"}:
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
        if cand.get("status") != "screened":
            continue
        if cand.get("artist_qid") not in approved_artists:
            continue
        qid = cand.get("qid")
        if not qid or qid in seen:
            continue
        row = _cand_row(cand, "released by approving this artist")
        row["decision"] = None
        out.append(row)
    out.sort(key=lambda r: (str(r.get("artist_label") or ""), str(r.get("title") or "")))
    return out
