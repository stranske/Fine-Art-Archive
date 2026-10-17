Malformed master-facts caches whose `entries` value is a list or null now count as cache misses. Previously those shapes raised `AttributeError` during acquisition review. Two regression cases reproduced the failure before the small cache-shape guard was added; this is the only production change.

The PR adds **71 offline cases** for API delivery and review gates, cache recovery, discovery, and museum artist resolution. The latest six cases check low-confidence and QID-less aliases, Getty-to-Wikidata bridging, absent/invalid Getty results, an unavailable Wikidata provider, and a Wikidata link embedded in museum creator text. No additional production bug was found.

Targets follow [the repository ranking](https://github.com/stranske/Fine-Art-Archive/blob/codex/issue-810-api-discovery-coverage/docs/evidence/issue-799-coverage/review-gap-ranking.csv): API main, API store, then source resolver. Repair-history matches are a proxy, not a verified escaped-defect count. Fresh history counts preserve that order: 28/57, 6/21, and 5/9 repair matches/touches respectively. This follow-up continues the already selected resolver target in the same logical PR.

### Coverage

The supplied CI baseline is **89.64%**. The original starting-head whole-suite baseline was **89.9790326%**, below the 90% stop threshold despite displaying as 90% in the rounded table. This continuation does not open a new PR. Matched local whole-suite coverage now rises **89.9790% → 91.0234%**, covering **141 previously missing target statements and branches**. CI's numbers remain authoritative for Gate acceptance.

| Target | Original local missing statements + branches | Latest local missing statements + branches | Reduction | Latest cover |
|---|---:|---:|---:|---:|
| `api/main.py` | 63 + 35 | 3 + 10 | 85 | 99.29% |
| `api/store.py` | 20 + 6 | 0 + 1 | 25 | 99.82% |
| `enrichment/source_resolver.py` | 95 + 88 | 78 + 74 | 31 | 86.52% |

The published whole-CI ranking has 111, 26, and 183 missing units for these targets. The matched local reduction above uses the original baseline reports retained in this PR, rather than crediting inherited tests twice. The cache fix's three new statements and two new branches are fully covered and excluded from the count of formerly uncovered units.

The immediately preceding head `1472a49576c01baf4ec466295093cd153b44715c` has a [successful Gate run](https://github.com/stranske/Fine-Art-Archive/actions/runs/38987800809), including Python 3.12 and 3.13, Black and Ruff. Its Python 3.12 job reports **2394 passed, 12 skipped** and **91.02%**. [The CI receipt](parent-ci.json) records its target rows and exact checks. That success validates the previous 65 cases and cache fix; fresh CI for this six-case follow-up remains pending.

The latest six cases reduce resolver missing units **158 → 152** in matched whole-suite runs. Targeted verification: **194 passed in 3.82s**; the resolver row is **86.52%**. The resolver is not claimed fully covered. The remaining API lines are Pydantic v1 compatibility fallbacks and the zero-attempt retry fallback; this chunk does not synthesize unsupported runtime conditions to cover them. The original ~120-unit chunk is already exceeded.

### Executed mutation proofs

All **71 PR-added cases** individually fail with a deliberate production defect (exit 1) and pass after exact source restoration (exit 0). [The original 65-case index](mutation-summary.md) links to the original full receipts. [The six new cases](artist-mutation-summary.md) have separate [exact mutations, commands and complete outputs](artist-mutation-proofs.json.gz). The two cache regressions' failure before the fix is retained in [cache-bug-before-fix.txt.gz](cache-bug-before-fix.txt.gz).

| New case | Deliberate defect | Broken | Restored |
|---|---|---|---|
| Low-confidence alias | Accept an alias below the threshold | 1 failed | 1 passed |
| Alias without QID | Accept an alias with no QID | 1 failed | 1 passed |
| Getty absence | Stop resolution on no Getty result | 1 failed | 1 passed |
| Invalid Getty ULAN | Pass the unnormalized ULAN to Wikidata | 1 failed | 1 passed |
| Wikidata unavailable | Remove the provider guard | 1 failed | 1 passed |
| Embedded artist link | Ignore the museum's Wikidata link | 1 failed | 1 passed |

### Validation and task reconciliation

Fresh local baseline: **4 failed, 2390 passed, 12 skipped, 1 warning in 160.05s (0:02:40)**. Latest full suite: **4 failed, 2396 passed, 12 skipped, 1 warning in 155.44s (0:02:35)**. Both have exactly the same four `test_workspace_conflict_guard.py` failures because the default `/home/runner/.cache/fine-art-archive` directory is read-only; no tests were disabled. CI passes those tests at the preceding head. The external selector-polling harness from prior rounds and one Black worker are required by this sandbox; they change no repository code or tests.

- [x] Select targets in repository ranking order, rather than by file size.
- [x] Execute a failing mutation and passing restoration for every new test; 71/71 cases have receipts.
- [x] Fix real bugs minimally: only the malformed-cache shape guard is retained. The existing negative-cache regression also passes in the targeted suite.
- [x] Keep low blast radius: tests and the targeted cache fix, with no refactors.
- [x] Keep one PR for this logical API/enrichment coverage chunk.
- [x] Verify the preceding committed head's Gate, Python 3.12/3.13 tests and lint checks.
- [ ] Verify fresh Gate on the commit containing the latest six cases. Local checks do not replace it.

Applied Black to the changed Python file. Required whole-tree Black, CI whole-tree Black, CI whole-tree Ruff, and `git diff --check` pass. Exact commands, coverage summaries and hashes are in [artist-followup.json](artist-followup.json); [the latest full-suite coverage](artist-followup-coverage.json.gz) and [pytest output](artist-followup-pytest.txt.gz) are retained alongside the targeted reports.

The checkout's Git metadata is read-only, so staging into its branch fails creating `.git/index.lock`. A separate bare clone under `/tmp` preserves a handoff commit and bundle without changing the checkout's branch. Publishing that commit and running fresh CI remain outstanding. The GitHub connector rejected the live PR title/body and task-checkbox update: `MCP tool call requires approval, but approval policy is never`. The verified checklist above is the prepared local reconciliation. PR #813 was confirmed open with `isDraft=false`; no additional PR was opened.

Closes #810
