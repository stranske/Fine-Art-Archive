"""Title-variant match in the creator's oeuvre (Stage 3 of the exhaustion pipeline).

Stage 1 (:mod:`work_qid_by_creator`) fetches the creator's Wikidata oeuvre and
matches the sidecar title against each work's **English** label and altLabels
with SequenceMatcher at 0.93. On this archive that is where the search ends for
almost every work it cannot resolve: of the 466 works search-plan v4 retired
with a creator QID and no Q-ID, **358 were declined as ``by-creator:
below-threshold``** -- the oeuvre was fetched, and nothing scored high enough.

Reading those near-misses, the gap is not that the threshold is too high. It is
that the two strings differ STRUCTURALLY in ways that say nothing about which
work is meant:

======================  =============================================
archive copy number     ``Visio Tondali 2``, ``Beech Grove I.2``
language                the archive title is English, the label is not
a qualifier prefix      ``Portrait with a Bottle of Wine`` for
                        ``Self-Portrait With a Bottle of Wine``
a label disambiguator   ``Franklin Delano Roosevelt (1882-1945)``
======================  =============================================

Lowering the threshold is the wrong repair, and the field says so: at 0.83 it
contains ``Man in a Turban`` -> ``Young Man in a Turban`` (a different Rembrandt,
eighteen years apart) and at 0.53 ``February`` -> ``January`` (Grant Wood, same
year, same series). So this stage keeps a 0.93 bar and instead scores a small
set of NORMALIZED VARIANTS of each side, plus one structural predicate --
ordered token containment -- under guards strictly tighter than Stage 1's.

**Measured before it was built.** Against the archive's 466 retired works this
resolves ~4%: about one in twenty-five. That is the honest ceiling of a title
match here, because those works carry almost nothing else to match on -- 2.8%
record a holder, 0.2% an accession number, none a source URL. The value is that
it is exact about which ~4%, and that the works it declines are declined for a
NAMED reason a later plan can act on (see ``derived-item-candidate`` below).

Precision is the point, not recall. Every relaxation here was checked against
the archive's already-resolved works, where a proposal that differs from the
Q-ID on file is the exact wrong write this stage would make.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from fine_art_archive.enrichment.holder_by_creator import SparqlQuerier, _score_for, year_of
from fine_art_archive.identity.artist_resolver import fold_name

__all__ = [
    "CONTAINMENT_MIN",
    "TitleCandidate",
    "creator_work_titles",
    "is_derivation_candidate",
    "resolve_by_title_variants",
    "title_variants",
]

SCORE_THRESHOLD = 0.93
AMBIGUITY_MARGIN = 0.04
YEAR_TOLERANCE = 6
#: Containment is a weaker signal than an equal title, so the year has to agree
#: more closely -- and, unlike Stage 1, it is REQUIRED on both sides.
CONTAINMENT_YEAR_TOLERANCE = 2

#: How much of the longer title the shorter one must account for. Measured, not
#: chosen: at 2/3 the field contains ``Garden at Arles`` -> ``Garden of the
#: Hospital in Arles`` and ``Flowering Plum Orchard (after Hiroshige)`` -> ``The
#: Flowering Orchard`` -- two van Gogh pairs that are different paintings. The
#: true pairs that motivate the rule sit at 3/4 or better. One content word
#: dropped out of three is where a qualifier stops being a qualifier.
CONTAINMENT_MIN = 0.75

_PAREN_RE = re.compile(r"\s*\(([^)]*)\)")
#: A trailing small integer on an archive title is a second FILE of one work
#: ("Visio Tondali 2"), not part of the title. Bounded to two digits so a date
#: or a catalogue number is not silently eaten.
_COPY_NUM_RE = re.compile(r"[\s.]+([2-9]|[1-9][0-9])$")
_MARKER_INDEX_RE = re.compile(r"\s*\d+$")

#: Words a sidecar puts in parentheses to name a SECTION of a work, or a
#: rendition of it. A title carrying one is not the work: dropping the
#: parenthetical turns "Isenheim Altarpiece (Crucifixion)" into the whole
#: altarpiece, which is how one Q-ID came to sit on fifty Scrovegni sidecars.
#: These are reported as ``derived-item-candidate`` -- the fix is a
#: ``derived_from`` link, not a work Q-ID.
DERIVATION_MARKERS = frozenset(
    {
        "detail", "details", "fragment", "crop", "cropped", "section", "panel",
        "left panel", "right panel", "central panel", "closed", "open", "verso",
        "recto", "reverse", "predella", "interior", "exterior",
        "framed", "unframed", "full frame",
    }
)

#: Dropped before measuring containment: they carry no identity of their own, so
#: "Vase of Flowers and Cup" and "Vase with Flowers and Cup" are one title.
_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "in", "on", "at", "with", "de", "la", "le", "el", "il"}
)


@dataclass(frozen=True)
class OeuvreWork:
    """One work in a creator's oeuvre, with its labels in every language."""

    work_qid: str
    labels: tuple[str, ...]
    inception: str | None = None


