#!/usr/bin/env python3
"""Render the weekly decision page from weekly_review_<date>.json.

Read-only. Produces docs/reports/weekly_review_<date>.html — a self-contained page that
shows the evidence behind each open decision and records verdicts to a downloadable
weekly_decisions_<date>.json, which the next session reads directly.

Usage (on the Mac):
    /Users/teacher/.faa-venv/bin/python3 scripts/render_weekly_review.py --date 2026-08-03
"""
from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "docs" / "reports"

# Populated from thumbmap_<date>.json when make_review_thumbs.py has been run. Serving
# 480px JPEGs instead of 30-250 MB masters is what makes the page usable.
THUMBS: dict[str, str] = {}
# absolute thumb path -> relative src for the current render pass
_ACTIVE_REL: dict[str, str] = {}


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def evidence_title(title: str, *measured_values: int) -> str:
    """Refuse a heading whose numeric claims are absent from its evidence.

    Decision headings are high-salience owner prompts.  Making every numeral
    name a supplied measurement prevents a copied count from surviving after
    the payload changes (the historical 138-vs-88 failure).
    """
    stated = {int(token.replace(",", "")) for token in re.findall(r"\d[\d,]*", title)}
    measured = {int(value) for value in measured_values}
    unsupported = stated - measured
    if unsupported:
        raise ValueError(
            f"heading contains unsupported measurement(s) {sorted(unsupported)}: {title}"
        )
    return title


def furl(p: str) -> str:
    if not p:
        return ""
    return "file://" + urllib.parse.quote(p)


def thumb(path: str, label: str, cls: str = "") -> str:
    if not path:
        return f'<div class="ph {cls}">no file</div>'
    path = THUMBS.get(path, path)
    # When serving over http (the project convention: one dir per review, python -m
    # http.server on 127.0.0.1), file:// URLs do not load. Emit a relative src instead.
    src = _ACTIVE_REL.get(path) or furl(path)
    return (
        f'<img class="tn {cls}" loading="lazy" src="{e(src)}" alt="{e(label)}" '
        f"onerror=\"this.replaceWith(Object.assign(document.createElement('div'),"
        f"{{className:'ph',textContent:'not materialised'}}))\">"
    )


