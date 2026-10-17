All 65 cases failed with the listed temporary defect (exit 1) and passed after restoration (exit 0).

Each row is an executed, individually selected pytest invocation. Exact mutations, commands, and outputs are in `mutation-proofs.json.gz`.

| Test | Mutated function | Broken / restored |
|---|---|---|
| `tests/test_api_delivery_boundaries.py::test_impossible_quarantine_date_is_reported_without_a_ttl` | `_quarantine_report` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_work_response_attaches_latest_rating_without_mutating_sidecar` | `get_work` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_blank_export_path_is_a_client_error` | `_checked_export_dir` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_invalid_work_id_has_no_eink_master` | `_eink_master` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_facets_include_live_mood_counts` | `eink_facets` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_invalid_delivery_configuration_is_a_client_error[preview-spec]` | `eink_playlist_preview` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_invalid_delivery_configuration_is_a_client_error[export-spec]` | `eink_playlist_export` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_invalid_delivery_configuration_is_a_client_error[export-target]` | `eink_playlist_export` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_invalid_delivery_configuration_is_a_client_error[export-dither]` | `eink_playlist_export` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_export_plan_omits_render_evidence_for_missing_master` | `eink_playlist_export` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_review_lists_reject_nonpositive_limits[acquisitions]` | `list_acquisitions` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_review_lists_reject_nonpositive_limits[works]` | `review_works` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_review_lists_reject_nonpositive_limits[artists]` | `review_artists` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_review_lists_reject_nonpositive_limits[gate]` | `review_gate` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_work_decision_rejects_invalid_qid_before_writing` | `work_decision` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_acquisition_review_refuses_invalid_sidecar_without_writing` | `acquisition_review` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_review_artists_skips_unattributed_work_and_recovers_later_label` | `review_artists` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_gate_lookup_returns_limited_items_or_404[held]` | `review_gate` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_gate_lookup_returns_limited_items_or_404[absent]` | `review_gate` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_saved_feed_reports_render_failures_with_playlist_context[missing-404]` | `_render_feed_image` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_saved_feed_reports_render_failures_with_playlist_context[target-404]` | `_render_feed_image` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_saved_feed_reports_render_failures_with_playlist_context[fit-400]` | `_render_feed_image` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_saved_feed_reports_render_failures_with_playlist_context[pixels-500]` | `_render_feed_image` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_delete_playlist_changes_store_and_reports_missing[True]` | `eink_delete_playlist` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_delete_playlist_changes_store_and_reports_missing[False]` | `eink_delete_playlist` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_debug_log_invalid_body_is_422[not json]` | `_parse_debug_log_body` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_debug_log_invalid_body_is_422[[]]` | `_parse_debug_log_body` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_debug_log_invalid_body_is_422[{"event": 1}]` | `_parse_debug_log_body` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_recent_ratings_are_newest_first_and_limited` | `recent_ratings` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_candidate_proxy_converts_rgba_to_resized_jpeg` | `review_candidate_image` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_targets_publish_supported_device_and_export_roots` | `eink_targets` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_acquisition_review_rejects_invalid_id` | `acquisition_review` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_rating_rejects_unknown_legacy_reason_before_append` | `rate_work` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_queue_signature_records_disappearing_file` | `_queue_files_with_signature` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_queue_file_error_message_omits_host_paths[error0-permission denied]` | `_safe_queue_file_message` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_queue_file_error_message_omits_host_paths[error1-OSError]` | `_safe_queue_file_message` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_debug_rotation_replaces_previous_backup` | `debug_log` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_variant_candidate_without_matching_row_has_no_local_path` | `_variant_candidate_path` | 1 / 0 |
| `tests/test_api_delivery_boundaries.py::test_variant_decision_with_nonstring_identity_does_not_mask_valid_decision` | `variant_upgrades` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_invalid_facts_cache_shape_is_recoverable[raw0]` | `_load_master_facts` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_invalid_facts_cache_shape_is_recoverable[raw1]` | `_load_master_facts` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_invalid_facts_cache_shape_is_recoverable[raw2]` | `_load_master_facts` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_invalid_and_unchecked_facts_do_not_discard_healthy_neighbor` | `_load_master_facts` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_failed_cache_flush_preserves_existing_file` | `flush_master_facts` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_full_facts_cache_evicts_old_entries_and_keeps_current_master` | `_master_facts` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_unreadable_image_has_unknown_dimensions` | `_image_pixels` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_invalid_work_id_has_unchecked_health` | `master_health` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_symlinked_work_cannot_escape_archive` | `contained_work_path` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_unreadable_dossier_sidecar_does_not_hide_healthy_work` | `work_ids_with_dossier` | 1 / 0 |
| `tests/test_api_store_recovery.py::test_corrupt_sidecar_does_not_hide_acquisitions_or_artist_identities` | `acquisitions_since_epoch` | 1 / 0 |
| `tests/test_source_resolver_artist_recovery.py::test_museum_artist_direct_qid_needs_no_name_or_lookup` | `ArtistQidResolver.resolve` | 1 / 0 |
| `tests/test_source_resolver_artist_recovery.py::test_museum_artist_uses_confident_local_alias_before_getty` | `ArtistQidResolver.resolve` | 1 / 0 |
| `tests/test_source_resolver_artist_recovery.py::test_getty_outage_falls_back_to_named_wikidata_search[recovered]` | `ArtistQidResolver.resolve` | 1 / 0 |
| `tests/test_source_resolver_artist_recovery.py::test_getty_outage_falls_back_to_named_wikidata_search[absent]` | `ArtistQidResolver.resolve` | 1 / 0 |
| `tests/test_source_resolver_artist_recovery.py::test_artist_without_any_name_remains_unresolved_without_search` | `ArtistQidResolver.resolve` | 1 / 0 |
| `tests/test_companion_app_api.py::test_static_assets_report_missing_files_instead_of_serving_stale_paths` | `root` | 1 / 0 |
| `tests/test_companion_app_api.py::test_quarantine_report_distinguishes_expired_invalid_and_ttl_less_directories` | `_quarantine_report` | 1 / 0 |
| `tests/test_companion_app_api.py::test_build_eink_playlist_derives_only_missing_preference_evidence` | `_build_eink_playlist` | 1 / 0 |
| `tests/test_companion_app_api.py::test_active_research_requests_ignores_expired_and_malformed_records` | `_active_research_requests` | 1 / 0 |
| `tests/test_companion_app_api.py::test_eink_playlist_preview_returns_selected_items_without_masters` | `eink_playlist_preview` | 1 / 0 |
| `tests/test_companion_app_api.py::test_eink_preview_renders_a_local_master` | `eink_preview` | 1 / 0 |
| `tests/test_discovery.py::test_transport_helpers_normalize_payloads_and_upstream_failures` | `_head_size` | 1 / 0 |
| `tests/test_discovery.py::test_claim_values_skips_malformed_claims_and_retains_scalar_amount_and_id` | `claim_values` | 1 / 0 |
| `tests/test_discovery.py::test_resolvers_keep_partial_discovery_when_optional_metadata_is_missing_or_broken` | `discover_candidates` | 1 / 0 |
| `tests/test_discovery.py::test_discovery_main_writes_output_and_prints_a_bounded_preview` | `main` | 1 / 0 |
