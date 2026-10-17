# Claim-label mutation proofs

Each new case failed with exit 1 under its deliberate defect and passed with exit 0 after byte-for-byte source restoration. Exact source replacements, commands, and complete outputs are in [claim-label-mutations.json.gz](claim-label-mutations.json.gz).

| Case in `tests/test_source_resolver_claim_labels.py` | Deliberate defect | Broken / restored |
|---|---|---|
| `test_literal_medium_claims_are_trimmed_and_keep_source_order` | Preserve whitespace in literal medium claims | 1 failed / 1 passed |
| `test_blank_and_nontext_medium_claims_supply_no_candidate` | Accept blank literal claims as medium text | 1 failed / 1 passed |
| `test_medium_labels_skip_unusable_entities_and_deduplicate_in_claim_order` | Keep duplicate medium labels | 1 failed / 1 passed |
| `test_entities_without_usable_labels_do_not_invent_a_medium` | Invent a medium when none of the entities has a usable label | 1 failed / 1 passed |
| `test_missing_work_entity_is_unchecked_even_if_it_contains_claims` | Accept an entity explicitly marked missing | 1 failed / 1 passed |
| `test_failed_work_lookup_is_unchecked` | Treat a failed entity lookup as a successful empty response | 1 failed / 1 passed |
| `test_work_without_a_qid_is_unchecked_without_querying_wikidata` | Treat an absent work identity as a confirmed absence | 1 failed / 1 passed |
| `test_failed_label_lookup_leaves_field_researchable[medium-P186-wikidata]` | Treat a failed wikidata medium label request as a confirmed absence | 1 failed / 1 passed |
| `test_failed_label_lookup_leaves_field_researchable[medium-P186-commons]` | Treat a failed commons medium label request as a confirmed absence | 1 failed / 1 passed |
| `test_failed_label_lookup_leaves_field_researchable[category-P136-wikidata]` | Treat a failed wikidata category label request as a confirmed absence | 1 failed / 1 passed |
| `test_failed_label_lookup_leaves_field_researchable[category-P136-commons]` | Treat a failed commons category label request as a confirmed absence | 1 failed / 1 passed |
