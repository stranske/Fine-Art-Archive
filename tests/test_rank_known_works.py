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


def test_missing_only_drops_held_works(monkeypatch, tmp_path, capsys) -> None:
    import json

    # archive already holds one work by QID and one by title
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "meta.json").write_text(
        json.dumps({"stable_identifiers": {"wikidata_q": "Q100"}, "title": "Held By Qid"}),
        encoding="utf-8",
    )
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "meta.json").write_text(
        json.dumps({"title": "Held By Title"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        cli,
        "fetch_wikidata_sparql",
        lambda q: [
            _kw("Held By Qid", source_ids={"wikidata": "Q100"}, sitelinks=5),
            _kw("Held By Title", sitelinks=5),
            _kw("Not Held", sitelinks=5, image_url="http://x"),
        ],
    )
    monkeypatch.setattr(cli, "fetch_wikipedia_list", lambda n: [])
    monkeypatch.setattr(cli, "fetch_met", lambda n: [])

    rc = cli.main(["--artist-qid", "Q1", "--missing-only", "--staging-dir", str(tmp_path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Not Held" in out
    assert "Held By Qid" not in out
    assert "Held By Title" not in out


def test_is_held_matches_qid_and_title() -> None:
    held_qids, held_titles = {"Q100"}, {cli._norm_title("Held By Title")}
    assert cli.is_held(_kw("x", source_ids={"wikidata": "Q100"}), held_qids, held_titles)
    assert cli.is_held(_kw("Held By Title!"), held_qids, held_titles)
    assert not cli.is_held(_kw("Brand New", source_ids={"wikidata": "Q999"}), held_qids, held_titles)


def test_load_held_reads_qids_and_titles(tmp_path) -> None:
    import json

    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "meta.json").write_text(
        json.dumps({"stable_identifiers": {"wikidata_q": "Q7"}, "title": "The Night Watch"}),
        encoding="utf-8",
    )
    qids, titles = cli.load_held(tmp_path)
    assert qids == {"Q7"}
    assert cli._norm_title("The Night Watch") in titles


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
