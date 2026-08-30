"""Five lenses with separate budget shares, instead of one ranker.

The properties pinned here are the ones that make the portfolio worth having
over the single `-sitelinks` sort it replaces:

  * A lens with no feature data is UNAVAILABLE, and forfeits its share to the
    others. It is never a lens that "scored zero" — a broken feature pipeline
    must not be able to masquerade as "nothing matched".
  * The saturation cap holds a subject near its existing archive share and
    never bans it. A cap that rounds a real subject down to zero is a ban.
  * Fame does not get to eat the whole batch. The regional and atypicality
    lenses must still place works that the canon lens ranks last.
"""

from __future__ import annotations

import math
from typing import Any

from fine_art_archive.selection import lenses


def cand(qid: str, *, sitelinks: int | None = None, **features: Any) -> dict:
    row: dict[str, Any] = {"qid": qid}
    if sitelinks is not None:
        row["sitelinks"] = sitelinks
    if features:
        row["lens_features"] = features
    return row


# --------------------------------------------------------------------------
# Availability
# --------------------------------------------------------------------------
def test_lens_without_feature_data_is_unavailable_not_zero() -> None:
    """The failure this design exists to make impossible.

    A pool carrying only sitelinks can be ranked by canon and by nothing else.
    The other four must report `available=False` with a reason, so a broken
    feature precompute is visible instead of looking like a quiet batch.
    """
    pool = [cand("Q1", sitelinks=5), cand("Q2", sitelinks=2)]
    _, reports = lenses.select(pool, batch_cap=2)
    by_name = {r.name: r for r in reports}

    assert by_name["canon"].available is True
    for name in ("atypicality", "series", "regional", "standing"):
        assert by_name[name].available is False, name
        assert by_name[name].reason, "an unavailable lens must say why"
        assert by_name[name].chosen == []


def test_unavailable_lens_forfeits_its_share_rather_than_shrinking_the_batch() -> None:
    pool = [cand(f"Q{i}", sitelinks=i) for i in range(10)]
    chosen, _ = lenses.select(pool, batch_cap=7)
    assert len(chosen) == 7, "canon alone must still fill the batch"


def test_zero_genre_share_is_rejected_rather_than_scoring_perfect() -> None:
    """A share of 0 means the data is wrong, not that the work is unique."""
    assert lenses._atypicality(cand("Q1", genre_share_in_oeuvre=0)) is None
    assert lenses._atypicality(cand("Q2", genre_share_in_oeuvre=1.5)) is None
    assert lenses._atypicality(cand("Q3", genre_share_in_oeuvre=0.036)) == 0.964


def test_regional_share_must_be_finite_and_within_the_unit_interval() -> None:
    """Malformed country shares must not produce impossible or unordered scores."""
    for share in (math.nan, -0.01, 1.01, "not-a-number"):
        assert lenses._regional(cand("bad", country_share_in_archive=share)) is None
    assert lenses._regional(cand("valid", country_share_in_archive=0.25)) == 0.75
    assert lenses._regional(cand("string", country_share_in_archive="0.25")) == 0.75


def test_completed_series_stops_scoring() -> None:
    """A set the archive already holds in full is not a reason to buy more."""
    assert lenses._series(cand("Q1", series_size=36, series_held=36)) is None
    assert lenses._series(cand("Q2", series_size=36, series_held=12)) == 12 / 36
    assert lenses._series(cand("Q3", series_size=1, series_held=0)) is None


# --------------------------------------------------------------------------
# Allocation
# --------------------------------------------------------------------------
def test_allocation_sums_to_the_batch_cap() -> None:
    for cap in range(1, 13):
        got = lenses.allocate(cap, list(lenses.LENS_SHARES), lenses.LENS_SHARES)
        assert sum(got.values()) == cap, cap


def test_every_available_lens_gets_a_slot_when_the_cap_allows() -> None:
    """A lens that never gets a slot is indistinguishable from a disabled one."""
    got = lenses.allocate(7, list(lenses.LENS_SHARES), lenses.LENS_SHARES)
    assert len(got) == 5
    assert all(v >= 1 for v in got.values()), got


def test_allocation_renormalises_over_available_lenses() -> None:
    got = lenses.allocate(6, ["canon", "regional"], lenses.LENS_SHARES)
    assert sum(got.values()) == 6
    # canon 0.35 vs regional 0.20 — canon takes more, but regional is not zeroed
    assert got["canon"] > got["regional"] >= 1