@dataclass(frozen=True)
class TitleCandidate:
    work_qid: str
    label: str
    score: float
    kind: str  # "variant-title" | "containment"
    inception: str | None
    normalization: str  # which form of the SIDECAR title reached the match


def _titles_query(creator_qid: str, *, limit: int = 4000) -> str:
    """The oeuvre with labels and altLabels in EVERY language.

    Stage 1 filters both to English, which is right for its purpose -- it also
    reads collection, accession and location, and an all-language fetch of
    those would multiply the rows. Here only the title matters, and an
    English-only fetch silently scores a real match against an empty string
    whenever a work has no English label.
    """
    return (
        "SELECT ?w (SAMPLE(?inception) AS ?inception) "
        '(GROUP_CONCAT(DISTINCT ?lbl; separator="||") AS ?labels) '
        '(GROUP_CONCAT(DISTINCT ?alt; separator="||") AS ?alts) WHERE { '
        f"?w wdt:P170 wd:{creator_qid} . "
        "OPTIONAL { ?w rdfs:label ?lbl } "
        "OPTIONAL { ?w skos:altLabel ?alt } "
        "OPTIONAL { ?w wdt:P571 ?inception } "
        f"}} GROUP BY ?w LIMIT {limit}"
    )


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split("||") if part.strip()]


def creator_work_titles(creator_qid: str, *, client: SparqlQuerier) -> list[OeuvreWork]:
    """Every work by this creator, with all-language labels and altLabels."""
    payload = client.query(_titles_query(creator_qid))
    if not isinstance(payload, dict):
        return []
    works: list[OeuvreWork] = []
    for binding in payload.get("results", {}).get("bindings", []):
        uri = binding.get("w", {}).get("value", "")
        work_qid = uri.rsplit("/", 1)[-1]
        if not work_qid:
            continue
        labels = _split(binding.get("labels", {}).get("value")) + _split(
            binding.get("alts", {}).get("value")
        )
        works.append(
            OeuvreWork(
                work_qid=work_qid,
                labels=tuple(labels),
                inception=binding.get("inception", {}).get("value"),
            )
        )
    return works


def _parenthetical_parts(title: str) -> tuple[str, list[str]]:
    inner = [match.group(1).strip() for match in _PAREN_RE.finditer(title)]
    return _PAREN_RE.sub("", title).strip(), inner


def is_derivation_candidate(title: str) -> bool:
    """True when the title names a section or rendition rather than a work."""
    _stripped, inner = _parenthetical_parts(title)
    return any(_MARKER_INDEX_RE.sub("", fold_name(part)) in DERIVATION_MARKERS for part in inner)