def card(cid: str, num: str, title: str, stakes: str, body: str, options: list[tuple[str, str]]) -> str:
    opts = "".join(
        f'<label class="opt"><input type="radio" name="d_{cid}" value="{e(v)}" '
        f'onchange="setD(\'{cid}\',this.value)"><span><b>{e(v)}</b> — {e(desc)}</span></label>'
        for v, desc in options
    )
    return f"""
<section class="card" id="{cid}">
  <div class="chead">
    <span class="num">{e(num)}</span>
    <h2>{e(title)}</h2>
    <span class="badge" id="badge_{cid}">undecided</span>
  </div>
  <p class="stakes">{stakes}</p>
  <div class="body">{body}</div>
  <div class="decide">
    <h3>Your call</h3>
    {opts}
    <textarea placeholder="Notes / conditions (optional) — these come back to me verbatim"
      oninput="setN('{cid}',this.value)" id="n_{cid}"></textarea>
  </div>
</section>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument(
        "--serve-dir",
        default="weekly_review",
        help="docroot under docs/reports/ to write index.html + thumbs/ into, for "
        "`python3 -m http.server`. Pass '' to write a standalone file:// page instead.",
    )
    args = ap.parse_args()
    d = args.date
    data = json.loads((REPORTS / f"weekly_review_{d}.json").read_text())

    tm = REPORTS / f"thumbmap_{d}.json"
    if tm.exists():
        THUMBS.update(json.loads(tm.read_text()))
        print(f"using {len(THUMBS)} local thumbnails")
    else:
        print("no thumbmap found — page will reference full-size masters "
              "(run scripts/make_review_thumbs.py first)")

    dated_rel: dict[str, str] = {}
    for abs_thumb in set(THUMBS.values()):
        dated_rel[abs_thumb] = f"thumbs_{d}/{Path(abs_thumb).name}"
    _ACTIVE_REL.clear()
    _ACTIVE_REL.update(dated_rel)

    serve_root: Path | None = None
    copied_for_serve = 0
    if args.serve_dir:
        serve_root = REPORTS / args.serve_dir
        tdir = serve_root / "thumbs"
        tdir.mkdir(parents=True, exist_ok=True)
        for abs_thumb in set(THUMBS.values()):
            src = Path(abs_thumb)
            if not src.exists():
                continue
            dst = tdir / src.name
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                dst.write_bytes(src.read_bytes())
            copied_for_serve += 1
        print(f"copied {copied_for_serve} thumbs into {tdir} for http serving")

    ung = data["ungranted"]
    cands = data["candidates"]
    unprom = data["unpromoted"]
    coll = data["collisions"]
    p31 = data["allowed_p31"]
    live = data["live_works"]
    grants = data.get("grants") or {}
    standing_grants = grants.get("standing_acquisition") or []
    promotions = (data.get("ops") or {}).get("promotions") or []
    last_promotion_date = max((p.get("ts", "") for p in promotions), default="")[:10]

    # ---------- 1. grant attribution
    rows = []
    for grant in sorted(ung["by_grant"]):
        items = ung["by_grant"][grant]
        rows.append(
            f'<h4>{e(grant)} — {len(items)} promotions '
            f'<span class="dim">(recorded scope: '
            + ("8 duplicate pairs; metadata transfer + quarantine" if grant == "G41"
               else "6 sidecars with wrong artist Q-IDs; modify-in-place only")
            + ")</span></h4>"
        )
        rows.append('<div class="grid">')
        for it in items:
            rows.append(
                f"""<figure class="cellw">
  {thumb(it['master'], it['title'])}
  <figcaption>
    <b>{e(it['title'])}</b><br>
    <span class="dim">{e(it['artist'])}</span><br>
    <span class="mono dim">{e(it['wid'])}</span><br>
    <span class="dim">{e(it['size_mb'])} MB · {e(it['batch'])}</span>
    <label class="flag"><input type="checkbox" onchange="flag('{e(it['wid'])}',this.checked)"> flag this one</label>
  </figcaption>
</figure>"""
            )
        rows.append("</div>")
    grant_counts = {grant: len(items) for grant, items in ung["by_grant"].items()}
    grant_body = f"""
<p>The grant ledger was parsed from <code>permissions.md</code>. These {ung['total']} promotion
records name grant IDs whose operation does not explicitly include a move into
<code>Art/works/</code>: {e(', '.join(f'{g} ({n})' for g, n in sorted(grant_counts.items())))}.</p>
<p class="warn">Why it matters: <code>operations.log</code> plus the authorizing grant is the undo
script. A promotion is shown here only when the current ledger cannot explain it.</p>
{''.join(rows)}"""

    # ---------- 2. candidates
    ccards = []
    for c in cands["top"]:
        held = (
            "<ul class='held'>" + "".join(f"<li>{e(t)}</li>" for t in c["held_titles"]) + "</ul>"
            if c["held_titles"]
            else "<p class='dim'>none held</p>"
        )
        ccards.append(
            f"""<figure class="cand" id="c_{e(c['qid'])}">
  <img class="ctn" loading="lazy" src="{e(c['thumb'])}" alt="{e(c['title'])}"
    onerror="this.replaceWith(Object.assign(document.createElement('div'),{{className:'ph',textContent:'thumb unavailable'}}))">
  <figcaption>
    <b>{e(c['title'])}</b><br>
    <span class="dim">{e(c['artist'])}</span> ·
    <a href="{e(c['wikidata_url'])}" target="_blank" class="mono">{e(c['qid'])}</a><br>
    <span class="dim">{c['sitelinks']} sitelinks · you already hold {c['held_count']} by this artist</span>
    <details><summary>held by this artist</summary>{held}</details>
    <div class="pick">
      <button onclick="pick('{e(c['qid'])}','acquire',this)">acquire</button>
      <button onclick="pick('{e(c['qid'])}','skip',this)">skip</button>
      <button onclick="pick('{e(c['qid'])}','later',this)">later</button>
    </div>
  </figcaption>