def test_allocation_with_no_available_lenses_is_empty_not_a_crash() -> None:
    assert lenses.allocate(7, [], lenses.LENS_SHARES) == {}
    assert lenses.allocate(0, ["canon"], lenses.LENS_SHARES) == {}


# --------------------------------------------------------------------------
# The point of the whole thing
# --------------------------------------------------------------------------
def test_fame_does_not_eat_the_batch() -> None:
    """The case that motivated the redesign.

    `Obscure` has zero sitelinks and would never be reached by a `-sitelinks`
    sort — it is the Oslo Rembrandt landscape. It is atypical for its painter
    and from an under-represented country, so it must be selected anyway.
    """
    famous = [cand(f"F{i}", sitelinks=100 - i) for i in range(8)]
    obscure = cand(
        "Obscure",
        sitelinks=0,
        genre_share_in_oeuvre=0.036,
        country_share_in_archive=0.001,
    )
    chosen, reports = lenses.select([*famous, obscure], batch_cap=5)

    ids = [c["qid"] for c in chosen]
    assert "Obscure" in ids, ids
    by_name = {r.name: r for r in reports}
    assert by_name["atypicality"].available is True
    assert by_name["regional"].available is True


def test_a_lens_never_double_counts_a_candidate() -> None:
    shared = cand("Shared", sitelinks=99, genre_share_in_oeuvre=0.01, country_share_in_archive=0.0)
    pool = [shared, *[cand(f"Q{i}", sitelinks=i) for i in range(6)]]
    chosen, reports = lenses.select(pool, batch_cap=4)
    ids = [c["qid"] for c in chosen]
    assert len(ids) == len(set(ids))
    picked = [cid for r in reports for cid in r.chosen]
    assert len(picked) == len(set(picked)), "one candidate credited to two lenses"


def test_exhausted_lens_releases_slots_to_rankable_lenses() -> None:
    shared = cand("shared", sitelinks=100, country_share_in_archive=0.1)
    regional_only = [cand(f"regional-{i}", country_share_in_archive=0.2 + i / 100) for i in range(3)]
    chosen, _ = lenses.select([shared, *regional_only], batch_cap=4)
    assert {item["qid"] for item in chosen} == {"shared", "regional-0", "regional-1", "regional-2"}


# --------------------------------------------------------------------------
# Saturation cap
# --------------------------------------------------------------------------
def _bucket(c: dict) -> str:
    return str(c.get("bucket", "other"))


def test_saturation_caps_a_share_it_does_not_ban_a_subject() -> None:
    """Tim's correction: not zero Madonnas, just not a thousand of them."""
    pool = [{"qid": f"M{i}", "bucket": "madonna"} for i in range(10)]
    kept, report = lenses.apply_saturation_cap(
        pool, batch_cap=7, archive_shares={"madonna": 0.112}, bucket_of=_bucket
    )
    assert len(kept) >= 1, "a capped subject must still be acquirable"
    assert report.held["madonna"] == len(pool) - len(kept)
    assert report.summary()["total_held"] > 0


def test_cap_reports_headroom_beside_what_it_held() -> None:
    """`held` alone reads as a working filter forever; headroom shows the state."""
    pool = [{"qid": "M1", "bucket": "madonna"}]
    kept, report = lenses.apply_saturation_cap(
        pool,
        batch_cap=7,
        archive_shares={"madonna": 0.112, "landscape": 0.077},
        bucket_of=_bucket,
    )
    assert len(kept) == 1
    assert report.held == {}
    # Landscape was never offered a candidate — its headroom is untouched, and
    # that is visible rather than looking like a cap that rejected everything.
    assert report.headroom["landscape"] >= 1
    assert report.summary()["total_headroom"] >= 1


def test_bucket_with_no_recorded_share_is_uncapped_not_blocked() -> None:
    """An unknown share must not silently forbid a subject."""
    pool = [{"qid": f"X{i}", "bucket": "unheard-of"} for i in range(5)]
    kept, report = lenses.apply_saturation_cap(
        pool, batch_cap=7, archive_shares={"madonna": 0.112}, bucket_of=_bucket
    )
    assert len(kept) == 5
    assert report.held == {}
