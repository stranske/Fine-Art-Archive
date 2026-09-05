"""Artist-name splitting and source-quality blending — two places a wrong answer is silent.

`split_multi` decides whether "Rubens and Jan Brueghel" is two artists or one, and whether
"Vermeer, Johannes" is a family/given pair rather than a collaboration. A wrong split does not
raise: it INVENTS an artist or MERGES two, and the archive's identity graph absorbs it.

`blended_stats` warms empirical statistics in over 30 days, falling back to the tier prior when it
cannot read `first_seen`. That fallback was unexercised, and it is the branch that decides what a
source's quality looks like when its own timestamp is unreadable.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from fine_art_archive.identity.artist_resolver import split_multi
from fine_art_archive.quality.source_quality import (
    DEFAULT_TIER_PRIORS,
    WARMUP_DAYS,
    SourceQualityAggregate,
    _load_legacy_bucket_lookup,
)

# ---------------------------------------------------------------------------------------------
# Splitting attribution strings.
# ---------------------------------------------------------------------------------------------


def test_a_single_comma_is_read_as_family_given_not_a_collaboration():
    """ "Vermeer, Johannes" is ONE painter. Splitting it invents a second artist called Johannes."""
    assert split_multi("Vermeer, Johannes") == ["Vermeer, Johannes"]


def test_two_artists_joined_by_and_are_split():
    assert split_multi("Rubens and Jan Brueghel") == ["Rubens", "Jan Brueghel"]


def test_an_ampersand_also_splits():
    assert split_multi("Rubens & Jan Brueghel") == ["Rubens", "Jan Brueghel"]


def test_a_comma_alongside_and_is_a_real_list():
    """The single-comma exemption must not swallow a genuine three-way collaboration."""
    parts = split_multi("Rubens, Snyders and Jan Brueghel")
    assert len(parts) == 3
    assert "Rubens" in parts and "Snyders" in parts


@pytest.mark.parametrize(
    "marker",
    [
        "Style of",
        "After",
        "Copy of",
        "Attributed to",
        "Circle of",
        "Follower of",
        "Workshop of",
        "School of",
    ],
)
def test_every_relation_marker_is_stripped_from_the_identity(marker):
    """These change the RELATION, not the identity.

    Left attached, "Follower of Rembrandt" becomes a distinct artist from "Rembrandt" and the
    archive grows a phantom entry for every marker anyone has ever typed.
    """
    assert split_multi(f"{marker} Rembrandt") == ["Rembrandt"]


def test_marker_stripping_is_case_insensitive():
    assert split_multi("STYLE OF Rembrandt") == ["Rembrandt"]
    assert split_multi("attributed to Rembrandt") == ["Rembrandt"]


def test_markers_are_stripped_from_each_part_of_a_collaboration():
    assert split_multi("After Rubens and Circle of Brueghel") == ["Rubens", "Brueghel"]


def test_a_marker_inside_a_name_is_not_stripped():
    """Only a LEADING marker is a relation. Anchoring matters: an unanchored pattern would eat
    the word wherever it appeared."""
    assert split_multi("Jan After") == ["Jan After"]


def test_surrounding_whitespace_never_survives():
    assert split_multi("  Rubens  and  Brueghel  ") == ["Rubens", "Brueghel"]


def test_an_empty_part_is_dropped_rather_than_becoming_a_blank_artist():
    """A blank entry in the identity graph is worse than a missing one — it matches everything."""
    assert "" not in split_multi("Rubens and  and Brueghel")


# ---------------------------------------------------------------------------------------------
# Blending empirical statistics with the tier prior.
# ---------------------------------------------------------------------------------------------


def _agg(**kw) -> SourceQualityAggregate:
    base = {"source": "example.org", "work_class": "painting", "host_tier": 1}
    base.update(kw)
    return SourceQualityAggregate(**base)


def test_with_no_first_seen_the_prior_is_returned_whole():
    """No empirical history means no evidence to blend; the prior IS the answer."""
    assert _agg(first_seen=None).blended_stats() == dict(DEFAULT_TIER_PRIORS[1])


def test_an_unparseable_first_seen_falls_back_to_the_prior():
    """The branch this file exists for.

    An unreadable timestamp is not an old source and not a new one. Falling back to the prior is
    the honest answer; treating it as OLD would fully trust evidence whose age is unknown, and
    crashing would take down an aggregation over every source because one sidecar had a bad date.

    THE EVIDENCE HERE MUST DIFFER FROM THE PRIOR, and the first version of this test omitted it.
    With no counts, `empirical_stats` is all None, so a blend at t=0 and a straight return of the
    prior produce the identical dict — a break that treated the bad date as "brand new" passed.
    Perfect verify counts make the two answers distinguishable.
    """
    agg = _agg(first_seen="not-a-timestamp", n_acquired=10, n_verify_total=10, n_verify_pass=10)
    empirical = agg.empirical_stats()
    assert empirical.get("verify_pass_rate") not in (
        None,
        DEFAULT_TIER_PRIORS[1]["verify_pass_rate"],
    ), "the fixture must produce evidence that differs from the prior, or nothing is pinned"
    assert agg.blended_stats() == dict(DEFAULT_TIER_PRIORS[1])
    # WHAT THIS CANNOT PIN, stated so nobody re-derives it. Substituting `now` for the bad date is
    # BEHAVIOURALLY IDENTICAL to returning the prior: t becomes 0, so the blend is
    # `0*empirical + 1*prior`. No input distinguishes them, and a break demo that swaps one for
    # the other correctly catches nothing. The risky direction is the other one — treating an
    # unknown age as OLD, which fully trusts evidence whose warmup position nobody knows — and
    # that is what the assertion above does catch.


def test_a_source_older_than_the_warmup_window_is_fully_weighted_to_its_own_evidence():
    old = (datetime.now(UTC) - timedelta(days=WARMUP_DAYS * 2)).isoformat()
    agg = _agg(first_seen=old, n_acquired=10, n_verify_total=10, n_verify_pass=10)
    stats = agg.blended_stats()
    empirical = agg.empirical_stats()
    for key, value in empirical.items():
        if value is not None:
            assert stats[key] == pytest.approx(value), key


def test_midway_through_warmup_the_answer_sits_between_prior_and_evidence():
    """The whole point of a warmup: a source with three days of history must not be trusted like
    one with three months, nor ignored."""
    half = (datetime.now(UTC) - timedelta(days=WARMUP_DAYS / 2)).isoformat()
    agg = _agg(first_seen=half, n_acquired=10, n_verify_total=10, n_verify_pass=10)
    stats = agg.blended_stats()
    prior = DEFAULT_TIER_PRIORS[1]
    empirical = agg.empirical_stats()
    key = "verify_pass_rate"
    if empirical.get(key) is not None and empirical[key] != prior[key]:
        low, high = sorted((prior[key], empirical[key]))
        assert low < stats[key] < high, (stats[key], low, high)


def test_a_metric_with_no_evidence_keeps_its_prior_even_when_others_have_evidence():
    """Partial evidence must not drag an unmeasured metric toward zero."""
    old = (datetime.now(UTC) - timedelta(days=WARMUP_DAYS * 2)).isoformat()
    agg = _agg(first_seen=old, n_acquired=5, n_verify_total=5, n_verify_pass=5)
    stats = agg.blended_stats()
    empirical = agg.empirical_stats()
    for key, prior_value in DEFAULT_TIER_PRIORS[1].items():
        if empirical.get(key) is None:
            assert stats[key] == prior_value, key


# ---------------------------------------------------------------------------------------------
# Recovering the original bucket from the manifest.
# ---------------------------------------------------------------------------------------------


def test_a_missing_manifest_is_an_empty_lookup_not_an_error(tmp_path):
    """The manifest is optional; its absence must not abort an aggregation over every source."""
    assert _load_legacy_bucket_lookup(tmp_path / "absent.csv") == {}


def test_rows_are_recovered_by_work_id(tmp_path):
    csv_path = tmp_path / "manifest.csv"
    csv_path.write_text(
        "work_id,master_ingested_from\nw1,bucket/a\nw2,bucket/b\n", encoding="utf-8"
    )
    assert _load_legacy_bucket_lookup(csv_path) == {"w1": "bucket/a", "w2": "bucket/b"}


def test_rows_missing_either_half_are_skipped(tmp_path):
    """A work_id with no bucket, or a bucket with no work_id, cannot be joined to anything —
    admitting it would put an empty key or an empty value into the lookup."""
    csv_path = tmp_path / "manifest.csv"
    csv_path.write_text(
        "work_id,master_ingested_from\nw1,bucket/a\n,bucket/orphan\nw3,\n", encoding="utf-8"
    )
    assert _load_legacy_bucket_lookup(csv_path) == {"w1": "bucket/a"}


@pytest.mark.parametrize(
    "first_seen",
    ["2026-08-01T12:00:00", "2026-08-01T12:00:00Z", "2026-08-01T17:30:00+05:30"],
)
def test_aggregate_blends_timestamp_formats_in_utc(first_seen: str) -> None:
    agg = _agg(first_seen=first_seen, n_verify_total=10, n_verify_pass=8)
    stats = agg.blended_stats(now=datetime(2026, 8, 16, 12, tzinfo=UTC))
    assert stats["verify_pass_rate"] == pytest.approx(
        (0.8 + DEFAULT_TIER_PRIORS[1]["verify_pass_rate"]) / 2
    )
    assert all(math.isfinite(value) for value in agg.to_dict()["blended"].values())


def test_aggregate_rejects_non_string_timestamp() -> None:
    agg = _agg(first_seen=20260801, n_verify_total=10, n_verify_pass=8)
    assert agg.blended_stats(now=datetime(2026, 8, 16, 12, tzinfo=UTC)) == DEFAULT_TIER_PRIORS[1]
