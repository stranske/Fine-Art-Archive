"""Tests for the display-worthiness ranking CLI."""

from __future__ import annotations

from scripts import rank_known_works as cli

from fine_art_archive.known_works.fetchers import KnownWork


def _kw(title: str, **kw) -> KnownWork:
    return KnownWork(title=title, **kw)


def test_gather_merges_and_dedupes(monkeypatch) -> None:
    monkeypatch.setattr(
        cli, "fetch_wikidata_sparql", lambda q: [_kw("Irises", year=1889, sitelinks=20)]
    )
    monkeypatch.setattr(
        cli, "fetch_wikipedia_list", lambda n: [_kw("Irises", year=1889, image_url="http://x")]
    )
    monkeypatch.setattr(cli, "fetch_met", lambda n: [])

    works = cli.gather("Q5582", "Vincent van Gogh")

    assert len(works) == 1  # deduped across sources
    assert works[0].sitelinks == 20 and works[0].image_url == "http://x"  # metadata merged


def test_gather_needs_a_source() -> None:
    assert cli.gather(None, None) == []


def test_main_ranks_and_respects_top(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "fetch_wikidata_sparql",
        lambda q: [
            _kw("Obscure Study", sitelinks=0),
            _kw("Famous", sitelinks=50, image_url="http://x", holder="MoMA"),
        ],
    )
    monkeypatch.setattr(cli, "fetch_wikipedia_list", lambda n: [])
    monkeypatch.setattr(cli, "fetch_met", lambda n: [])

    rc = cli.main(["--artist-qid", "Q5582", "--top", "1"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Famous" in out
    assert "Obscure Study" not in out  # trimmed by --top 1 (Famous ranks first)