</figure>"""
        )
    artist_counts = Counter(c["artist"] for c in cands["top"] if c.get("artist"))
    concentration = ", ".join(
        f"{count} {artist}" for artist, count in artist_counts.most_common(3) if count > 1
    )
    cand_body = f"""
<p>The current grant ledger contains no standing acquisition authority. This preview asks whether to
create one and which of the {len(cands['top'])} shown candidates belong in the first authorized batch.
Pick per work below — that <em>is</em> the batch list, so it does not need to be reconstructed later.</p>
<p class="dim">Frontier: {cands['frontier_total']} total · {cands['by_status'].get('screened',0)} screened ·
{cands['by_status'].get('review',0)} held at the subject gate · {cands['by_status'].get('rejected',0)} sticky-rejected.
Ranked by Wikidata sitelinks, the notability proxy. Artist names resolved by live lookup, not recall.</p>
<div class="cgrid">{''.join(ccards)}</div>
{f'<p class="dim">Candidate concentration: {e(concentration)}.</p>' if concentration else ''}"""

    # ---------- 3. generator starvation
    latest_run = cands.get("latest_run") or {}
    raw_by_generator = latest_run.get("raw_by_generator") or {}
    admitted_by_generator = latest_run.get("admitted_by_generator") or {}
    active_generators = [g for g, n in raw_by_generator.items() if n]
    starved_generators = [g for g in active_generators if not admitted_by_generator.get(g)]
    gen_rows = "".join(
        f"<tr><td><code>{e(g)}</code></td><td>{raw_by_generator[g]}</td>"
        f"<td>{admitted_by_generator.get(g, 0)}</td></tr>"
        for g in active_generators
    )
    gen_body = f"""
<p>The latest discovery run at {e(latest_run.get('ts'))} produced candidates from
{len(active_generators)} active generators. The table is read directly from that run's merge payload.</p>
<table><tr><th>generator</th><th>raw</th><th>admitted</th></tr>{gen_rows}</table>
<p>Added: <b>{latest_run.get('added', 0)}</b>. Dropped by the cap after eligibility and deduplication:
<b>{latest_run.get('capped', 0)}</b>.</p>"""

    # ---------- 4. unpromoted
    urows = []
    for u in unprom:
        coll_html = (
            f"""<div class="vs">
  <div>{thumb(u['staged_master'], 'staged', 'sm')}<div class="dim">staged · {e(u['size_mb'])} MB</div></div>
  <div>{thumb(u['collision_master'], 'held', 'sm')}<div class="dim">already held<br><span class="mono">{e(u['title_collision_with'])}</span></div></div>
</div>"""
            if u["title_collision_with"]
            else f"""<div class="vs"><div>{thumb(u['staged_master'], 'staged', 'sm')}
<div class="dim">staged · {e(u['size_mb'])} MB</div></div>
<div class="ph">no title match in archive</div></div>"""
        )
        urows.append(
            f"""<div class="urow">
  <div class="uinfo"><b>{e(u['title'])}</b><br><span class="dim">{e(u['artist'])}</span><br>
    <span class="mono dim">{e(u['wid'])}</span></div>
  {coll_html}
  <div class="pick">
    <button onclick="pickU('{e(u['wid'])}','promote',this)">promote</button>
    <button onclick="pickU('{e(u['wid'])}','discard',this)">discard staged</button>
    <button onclick="pickU('{e(u['wid'])}','keep',this)">leave staged</button>
  </div>
</div>"""
        )
    unprom_body = f"""