def title_variants(title: str) -> list[tuple[str, str]]:
    """``(normalized form, how it was reached)``, most faithful first.

    A parenthetical's CONTENT is deliberately never offered as a title of its
    own. It is a gloss, a series, or a section, and none of those is the work:
    scoring it directly matched "Chiryu, Station 40 (The Fifty-Three Stations of
    the Tokaido)" to the Q-ID of the SERIES -- the group-of-paintings error the
    uniqueness guard exists to catch, arrived at from the other direction.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(text: str, how: str) -> None:
        folded = _score_for(text)
        if folded and folded not in seen:
            seen.add(folded)
            out.append((folded, how))

    add(title, "as-written")
    add(_COPY_NUM_RE.sub("", title), "copy-number")
    stripped, _inner = _parenthetical_parts(title)
    if stripped:
        add(stripped, "parenthetical")
        add(_COPY_NUM_RE.sub("", stripped), "parenthetical")
    return out


def _content_tokens(folded: str) -> list[str]:
    """Tokens that carry identity: no stopwords, and nothing one character long.

    The single-character rule is not cosmetic. Folding "The Artist's Son" leaves
    a bare "s", which counted as a content word made it 3 tokens against "The
    Artist's Son, Paul"'s 4 -- exactly 0.75, so a Cezanne who painted his son
    many times passed a threshold set to keep him out. Without it the pass
    proposed Q20189742 for a sidecar already holding Q22337859.
    """
    return [
        token for token in folded.split() if len(token) > 1 and token not in _STOPWORDS
    ]


def containment(a: str, b: str) -> float:
    """How much of the longer title the shorter accounts for, or 0.0.

    Ordered, not set-based: "Portrait of Bianca Ponzoni Anguissola or Lady in a
    Fur" contains "Portrait of Bianca Ponzoni Anguissola" in sequence. An
    unordered bag would also match two works that share a word pool in different
    roles. Returns 0.0 below :data:`CONTAINMENT_MIN`.
    """
    tokens_a, tokens_b = _content_tokens(a), _content_tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    short, long = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    index = 0
    for token in long:
        if index < len(short) and token == short[index]:
            index += 1
    if index != len(short):
        return 0.0
    ratio = len(short) / len(long)
    return ratio if ratio >= CONTAINMENT_MIN else 0.0


def _rank(title: str, works: list[OeuvreWork]) -> list[TitleCandidate]:
    """Best candidate per distinct work, highest score first."""
    forms = title_variants(title)
    best: dict[str, TitleCandidate] = {}
    for work in works:
        top: TitleCandidate | None = None
        for label in work.labels:
            for label_form, _how in title_variants(label):
                for form, how in forms:
                    # One content word is not an identification. Matched across
                    # every language, a bare "Mars" or "February" finds a
                    # same-named work in an oeuvre that may hold several.
                    if min(len(_content_tokens(form)), len(_content_tokens(label_form))) < 2:
                        continue
                    score = SequenceMatcher(None, form, label_form).ratio()
                    kind = "variant-title"
                    if score < SCORE_THRESHOLD:
                        contained = containment(form, label_form)
                        if not contained:
                            continue
                        # Ordered just below an equal title, and by how much of
                        # the longer title survived, so a full match always wins
                        # a tie against a contained one.
                        score = SCORE_THRESHOLD - (1.0 - contained) * 0.01
                        kind = "containment"
                    if top is None or score > top.score:
                        top = TitleCandidate(
                            work.work_qid, label, score, kind, work.inception, how
                        )
        if top is not None:
            current = best.get(top.work_qid)
            if current is None or top.score > current.score:
                best[top.work_qid] = top
    return sorted(best.values(), key=lambda candidate: -candidate.score)


def resolve_by_title_variants(
    title: str,
    sidecar_year: int | None,
    creator_qid: str | None,
    *,
    client: SparqlQuerier,
    works: list[OeuvreWork] | None = None,
) -> tuple[TitleCandidate | None, str]:
    """Resolve one work's QID from its creator's oeuvre under v5 normalization.

    Returns ``(TitleCandidate, "match")`` or ``(None, reason)``. The reasons are
    load-bearing -- a later plan acts on them rather than re-deriving them:

    ``derived-item-candidate``
        the title names a section or rendition ("... (detail)"). The repair is a
        ``derived_from`` link, and such a sidecar must hold no work Q-ID at all.
    ``title-parenthetical-needs-review``
        the match was reached only by dropping a parenthetical from the SIDECAR
        title, which may have named a section.
    ``containment-needs-year``
        contained titles agreed but one side has no year, so the weaker match
        has no second signal.
    """
    if not creator_qid:
        return None, "no-creator"
    if is_derivation_candidate(title):
        return None, "derived-item-candidate"
    oeuvre = works if works is not None else creator_work_titles(creator_qid, client=client)
    if not oeuvre:
        return None, "no-works"

    ranked = _rank(title, oeuvre)
    if not ranked:
        return None, "no-candidate"
    best = ranked[0]
    if len([c for c in ranked if c.score >= best.score - AMBIGUITY_MARGIN]) > 1:
        return None, "ambiguous"

    if best.normalization == "parenthetical":
        # Wikidata uses a parenthetical as a DISAMBIGUATOR ("Franklin Delano
        # Roosevelt (1882-1945)"), so dropping it from the LABEL is safe. An
        # archive title uses it to name a SECTION -- "Isenheim Altarpiece
        # (Crucifixion)", "The School of Athens (detail)" -- and dropping that
        # turns a panel into the whole altarpiece. The asymmetry is deliberate.
        return None, "title-parenthetical-needs-review"

    work_year = year_of(best.inception)
    if best.kind == "containment":
        if sidecar_year is None or work_year is None:
            return None, "containment-needs-year"
        if abs(sidecar_year - work_year) > CONTAINMENT_YEAR_TOLERANCE:
            return None, "year-mismatch"
    elif (
        sidecar_year is not None
        and work_year is not None
        and abs(sidecar_year - work_year) > YEAR_TOLERANCE
    ):
        return None, "year-mismatch"
    return best, "match"


def year_from(value: Any) -> int | None:
    """Re-exported so callers need not import Stage 1 for the year parser."""
    return year_of(value)
