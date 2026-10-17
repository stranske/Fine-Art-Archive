# Artist resolution follow-up mutation proofs

Each collected case was run against the stated source mutation, failed with exit 1,
and passed with exit 0 after restoring the original source bytes. Full commands,
mutations and outputs are in [artist-mutation-proofs.json.gz](artist-mutation-proofs.json.gz).

| Case in `tests/test_source_resolver_artist_recovery.py` | Deliberate defect | Broken | Restored |
|---|---|---|---|
| `test_unconfirmed_alias_uses_getty_bridge_and_museum_name[low-confidence]` | Accept an alias below the confidence threshold | 1 failed | 1 passed |
| `test_unconfirmed_alias_uses_getty_bridge_and_museum_name[no-qid]` | Accept a local alias result without a QID | 1 failed | 1 passed |
| `test_unusable_getty_result_still_searches_museum_creator[absent]` | Stop resolution when Getty returns no result | 1 failed | 1 passed |
| `test_unusable_getty_result_still_searches_museum_creator[invalid-ulan]` | Pass an invalid ULAN through without normalization | 1 failed | 1 passed |
| `test_getty_identity_without_wikidata_cannot_supply_a_qid` | Remove the guard for an absent Wikidata provider | 1 failed | 1 passed |
| `test_museum_artist_wikidata_url_supplies_identity_without_search` | Ignore a Wikidata link embedded in the museum creator text | 1 failed | 1 passed |