<p>{len(unprom)} acquired masters sit in <code>staging_acquisitions/</code> with no matching
<code>Art/works/</code> directory. Several duplicate works you already hold — shown side by side below,
staged on the left, held on the right — so these are plausibly correct skips rather than pending
promotions. Either way <code>discovery_growth_design.md</code> §V-bis names "acquired-but-not-promoted"
as its own alarm, so leaving them ambiguous keeps that alarm ringing.</p>
<p class="warn">Where a held copy exists, read the first hard rule before choosing: the lower-resolution
side is often your Meural display crop, and the pair may be master + crop rather than duplicate.</p>
{''.join(urows)}
<p class="dim">A further 78 staging directories duplicate works already in the archive and are safe to
clear on any verdict here.</p>"""

    # ---------- 5. ALLOWED_P31
    cls_rows = []
    junk = {"Q11086742", "Q1167694", "Q57276"}
    allowed_qids = {c["qid"] for definition in p31["definitions"] for c in definition["classes"]}
    junk_present = sorted(allowed_qids & junk)
    drawing_missing = p31["dropped"]["qid"] not in allowed_qids
    for c in p31["definitions"][0]["classes"]:
        bad = c["qid"] in junk
        cls_rows.append(
            f'<tr class="{"bad" if bad else ""}"><td class="mono">'
            f'<a href="https://www.wikidata.org/wiki/{e(c["qid"])}" target="_blank">{e(c["qid"])}</a></td>'
            f'<td>{e(c["label"])}</td><td>{"NOT AN ARTWORK CLASS" if bad else ""}</td></tr>'
        )
    p31_body = f"""
<p>The active source is <code>{e(p31['definitions'][0]['file'])}</code>. The configured drawing root
<code>{e(p31['dropped']['qid'])}</code> is {"missing" if drawing_missing else "present"};
{len(junk_present)} known non-artwork class IDs are present.</p>
<table><tr><th>Q-ID</th><th>Wikidata label</th><th></th></tr>{''.join(cls_rows)}</table>
<p class="warn">This decision renders only while drawing is missing or a known forbidden ID remains.
Discovery and acquisition otherwise read the same canonical set.</p>"""

    # ---------- 6. work Q-ID collisions
    crows = []
    for c in coll["worst"]:
        ex = "".join(
            f"""<figure class="cellw">{thumb(x['master'], x['title'])}
<figcaption><span class="dim">{e(x['title'])}</span><br>
<span class="mono dim">{e(x['wid'])}</span></figcaption></figure>"""
            for x in c["examples"]
        )
        crows.append(
            f"""<div class="collblk">
  <h4><a href="{e(c['wikidata_url'])}" target="_blank" class="mono">{e(c['qid'])}</a>
  — "{e(c['label'])}" on <b>{c['n']}</b> sidecars</h4>
  <div class="grid">{ex}</div>
</div>"""
        )
    coll_body = f"""
<p>{coll['qids_on_multiple']} work Q-IDs are on more than one sidecar ({coll['extra_assignments']} extra
assignments). A work Q-ID denotes one work, so every one of these is wrong in one of three ways — and the
three want opposite remedies, which is why this is a decision and not a fix:</p>
<ol>
<li><b>Genuine duplicate holdings</b> — D017 dedup territory.</li>
<li><b>A series Q-ID on each member</b> — wants a <code>part_of</code> relation, not dedup.</li>
<li><b>A subject Q-ID mistaken for a work Q-ID</b> — wants a write-time validation rule.</li>
</ol>
<p>The worst offender is case 3, which I got wrong when I filed the issue and corrected after lookup:
<code>Q547923</code> is <b>"The Raising of Lazarus"</b>, sitting on 50 sidecars including a Giotto
<em>Lamentation</em> detail — a different scene entirely. Precedent: G40 found <code>Q488841</code>,
"adoration of the Magi", in the same field.</p>
{''.join(crows)}
<p class="warn">Any dedup arising from this must run <code>scripts/audit_duplicate_decisions.py</code>
first. On 2026-08-01, 26 of 34 proposed quarantines were display copies.</p>"""

    # ---------- completeness sidebar
    issues = f"""
<section class="card" id="issues">
  <div class="chead"><span class="num">FYI</span><h2>The four completeness issues — filed, no decision needed today</h2></div>
  <p class="stakes">These are on GitHub with full evidence. Listed so you know what is tracked, not to
  action now.</p>
  <table>
  <tr><th>#</th><th>finding</th><th>state</th></tr>
  <tr><td><a href="https://github.com/stranske/Fine-Art-Archive/issues/406" target="_blank">406</a></td>
      <td>34 artist Q-IDs do not denote the named artist</td><td class="warn">count is stale — see below</td></tr>
  <tr><td><a href="https://github.com/stranske/Fine-Art-Archive/issues/407" target="_blank">407</a></td>
      <td>canonical/mirror disagree: 69 mirror-only, 1 conflicting</td><td>down from 76 to 1</td></tr>
  <tr><td><a href="https://github.com/stranske/Fine-Art-Archive/issues/408" target="_blank">408</a></td>
      <td>{coll['qids_on_multiple']} work Q-IDs on multiple sidecars</td><td>= current collision evidence</td></tr>
  <tr><td><a href="https://github.com/stranske/Fine-Art-Archive/issues/409" target="_blank">409</a></td>
      <td>steps 9/10/12 falsely marked completed</td><td>reopen proposed</td></tr>
  </table>
  <p class="warn"><b>#406's number does not hold up.</b> The audit reported
  <code>verified_this_run: 0</code> with 818 cached verdicts, so it re-reported an old measurement. I
  re-checked all 10 Q-IDs it names against live Wikidata: <b>17 of 17 carrier sidecars now match, 0
  mismatch.</b> Your G47 resplit fixed them and the cache never noticed. The remaining ~17 of the 34 are
  not named in the report, so I cannot clear those. The real bug is the cache having no TTL.</p>
</section>"""

    decision_cards: list[str] = []
    decision_ids: list[str] = []
    nav_items: list[str] = []

    def add_decision(cid: str, num: str, nav_label: str, title: str, stakes: str,
                     contents: str, options: list[tuple[str, str]]) -> None:
        decision_ids.append(cid)
        decision_cards.append(card(cid, num, title, stakes, contents, options))
        nav_items.append(f'<a href="#{cid}" id="nav_{cid}">{num} · {e(nav_label)}</a>')

    if ung["total"]:
        add_decision(
            "grant_attribution", "1", "grant attribution",
            evidence_title(
                f"{ung['total']} of {len(promotions)} promotions lack current grant authority",
                ung["total"], len(promotions),
            ),
            "Highest consequence: this is an audit-trail gap that gets harder to reconstruct over time.",
            grant_body,
            [
                ("retro-grant", f"record authority for the {ung['total']} unexplained promotions"),
                ("review-each", "review every unexplained promotion before changing the ledger"),
                ("unauthorized", "treat the unexplained promotions as unauthorized pending review"),
                ("accept-as-is", "record the discrepancy without changing the ledger"),
            ],
        )
    if not standing_grants:
        add_decision(
            "acquisition_grant", "2", "acquisition grant",
            evidence_title(
                f"No standing acquisition grant — review {len(cands['top'])} candidates",
                len(cands["top"]),
            ),
            "Without standing authority, each growth batch needs an owner decision.", cand_body,
            [
                ("standing-100", "standing grant: up to 100 works/month, at most 25 per weekly batch"),
                ("standing-50", "standing grant with a tighter 50/month ceiling"),
                ("batch-only", "authorize only the individually selected works"),
                ("hold", "acquire nothing this cycle"),
            ],
        )
    if starved_generators:
        add_decision(
            "generator_cap", "3", "generator cap",
            evidence_title(
                f"Frontier cap admitted zero from {len(starved_generators)} of {len(active_generators)} active generators",
                len(starved_generators), len(active_generators),
            ),
            "A zero-admission generator changes which kinds of work growth can offer.", gen_body,
            [
                ("round-robin", "allocate the cap per generator with surplus redistribution"),
                ("raise-cap", "raise the cap and rank when draining the frontier"),
                ("confirm-first", "inspect the merge path before changing it"),
                ("leave", "accept the current generator concentration"),
            ],
        )
    if unprom:
        add_decision(
            "unpromoted", "4", "unpromoted",
            evidence_title(
                f"{len(unprom)} acquired works remain unpromoted", len(unprom)
            ),
            "These staged works keep the acquired-but-not-promoted alarm active.", unprom_body,
            [
                ("per-item", "use the per-item choices above"),
                ("discard-all", "discard all staged copies"),
                ("promote-nondupe", "promote only works without an archive title match"),
                ("defer", "leave all staged for later review"),
            ],
        )
    p31_problem = p31["dropped"]["qid"] not in allowed_qids or bool(allowed_qids & junk)
    if p31_problem:
        add_decision(
            "allowed_p31", "5", "class whitelist",
            "The acquirer's class whitelist needs correction",
            "The measured whitelist either excludes the dropped class or includes non-artwork classes.", p31_body,
            [
                ("add-drawing-clean", "add the dropped drawing class, remove junk entries, and verify each class"),
                ("add-drawing-only", "add only the dropped drawing class"),
                ("upstream-first", "fix the canonical source before syncing the operational copy"),
                ("no-drawings", "leave drawings outside acquisition scope"),
            ],
        )
    if coll["qids_on_multiple"]:
        add_decision(
            "qid_collisions", "6", "work Q-IDs",
            evidence_title(
                f"{coll['qids_on_multiple']} work Q-IDs are on more than one sidecar",
                coll["qids_on_multiple"],
            ),
            "The denominator remains ambiguous until duplicate, series, and subject uses are separated.", coll_body,
            [
                ("triage-3way", "triage duplicate, series, and subject cases before moving files"),
                ("subject-rule-only", "add the write-time validation rule first"),
                ("dedup-small", "start with the smallest collision clusters"),
                ("defer", "defer collision triage"),
            ],
        )

    body = "".join([*decision_cards, issues])
    nav_html = "\n    ".join([*nav_items, '<a href="#issues">FYI · filed issues</a>'])
    ids_json = json.dumps(decision_ids)
    decision_total = len(decision_ids)

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Fine Art Archive — decisions for {e(d)}</title>
<style>
:root{{--bg:#12100e;--fg:#efe9e1;--dim:#9b938a;--line:#332e29;--card:#1a1714;--acc:#c9a227;--warn:#e0a458;--bad:#c96a5a}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
a{{color:var(--acc)}}
header.top{{padding:26px 32px 18px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:20}}
header.top h1{{margin:0 0 6px;font-size:21px;font-weight:600}}
.kpis{{display:flex;gap:26px;flex-wrap:wrap;margin-top:12px}}
.kpi{{font-size:13px;color:var(--dim)}} .kpi b{{display:block;font-size:20px;color:var(--fg)}}
.kpi.up b{{color:#7fb069}} .kpi.warn b{{color:var(--warn)}}
nav{{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}}
nav a{{font-size:12px;padding:4px 9px;border:1px solid var(--line);border-radius:11px;text-decoration:none;color:var(--dim)}}
nav a.done{{border-color:#7fb069;color:#7fb069}}
main{{max-width:1180px;margin:0 auto;padding:26px 22px 190px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px 22px;margin:0 0 26px}}
.chead{{display:flex;align-items:center;gap:12px;margin-bottom:8px;flex-wrap:wrap}}
.chead h2{{margin:0;font-size:17px;font-weight:600;flex:1;min-width:260px}}
.num{{background:var(--acc);color:#1a1714;font-weight:700;border-radius:5px;padding:1px 8px;font-size:12px}}
.badge{{font-size:11px;color:var(--dim);border:1px solid var(--line);border-radius:10px;padding:2px 9px}}
.badge.set{{color:#7fb069;border-color:#7fb069}}
.stakes{{color:var(--dim);font-size:13.5px;margin:0 0 14px;font-style:italic}}
.warn{{color:var(--warn)}}
.dim{{color:var(--dim)}}
.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px}}
code{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;background:#241f1b;padding:1px 4px;border-radius:3px}}
table{{border-collapse:collapse;margin:12px 0;font-size:13px;width:100%}}
th,td{{border:1px solid var(--line);padding:5px 9px;text-align:left}}
th{{color:var(--dim);font-weight:500}}
tr.bad td{{background:#2a1c19;color:var(--bad)}}
.grid{{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0 16px}}
.cellw{{width:150px;margin:0;font-size:11px}}
.tn{{width:150px;height:105px;object-fit:cover;border-radius:5px;background:#000;display:block}}
.tn.sm{{width:118px;height:84px}}
.ph{{width:150px;height:105px;display:flex;align-items:center;justify-content:center;
  background:#241f1b;color:var(--dim);font-size:10.5px;border-radius:5px;text-align:center}}
.cgrid{{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0}}
.cand{{width:250px;margin:0;background:#211d19;border:1px solid var(--line);border-radius:8px;
  padding:10px;font-size:12px}}
.cand.acquire{{border-color:#7fb069}} .cand.skip{{opacity:.42}} .cand.later{{border-color:var(--warn)}}
.ctn{{width:100%;height:150px;object-fit:cover;border-radius:5px;background:#000;display:block;margin-bottom:7px}}
details summary{{cursor:pointer;color:var(--dim);font-size:11px;margin:5px 0}}
ul.held{{margin:4px 0 0 15px;padding:0;font-size:11px;color:var(--dim)}}
.pick{{display:flex;gap:5px;margin-top:8px;flex-wrap:wrap}}
.pick button{{flex:1;background:#2b2621;color:var(--fg);border:1px solid var(--line);border-radius:5px;
  padding:4px 7px;font-size:11.5px;cursor:pointer}}
.pick button:hover{{border-color:var(--acc)}}
.pick button.on{{background:var(--acc);color:#1a1714;border-color:var(--acc);font-weight:600}}
.urow{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;border-top:1px solid var(--line);padding:12px 0}}
.uinfo{{width:250px;font-size:12.5px}}
.vs{{display:flex;gap:10px}} .vs>div{{font-size:10.5px;text-align:center}}
.collblk{{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}}
.collblk h4{{margin:0 0 6px;font-size:13.5px;font-weight:500}}
.decide{{border-top:1px solid var(--line);margin-top:16px;padding-top:14px}}
.decide h3{{margin:0 0 9px;font-size:13px;color:var(--acc);text-transform:uppercase;letter-spacing:.5px}}
.opt{{display:flex;gap:9px;align-items:flex-start;padding:7px 9px;border:1px solid var(--line);
  border-radius:6px;margin-bottom:6px;cursor:pointer;font-size:13px}}
.opt:hover{{border-color:var(--acc)}}
.opt input{{margin-top:3px}}
textarea{{width:100%;min-height:52px;background:#241f1b;color:var(--fg);border:1px solid var(--line);
  border-radius:6px;padding:8px;font:13px inherit;margin-top:7px}}
.flag{{display:block;margin-top:5px;font-size:10.5px;color:var(--dim);cursor:pointer}}
footer.bar{{position:fixed;bottom:0;left:0;right:0;background:#1a1714;border-top:1px solid var(--line);
  padding:13px 26px;display:flex;gap:16px;align-items:center;z-index:30;flex-wrap:wrap}}
footer.bar button{{background:var(--acc);color:#1a1714;border:0;border-radius:6px;padding:9px 17px;
  font-weight:600;cursor:pointer;font-size:13.5px}}
footer.bar button.ghost{{background:transparent;color:var(--dim);border:1px solid var(--line)}}
#prog{{font-size:13px;color:var(--dim)}}
#prog b{{color:var(--fg)}}
</style></head><body>

<header class="top">
  <h1>Fine Art Archive — decisions for {e(d)}</h1>
  <div class="dim" style="font-size:13px">Every number below was measured on your Mac, not in the sandbox.
  Nothing has been quarantined, deleted, or acquired. Pick what you want; the footer writes a file I read
  next session, so nothing needs pasting.</div>
  <div class="kpis">
    <div class="kpi up"><b>{live:,}</b>works · +{len(promotions)} promotions in window</div>
    <div class="kpi"><b>{cands['by_status'].get('screened',0):,}</b>screened candidates</div>
    <div class="kpi warn"><b>{ung['total']}</b>works lacking a grant</div>
    <div class="kpi warn"><b>{len(unprom)}</b>unpromoted</div>
    <div class="kpi"><b>{e(last_promotion_date or 'none')}</b>latest promotion</div>
  </div>
  <nav id="nav">
    {nav_html}
  </nav>
</header>

<main>{body}</main>

<footer class="bar">
  <span id="prog"><b>0</b> of {decision_total} decided</span>
  <button onclick="dl()">Download decisions file</button>
  <button class="ghost" onclick="cp()">Copy to clipboard</button>
  <button class="ghost" onclick="reset()">Clear</button>
  <span class="dim" style="font-size:12px">Saves as you go. Download drops
  <code>weekly_decisions_{e(d)}.json</code> in Downloads — tell me it is there and I read it.</span>
</footer>

<script>
const DATE="{e(d)}", KEY="faa_decisions_"+DATE, IDS={ids_json};
let S=JSON.parse(localStorage.getItem(KEY)||'{{"decisions":{{}},"candidates":{{}},"unpromoted":{{}},"flags":[]}}');
function save(){{localStorage.setItem(KEY,JSON.stringify(S));prog();}}
function prog(){{
  let n=IDS.filter(i=>S.decisions[i]&&S.decisions[i].verdict).length;
  document.getElementById("prog").innerHTML="<b>"+n+"</b> of "+IDS.length+" decided";
  IDS.forEach(i=>{{
    const b=document.getElementById("badge_"+i), a=document.getElementById("nav_"+i);
    const v=S.decisions[i]&&S.decisions[i].verdict;
    if(b){{b.textContent=v?v:"undecided";b.className="badge"+(v?" set":"");}}
    if(a)a.className=v?"done":"";
  }});
}}
function setD(id,v){{S.decisions[id]=S.decisions[id]||{{}};S.decisions[id].verdict=v;save();}}
function setN(id,v){{S.decisions[id]=S.decisions[id]||{{}};S.decisions[id].note=v;save();}}
function pick(q,v,btn){{
  S.candidates[q]=v;btn.parentNode.querySelectorAll("button").forEach(b=>b.classList.remove("on"));
  btn.classList.add("on");const f=document.getElementById("c_"+q);
  f.className="cand "+v;save();
}}
function pickU(w,v,btn){{
  S.unpromoted[w]=v;btn.parentNode.querySelectorAll("button").forEach(b=>b.classList.remove("on"));
  btn.classList.add("on");save();
}}
function flag(w,on){{
  S.flags=S.flags.filter(x=>x!==w); if(on)S.flags.push(w); save();
}}
function payload(){{
  return JSON.stringify({{generated:DATE,decided_at:new Date().toISOString(),
    decisions:S.decisions,candidate_picks:S.candidates,unpromoted_picks:S.unpromoted,
    flagged_works:S.flags}},null,2);
}}
function dl(){{
  const b=new Blob([payload()],{{type:"application/json"}}),u=URL.createObjectURL(b),
    a=document.createElement("a");a.href=u;a.download="weekly_decisions_"+DATE+".json";a.click();
  URL.revokeObjectURL(u);
}}
function cp(){{navigator.clipboard.writeText(payload()).then(()=>alert("Copied."));}}
function reset(){{if(confirm("Clear all picks?")){{localStorage.removeItem(KEY);location.reload();}}}}
// restore
window.addEventListener("DOMContentLoaded",()=>{{
  for(const id in S.decisions){{
    const v=S.decisions[id].verdict;
    if(v){{const r=document.querySelector('input[name="d_'+id+'"][value="'+CSS.escape(v)+'"]');if(r)r.checked=true;}}
    const n=document.getElementById("n_"+id); if(n&&S.decisions[id].note)n.value=S.decisions[id].note;
  }}
  for(const q in S.candidates){{
    const f=document.getElementById("c_"+q); if(!f)continue; f.className="cand "+S.candidates[q];
    f.querySelectorAll(".pick button").forEach(b=>{{if(b.textContent.trim()===S.candidates[q])b.classList.add("on");}});
  }}
  (S.flags||[]).forEach(w=>{{}});
  prog();
}});
</script>
</body></html>"""

    out = REPORTS / f"weekly_review_{d}.html"
    out.write_text(doc)
    print(f"wrote {out} ({len(doc):,} bytes)")

    if serve_root is not None:
        served_doc = doc.replace(f"thumbs_{d}/", "thumbs/")
        (serve_root / "index.html").write_text(served_doc)
        print(f"wrote {serve_root / 'index.html'} — serve with:")
        print(f"  cd '{serve_root}' && /Users/teacher/.faa-venv/bin/python3 "
              f"-m http.server 8792 --bind 127.0.0.1")
        print("  open -a 'Google Chrome' http://127.0.0.1:8792/")


if __name__ == "__main__":
    main()
