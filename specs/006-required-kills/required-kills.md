# Required kills per invariant

Each entry is a deliberately wrong change to the server code that the test suite must fail on. See
[spec.md](./spec.md) for what that means, who owns the list and the rules for changing it. This is the
agent's draft; the owner has not yet reviewed it item by item.

**class**: `must` flips a must-transition (safety, paywall, completeness); `should` makes the service worse or
less faithful without being unsafe; `may` changes only speed or order. **killed by** is the first test that fails
on the entry's change when the whole suite runs; each was re-run alone against the change and still fails. An
id with `S` is a second-order entry: two redundant layers removed together.

## Tally

| invariant | entries | killed | survive by design |
|---|---|---|---|
| G1 Scope: nothing outside kb is ever listed or read (Art. I, VII; AC-FR-025) | 29 | 22 | 7 |
| G2 Read-only: no write path to Drive (Art. V) | 14 | 14 | 0 |
| G3 Authentication: every drive_* call needs a valid access token (Art. VII) | 12 | 12 | 0 |
| G4 Paywall: no token, code or cookie without an active subscription; fails closed | 31 | 31 | 0 |
| G5 Completeness is visible: PARTIAL vs EMPTY, never silent (Art. X) | 26 | 24 | 2 |
| G6 Exactness and determinism: literal means literal; same order every time (Art. IX) | 13 | 11 | 2 |
| G7 Ephemerality, freshness, isolation: nothing kept, nothing shared between calls (Art. I, III) | 7 | 7 | 0 |
| G8 Provenance and citation: one cite line, no locator in results (Art. VIII) | 13 | 13 | 0 |
| G9 Failure taxonomy: classified, and no existence oracle (Art. XI) | 7 | 7 | 0 |
| G10 Secrets and logs: no token, no document text in logs (Art. VII, XI) | 7 | 7 | 0 |
| G11 Abuse limits: the per-call ceilings against bulk extraction | 21 | 21 | 0 |
| G12 Documents are data, not instructions (Art. VI) | 3 | 3 | 0 |
| G13 Speed: the three engineering invariants from the latency fixes | 6 | 6 | 0 |
| G14 OAuth and identity surface: no SSRF, no code theft, no account takeover (Art. VII) | 23 | 23 | 0 |
| **all** | **212** | **201** | **11** |

## G1. Scope: nothing outside kb is ever listed or read (Art. I, VII; AC-FR-025)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G1-01 | must | is_inside_tree falls through to True: any id the lookup returns is allowed [POSITIVE CONTROL] | `test_allowed_folder.py::test_read_outside_allowed_folder_is_authorization_error` |
| G1-02 | must | membership check dropped: an id Drive knows is allowed wherever it lives | `test_allowed_folder.py::test_read_outside_allowed_folder_is_authorization_error` |
| G1-03 | must | a named folder_id is not checked at all (only file ids are) | `test_allowed_folder.py::test_ls_unrelated_folder_is_authorization_error` |
| G1-04 | must | a missing id raises FILE_NOT_FOUND instead of the refusal (existence oracle) | `test_allowed_folder.py::test_outside_missing_and_ungranted_ids_take_the_same_drive_calls` |
| G1-05 | must | the lookups stop at the first refusal (call count and timing reveal which id failed) | `test_one_metadata_get_per_id.py::test_the_access_check_looks_the_ids_up_side_by_side` |
| G1-06 | must | no allow-list configured no longer refuses | `test_allowed_folder.py::test_unset_allow_list_refuses_every_call_without_drive_io` |
| G1-07 | must | omitted folder is widened to the Drive root instead of kb | `test_allowed_folder.py::test_omitted_ls_lists_allowed_folder_not_root` |
| G1-08 | must | omitted folder is no longer narrowed to kb (all three rewrite layers go with it) | `test_allowed_folder.py::test_omitted_ls_lists_allowed_folder_not_root` |
| G1-09 | must | rewrite layer 1 only (handle_tool) | **survives by design**: equivalent while the other argument-rewriting layer holds; both together are killed (G1-S1) |
| G1-10 | must | rewrite layer 2 only (middleware.authorize) | **survives by design**: equivalent while the other argument-rewriting layer holds; both together are killed (G1-S1) |
| G1-11 | must | rewrite layer 3 only (evaluate_chain) | **survives by design**: equivalent: the chain's own rewrite only feeds its decision, and the arguments arrive already rewritten |
| G1-12 | must | all three rewrite layers removed | `test_allowed_folder.py::test_omitted_ls_lists_allowed_folder_not_root` |
| G1-13 | must | whole-grant refusal removed (only the last of five layers against an unscoped call) | **survives by design**: unreachable while any rewrite layer holds: the folder is always set before this check |
| G1-14 | should | tree listing skipped: nested folders refused | `test_allowed_folder.py::test_outside_folders_cannot_even_be_listed` |
| G1-15 | should | ancestor walk stops following the tree: nested files refused | `test_allowed_folder.py::test_deep_file_inside_allowed_folder_is_still_readable` |
| G1-16 | must | tree builder trusts a lister that returns folders not under the frontier | `test_scope_backstops.py::test_the_folder_tree_leaves_out_a_folder_that_is_not_under_the_frontier` |
| G1-17 | should | file_ids inside the named folder check removed (file_outside_folder) | `test_auth_contract.py::test_folder_and_granted_file_outside_folder_is_authorization_error` |
| G1-18 | should | walker scope check removed for named files | **survives by design**: equivalent: the chain checks the same membership first |
| G1-19 | must | a listing is no longer filtered to real children (stale or over-broad index entry) | `test_allowed_folder.py::test_stale_listing_entry_outside_the_folder_is_dropped` |
| G1-20 | should | trashed files are listed and searched | `test_scope_backstops.py::test_a_trashed_file_the_listing_returned_anyway_is_not_searched` |
| G1-21 | should | whitespace-only file id counts as a named file (skips the kb rewrite) | `test_allowed_folder.py::test_blank_file_ids_do_not_skip_the_allow_list_rewrite` |
| G1-22 | should | an explicitly named subfolder is replaced by kb root | `test_allowed_folder.py::test_ls_unrelated_folder_is_authorization_error` |
| G1-23 | must | startup accepts a Drive root as the allow-list | `test_allowed_folder.py::test_startup_drive_check_refuses_anything_but_one_folder` |
| G1-24 | must | startup accepts a non-folder as the allow-list | `test_allowed_folder.py::test_startup_drive_check_refuses_anything_but_one_folder` |
| G1-25 | must | server starts with no allow-list configured | `test_scope_backstops.py::test_startup_says_what_to_set_when_the_allow_list_is_missing_or_an_alias` |
| G1-26 | must | startup accepts alias 'root' as the allow-list | `test_allowed_folder.py::test_startup_requires_one_real_allow_list_folder` |
| G1-S1 | must | second order: the two layers that rewrite the tool's own arguments removed together | `test_allowed_folder.py::test_omitted_ls_lists_allowed_folder_not_root` |
| G1-S2 | must | second order: rewrite layers 2 and 3 removed together (layer 1 still rewrites the arguments) | **survives by design**: one argument-rewriting layer still holds |
| G1-S3 | must | second order: rewrite layers 1 and 3 removed together (layer 2 still rewrites the arguments) | **survives by design**: one argument-rewriting layer still holds |

## G2. Read-only: no write path to Drive (Art. V)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G2-01 | must | Google scope widened from drive.readonly to drive | `test_request_isolation.py::test_overlapping_mints_are_distinct_objects` |
| G2-02 | must | a files().delete( method appears | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-03 | must | a files().update( method appears (trash/rename) | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-04 | must | a files().create( method appears | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-05 | must | a permissions().create( method appears (share) | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-06 | must | a files().copy( method appears | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-07 | must | a files().emptyTrash( method appears | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-08 | must | a comments().create( method appears | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-09 | must | a revisions().delete( method appears | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-10 | must | a raw HTTP DELETE to the Drive API appears | `test_drive_calls_are_read_only.py::test_the_adapter_makes_no_raw_http_writes` |
| G2-11 | must | a drives().create( method appears | `test_drive_calls_are_read_only.py::test_the_adapter_calls_only_read_endpoints` |
| G2-12 | must | tool advertises readOnlyHint=False | `test_tool_schemas.py::test_tools_list_is_exactly_the_read_only_surface` |
| G2-13 | must | tool advertises destructiveHint=True | `test_tool_schemas.py::test_tools_list_is_exactly_the_read_only_surface` |
| G2-14 | must | a fifth tool name (drive_delete) joins the read-only tool set | `test_tool_schemas.py::test_tools_list_is_exactly_the_read_only_surface` |

## G3. Authentication: every drive_* call needs a valid access token (Art. VII)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G3-01 | must | token type not checked (a refresh or code token works as an access token) | `test_token_claims.py::test_a_token_with_one_wrong_claim_is_refused` |
| G3-02 | must | issuer not checked | `test_token_claims.py::test_a_token_with_one_wrong_claim_is_refused` |
| G3-03 | must | audience not checked (a token for another resource works) | `test_token_claims.py::test_a_token_with_one_wrong_claim_is_refused` |
| G3-04 | must | expiry not checked | `test_subscription_cancel.py::test_cancel_at_period_end_ends_tool_access_after_the_paid_period` |
| G3-05 | must | scope not checked | `test_token_claims.py::test_a_token_with_one_wrong_claim_is_refused` |
| G3-06 | must | signature not compared (any well-formed token passes) | `test_oauth_limits.py::test_tampered_client_id_is_invalid_client` |
| G3-07 | must | JWT alg header not checked | `test_token_claims.py::test_a_header_that_names_another_algorithm_is_refused_even_with_a_valid_signature` |
| G3-08 | must | chain no longer verifies the caller | `test_chain.py::test_authn_failure_never_calls_google` |
| G3-09 | must | handle_tool no longer verifies the caller | `test_token_claims.py::test_authentication_comes_before_argument_validation` |
| G3-10 | must | authentication removed in both layers | `test_auth_contract.py::test_missing_bearer_is_authentication_error_and_no_drive_io` |
| G3-11 | must | Google credentials are minted before the caller is authenticated | `test_chain.py::test_no_allow_list_refuses_before_google` |
| G3-12 | must | consent password: an unset (empty) secret accepts an empty answer | `test_token_claims.py::test_an_empty_consent_password_never_matches` |

## G4. Paywall: no token, code or cookie without an active subscription; fails closed

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G4-01 | must | canceled counts as entitled | `test_subscription_cancel.py::test_cancel_at_period_end_ends_tool_access_after_the_paid_period` |
| G4-02 | must | past_due counts as entitled | `test_subscription_cancel.py::test_failed_renewal_ends_refresh` |
| G4-03 | must | billing outage fails open (is_subscription_active) | `test_stripe_gateway_edges.py::test_a_check_stripe_cannot_answer_is_not_active` |
| G4-04 | must | billing outage fails open (provider._active) | `test_subscription_cancel.py::test_stripe_outage_fails_closed` |
| G4-05 | must | authorize issues a code without checking the subscription | `test_subscription_cancel.py::test_cancel_at_period_end_ends_tool_access_after_the_paid_period` |
| G4-06 | must | code exchange does not refuse an inactive subscription | `test_subscription_http.py::test_paid_connect_counts_once_and_a_lapsed_exchange_counts_nothing` |
| G4-07 | must | code with no customer id counts as subscribed | `test_token_lifecycle.py::test_a_code_from_before_the_paywall_has_no_customer_and_is_refused` |
| G4-08 | must | refresh does not refuse a lapsed subscription | `test_subscription_cancel.py::test_cancel_at_period_end_ends_tool_access_after_the_paid_period` |
| G4-09 | must | refresh token with no customer id counts as subscribed | `test_token_lifecycle.py::test_a_refresh_token_from_before_the_paywall_is_refused` |
| G4-10 | should | a Stripe outage reads as 'subscription inactive' (permanent) instead of 'unavailable' (retry) | `test_subscription_cancel.py::test_stripe_outage_fails_closed` |
| G4-11 | should | a failed refresh keeps the refresh token spent (subscriber locked out by a Stripe blip) | `test_subscription_cancel.py::test_stripe_outage_fails_closed` |
| G4-12 | must | refresh token is not reserved before the Stripe check (two refreshes can both succeed) | `test_subscription_cancel.py::test_a_stripe_blip_during_refresh_is_retried` |
| G4-13 | must | authorization code can be used twice (jti never recorded) | `test_token_lifecycle.py::test_an_authorization_code_works_once` |
| G4-14 | must | authorization code replay check removed | `test_token_lifecycle.py::test_an_authorization_code_works_once` |
| G4-15 | must | revoked access token is still accepted | `test_token_lifecycle.py::test_a_revoked_access_token_is_no_longer_accepted` |
| G4-16 | should | refresh re-issue drops the customer id (next refresh cannot check the subscription) | `test_token_lifecycle.py::test_a_refreshed_token_can_be_refreshed_again` |
| G4-17 | must | Checkout session need not be complete | `test_stripe_gateway_edges.py::test_a_checkout_session_grants_access_only_when_complete_paid_and_ours` |
| G4-18 | must | unpaid Checkout session grants access | `test_duplicate_checkout.py::test_unpaid_or_incomplete_checkout_grants_nothing` |
| G4-19 | must | Checkout success link works for anyone (reference binding dropped) | `test_duplicate_checkout.py::test_checkout_with_a_subscribers_email_never_switches_customers` |
| G4-20 | must | Stripe webhook signature not compared | `test_subscription_http.py::test_verify_stripe_signature_unit` |
| G4-21 | must | Stripe webhook accepted when no signing secret is set | `test_webhook_signature_edges.py::test_a_signature_made_with_an_empty_key_is_never_accepted` |
| G4-22 | must | Stripe webhook replay window removed | `test_webhook_signature_edges.py::test_a_captured_event_cannot_be_replayed_later` |
| G4-23 | must | entitlement cookie: type not checked | `test_entitlement_cookie.py::test_a_cookie_with_one_wrong_claim_is_not_an_entitlement` |
| G4-24 | must | entitlement cookie: audience not checked | `test_entitlement_cookie.py::test_a_cookie_with_one_wrong_claim_is_not_an_entitlement` |
| G4-25 | must | entitlement cookie: expiry not checked | `test_entitlement_cookie.py::test_a_cookie_with_one_wrong_claim_is_not_an_entitlement` |
| G4-26 | should | entitlement cookie: customer id shape not checked | `test_entitlement_cookie.py::test_a_cookie_with_one_wrong_claim_is_not_an_entitlement` |
| G4-27 | must | entitlement cookie is trusted without verifying it | `test_oauth_limits.py::test_consent_ticket_does_not_carry_the_customer_id` |
| G4-28 | must | unsubscribed browser is not sent to /subscribe | `test_oauth_surface.py::test_the_cookies_the_server_sets_cannot_be_read_by_scripts` |
| G4-29 | should | entitlement cookie loses HttpOnly | `test_entitlement_cookie.py::test_the_cookie_cannot_be_read_by_scripts` |
| G4-30 | must | deploy script no longer sets MCP_SUBSCRIPTION_REQUIRED | `test_deploy_paywall_switch.py::test_the_deploy_carries_the_paywall_switch_and_the_kb_pin` |
| G4-31 | must | deploy script deploys without the paywall secrets instead of refusing | `test_deploy_paywall_switch.py::test_a_missing_stripe_secret_stops_the_deploy_before_it_starts` |

## G5. Completeness is visible: PARTIAL vs EMPTY, never silent (Art. X)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G5-01 | must | grep: files set aside for the byte cap no longer make the result PARTIAL | `test_drive_grep.py::test_folder_grep_defers_file_that_does_not_fit_and_scans_small_first` |
| G5-02 | must | grep: stopping at the file cap is reported as COMPLETE/EMPTY | `test_drive_grep.py::test_max_files_on_binaries_is_partial_not_unsupported` |
| G5-03 | must | grep: stopping at the match cap is reported as COMPLETE | `test_drive_grep.py::test_max_matches_inside_a_file_returns_an_in_file_cursor` |
| G5-04 | must | grep: a rate limit is reported as COMPLETE/EMPTY | `test_drive_grep.py::test_folder_export_429_is_partial_not_envelope` |
| G5-05 | must | grep: a cut file listing (time) no longer makes the result PARTIAL | **survives by design**: dead code: a cut listing returns earlier, so walk.time_exceeded is always false at this point |
| G5-06 | must | grep: skipped unsupported files are not reported | `test_drive_grep.py::test_mixed_folder_skips_unsupported_partial` |
| G5-07 | must | grep: zero hits reports COMPLETE instead of EMPTY | `test_drive_grep.py::test_grep_missing_phrase_is_empty` |
| G5-08 | must | grep: a cut listing is scanned anyway | `test_drive_grep.py::test_continuation_with_a_cut_listing_keeps_its_cursor` |
| G5-09 | must | grep: file cap off by one | `test_drive_grep.py::test_max_files_on_binaries_is_partial_not_unsupported` |
| G5-10 | must | grep: a file that does not fit the byte budget is dropped, neither scanned nor deferred | `test_drive_grep.py::test_folder_grep_defers_file_that_does_not_fit_and_scans_small_first` |
| G5-11 | must | grep: files after byte exhaustion are dropped, not deferred | `test_grep_byte_budget.py::test_a_call_with_no_bytes_left_defers_every_searchable_file` |
| G5-12 | must | grep: more matches in the same file are not reported as PARTIAL | `test_drive_grep.py::test_max_matches_inside_a_file_returns_an_in_file_cursor` |
| G5-13 | must | grep: a stopped scan gives no next_cursor (host cannot continue) | `test_drive_grep.py::test_folder_export_429_preserves_matches_already_found` |
| G5-14 | must | grep: resuming inside a file skips the rest of that file | `test_drive_grep.py::test_max_matches_inside_a_file_returns_an_in_file_cursor` |
| G5-15 | must | grep: a single named file can be deferred (and so never read) | `test_drive_grep.py::test_single_file_id_is_not_deferred_when_larger_than_remaining_budget` |
| G5-16 | must | grep: nothing searchable (all unsupported) reads as EMPTY, not an error | `test_drive_grep.py::test_grep_binary_by_id_is_classified_error` |
| G5-17 | should | grep: wrong partial reason for the match cap | `test_drive_grep.py::test_max_matches_inside_a_file_returns_an_in_file_cursor` |
| G5-18 | must | ls: a truncated listing is reported as COMPLETE | **survives by design**: redundant: immediate_children sets truncated equal to more, so the second test never differs |
| G5-19 | must | ls: an empty folder is reported as COMPLETE | `test_ls_completeness.py::test_an_empty_folder_is_empty_not_complete` |
| G5-20 | must | ls: a rate limit is reported as COMPLETE | `test_google_error_mapping.py::test_walk_429_is_partial_not_mapped_rate_limited_envelope` |
| G5-21 | must | ls: a listing cut by time is reported as COMPLETE | `test_ls_completeness.py::test_a_listing_cut_by_the_clock_is_partial_not_complete` |
| G5-22 | must | find: hitting max_results is reported as COMPLETE | `test_drive_find.py::test_find_max_results_counts_matches_only` |
| G5-23 | must | find: a cut by time is reported as COMPLETE | `test_partial_status.py::test_max_execution_time_partial` |
| G5-24 | must | find: a rate limit is reported as COMPLETE | `test_partial_status.py::test_walk_rate_limit_is_partial_not_error_envelope` |
| G5-25 | must | read: a truncated read is reported as COMPLETE | `test_large_responses.py::test_quote_heavy_text_is_cut_to_fit_the_response_cap` |
| G5-26 | should | read: a truncated read carries no partial_reason | `test_large_responses.py::test_quote_heavy_text_is_cut_to_fit_the_response_cap` |

## G6. Exactness and determinism: literal means literal; same order every time (Art. IX)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G6-01 | must | a literal pattern is compiled as a regex (re.escape dropped) | `test_drive_grep.py::test_literal_vs_regex_and_case_flag` |
| G6-02 | must | case_sensitive=True still ignores case | `test_drive_grep.py::test_literal_vs_regex_and_case_flag` |
| G6-03 | must | regex search ignores case_sensitive=False | `test_drive_grep.py::test_regex_matches_and_continuations_equal_the_literal_search` |
| G6-04 | must | case_sensitive defaults to False | `test_drive_grep.py::test_literal_vs_regex_and_case_flag` |
| G6-05 | must | reported line number is off by one | `test_drive_grep.py::test_one_match_per_line_counts_occurrences` |
| G6-06 | must | scan order ignores depth (shallow-first lost) | `test_parallel_listing.py::test_the_shallow_first_find_and_grep_results_are_unchanged` |
| G6-07 | may | scan order has no id tie-break | **survives by design**: not a requirement: equal-sized files are ordered by name or by id, both deterministic; the contract does not say which |
| G6-08 | must | scan order not sorted at all | `test_drive_grep.py::test_folder_export_429_preserves_matches_already_found` |
| G6-09 | may | listing order left to Drive (unspecified) | `test_shallow_first_order.py::test_find_returns_the_folders_own_files_first_under_max_results` |
| G6-10 | must | a file with two parents is scanned twice | `test_each_file_is_searched_once.py::test_a_file_with_two_parents_in_kb_is_scanned_once` |
| G6-11 | must | a repeated id in file_ids is scanned twice | **survives by design**: masked by the second duplicate guard; both removed together is killed (G6-S1) |
| G6-12 | must | find name_pattern becomes case-sensitive | `test_find_name_case.py::test_name_pattern_ignores_case` |
| G6-S1 | must | second order: both duplicate guards removed (two-parent scan and repeated file_ids) | `test_drive_grep.py::test_repeated_file_ids_are_scanned_once_and_cursors_finish` |

## G7. Ephemerality, freshness, isolation: nothing kept, nothing shared between calls (Art. I, III)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G7-01 | must | the metadata memo is shared by every call (stale across requests) | `test_one_metadata_get_per_id.py::test_the_memo_lasts_one_call` |
| G7-02 | should | the memo hands out its own dict (a caller can change what others see) | `test_one_metadata_get_per_id.py::test_the_memo_asks_the_wrapped_drive_once_and_hands_out_copies` |
| G7-03 | must | drive_read keeps the first text it saw per file id (stale after an edit) | `test_freshness.py::test_reread_sees_updated_fixture` |
| G7-04 | must | drive_read writes the document text to disk | `test_nothing_written_to_disk.py::test_the_four_tools_write_no_file` |
| G7-05 | must | a request's Drive binding is not cleared at the start of the next request | `test_request_binding_reset.py::test_a_request_does_not_inherit_the_previous_requests_drive` |
| G7-06 | must | Google credentials are minted once and shared by every request | `test_request_isolation.py::test_overlapping_mints_are_distinct_objects` |
| G7-07 | must | Google credentials mint skipped by reusing the previous request's binding | `test_allowed_folder.py::test_outside_folders_cannot_even_be_listed` |

## G8. Provenance and citation: one cite line, no locator in results (Art. VIII)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G8-01 | must | the citation rule is dropped from every tool description | `test_tool_schemas.py::test_answers_cite_onto_kb_in_one_line_only` |
| G8-02 | must | the cited line says something else (tool descriptions) | `test_tool_schemas.py::test_answers_cite_onto_kb_in_one_line_only` |
| G8-03 | must | the cited line says something else (initialize instructions) | `test_tool_schemas.py::test_answers_cite_onto_kb_in_one_line_only` |
| G8-04 | must | 'no Sources or References section' dropped from the instructions | `test_tool_schemas.py::test_answers_cite_onto_kb_in_one_line_only` |
| G8-05 | must | 'no Sources section, no file names or ids' dropped from every tool description | `test_tool_schemas.py::test_answers_cite_onto_kb_in_one_line_only` |
| G8-06 | must | grep matches carry a source locator again | `test_drive_grep.py::test_grep_idempotency_returns_match_with_provenance` |
| G8-07 | must | ls children carry the Drive link again | `test_no_source_link_in_results.py::test_ls_find_read_grep_results_carry_no_link_or_locator` |
| G8-08 | must | grep matches lose retrieved_at | `test_drive_grep.py::test_grep_idempotency_returns_match_with_provenance` |
| G8-09 | must | grep matches lose modified_time | `test_match_provenance.py::test_a_match_carries_its_full_provenance` |
| G8-10 | must | grep matches lose their location (line/offset) | `test_drive_grep.py::test_grep_idempotency_returns_match_with_provenance` |
| G8-11 | must | drive_read loses modified_time | `test_drive_read.py::test_read_returns_body_and_provenance` |
| G8-12 | must | drive_read loses retrieved_at | `test_drive_read.py::test_read_returns_body_and_provenance` |
| G8-13 | must | tool descriptions grow past the length hosts clip at (rule can be cut off) | `test_tool_schemas.py::test_citing_rule_leads_the_instructions_and_every_description` |

## G9. Failure taxonomy: classified, and no existence oracle (Art. XI)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G9-01 | must | 403 no longer reads as FILE_NOT_FOUND (permission and absence become distinguishable) | `test_allowed_folder.py::test_outside_missing_and_ungranted_ids_take_the_same_drive_calls` |
| G9-02 | must | 429 no longer reads as RATE_LIMITED | `test_drive_grep.py::test_folder_export_429_is_partial_not_envelope` |
| G9-03 | must | an unexpected Drive error reads as FILE_NOT_FOUND | `test_chain.py::test_google_500_during_chain_is_drive_api_error` |
| G9-04 | should | an unsupported type reads as INVALID_ARGUMENT | `test_drive_read.py::test_read_binary_is_unsupported_mime` |
| G9-05 | must | a binary file is downloaded and decoded as text | `test_fetch_text_refuses_binaries.py::test_a_binary_is_refused_and_never_downloaded` |
| G9-06 | must | arguments a tool does not take are accepted (chain and tool see different scopes) | `test_allowed_folder.py::test_arguments_a_tool_does_not_take_are_refused` |
| G9-07 | should | decision envelope carries the internal reason code in its message | `test_decision_envelope.py::test_every_refusal_gets_the_same_reply` |

## G10. Secrets and logs: no token, no document text in logs (Art. VII, XI)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G10-01 | must | a 'content' field is allowed into log records | `test_logging_hygiene.py::test_only_whitelisted_fields_are_written_and_redacted` |
| G10-02 | must | bearer tokens are no longer redacted | `test_log_redaction.py::test_an_authorization_header_that_is_not_bearer_is_redacted` |
| G10-03 | must | Authorization headers are no longer redacted | `test_log_redaction.py::test_an_authorization_header_that_is_not_bearer_is_redacted` |
| G10-04 | must | log lines carry exception text, not just the type | `test_log_redaction.py::test_an_exception_is_logged_by_type_and_never_by_text` |
| G10-05 | must | httpx request URLs are logged at INFO (carry keys and emails) | `test_logging_hygiene.py::test_email_routes_log_no_email_and_no_api_key` |
| G10-06 | must | log message text is not redacted | `test_logging_hygiene.py::test_only_whitelisted_fields_are_written_and_redacted` |
| G10-07 | must | string fields are not redacted | `test_log_redaction.py::test_a_secret_in_a_whitelisted_string_field_is_redacted` |

## G11. Abuse limits: the per-call ceilings against bulk extraction

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G11-01 | must | grep file cap 200 -> 2000 | `test_drive_grep.py::test_folder_grep_stops_at_grep_file_cap_with_cursor` |
| G11-02 | must | ls/find file cap 40 -> 400 | `test_published_limits.py::test_the_limits_are_the_published_numbers` |
| G11-03 | must | match cap 50 -> 5000 | `test_published_limits.py::test_the_limits_are_the_published_numbers` |
| G11-04 | must | per-operation byte cap 20 MB -> 200 MB | `test_published_limits.py::test_the_limits_are_the_published_numbers` |
| G11-05 | must | per-file byte cap 20 MB -> 200 MB | `test_published_limits.py::test_the_limits_are_the_published_numbers` |
| G11-06 | must | export size cap 20 MB -> 200 MB | `test_published_limits.py::test_the_limits_are_the_published_numbers` |
| G11-07 | must | time cap 25 s -> 250 s | `test_drive_grep.py::test_named_listing_cut_at_the_deadline_is_not_a_finished_slice` |
| G11-08 | must | the caller's max_matches can raise the cap above 50 | `test_published_limits.py::test_a_caller_cannot_raise_the_match_cap_past_fifty` |
| G11-09 | must | the caller's max_results can raise the find cap above 40 | `test_published_limits.py::test_a_caller_cannot_raise_the_find_cap_past_forty` |
| G11-10 | must | validation: max_results ceiling 40 -> 4000 | `test_invalid_argument.py::test_max_results_out_of_range` |
| G11-11 | must | validation: max_matches ceiling 50 -> 5000 | `test_published_limits.py::test_the_argument_ceilings_are_the_published_numbers` |
| G11-12 | must | validation: max_bytes ceiling 20 MB -> 200 MB | `test_invalid_argument.py::test_max_bytes_out_of_range` |
| G11-13 | must | grep never charges the byte budget | `test_drive_grep.py::test_folder_grep_defers_file_that_does_not_fit_and_scans_small_first` |
| G11-14 | must | grep returns more matches than max_matches from one file | `test_drive_grep.py::test_max_matches_inside_a_file_returns_an_in_file_cursor` |
| G11-15 | must | grep file cap not enforced | `test_drive_grep.py::test_max_files_on_binaries_is_partial_not_unsupported` |
| G11-16 | must | prefetch fetches a file that does not fit the remaining bytes | `test_drive_grep.py::test_invalid_utf8_does_not_make_a_prefetched_file_deferred` |
| G11-17 | must | read wire cap 30 MiB -> 300 MiB (Cloud Run rejects >32 MiB) | `test_large_responses.py::test_quote_heavy_text_is_cut_to_fit_the_response_cap` |
| G11-18 | must | /mcp body cap 4 MiB -> 400 MiB | `test_limits_pinned.py::test_the_request_body_caps_are_the_documented_numbers` |
| G11-19 | must | /register rate limit 20/h -> 20000/h | `test_limits_pinned.py::test_the_rate_limits_per_address_are_the_documented_numbers` |
| G11-20 | must | /token rate limit 600/min -> 600000/min | `test_limits_pinned.py::test_the_rate_limits_per_address_are_the_documented_numbers` |
| G11-21 | must | prefetch byte window 8 MB -> 800 MB | `test_prefetch_window.py::test_the_bytes_fetched_ahead_stay_inside_an_eight_megabyte_window` |

## G12. Documents are data, not instructions (Art. VI)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G12-01 | must | document text is passed to exec() (executable documents) | `test_documents_are_data.py::test_the_server_has_no_way_to_execute_text` |
| G12-02 | must | document text is handed to a shell | `test_documents_are_data.py::test_the_server_has_no_way_to_execute_text` |
| G12-03 | must | document text is used as the next tool call (server follows instructions in a document) | `test_documents_are_data.py::test_what_a_document_says_changes_nothing_but_its_own_text` |

## G13. Speed: the three engineering invariants from the latency fixes

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G13-01 | may | no per-call memo: the tool asks Drive for each id again | `test_one_metadata_get_per_id.py::test_drive_read_asks_drive_for_the_file_once` |
| G13-02 | may | the id lookups run one after another | `test_one_metadata_get_per_id.py::test_the_access_check_looks_the_ids_up_side_by_side` |
| G13-03 | may | the token is fetched by every thread (no lock) | `test_token_refreshed_once.py::test_ten_threads_starting_together_fetch_the_token_once` |
| G13-04 | may | folders are listed one at a time | `test_parallel_listing.py::test_folders_of_one_level_are_listed_at_the_same_time` |
| G13-05 | may | downloads run one at a time | `test_drive_grep.py::test_prefetched_grep_matches_a_sequential_scan_exactly` |
| G13-06 | may | id lookup pool shrinks to one worker | `test_one_metadata_get_per_id.py::test_the_access_check_looks_the_ids_up_side_by_side` |

## G14. OAuth and identity surface: no SSRF, no code theft, no account takeover (Art. VII)

| id | class | the wrong change the suite must reject | killed by |
|---|---|---|---|
| G14-01 | must | client-metadata fetch: the host allow-list is dropped (SSRF via client_id) | `test_oauth_surface.py::test_a_client_id_on_any_other_host_is_never_fetched` |
| G14-02 | must | client-metadata fetch: host matched by prefix (https://claude.ai.evil.example/x passes) | `test_oauth_surface.py::test_a_client_id_on_any_other_host_is_never_fetched` |
| G14-03 | must | client-metadata fetch follows redirects (an allowed host can bounce it inward) | `test_oauth_surface.py::test_an_allowed_host_is_fetched_without_following_redirects` |
| G14-04 | should | client_id length cap removed | `test_oauth_limits.py::test_cimd_client_id_over_512_characters_is_refused` |
| G14-05 | must | redirect allow-list defaults to allow (authorization code can go to any URL) | `test_oauth_surface.py::test_the_redirect_allow_list_for_client_metadata_clients` |
| G14-06 | must | plain-http redirect accepted for any host, not only loopback | `test_oauth_surface.py::test_the_redirect_allow_list_for_client_metadata_clients` |
| G14-07 | must | registered client id: token type not checked (any signed token is a client) | `test_oauth_surface.py::test_only_a_registration_is_a_client_id` |
| G14-08 | must | registered client id: audience not checked | `test_oauth_surface.py::test_only_a_registration_is_a_client_id` |
| G14-09 | should | registration: redirect_uris ceiling 5 -> 5000 | `test_oauth_limits.py::test_oversized_metadata_is_invalid_client_metadata` |
| G14-10 | should | registration: metadata ceiling 16 KB -> 16 MB | `test_oauth_limits.py::test_oversized_metadata_is_invalid_client_metadata` |
| G14-11 | must | consent: the password is not checked | `test_oauth_http.py::test_consent_password_required_when_auto_approve_disabled` |
| G14-12 | must | consent: a lapsed subscriber's click still issues a code | `test_subscription_http.py::test_allow_needs_the_same_paying_browser` |
| G14-13 | must | consent page: client_name not HTML-escaped (script injection from a registered name) | `test_oauth_surface.py::test_a_registered_name_with_markup_is_shown_as_text` |
| G14-14 | must | consent page: return host not HTML-escaped | `test_oauth_surface.py::test_the_pages_escape_everything_they_print` |
| G14-15 | must | consent page: ticket not HTML-escaped | `test_oauth_surface.py::test_the_pages_escape_everything_they_print` |
| G14-16 | must | consent: the click is no longer tied to the subscriber's own browser (hash not compared) | `test_oauth_limits.py::test_ticket_for_another_subscriber_is_refused` |
| G14-17 | must | an authorization code works for a different client | `test_token_lifecycle.py::test_a_code_and_a_refresh_token_belong_to_the_client_they_were_issued_to` |
| G14-18 | must | a refresh token works for a different client | `test_token_lifecycle.py::test_a_code_and_a_refresh_token_belong_to_the_client_they_were_issued_to` |
| G14-19 | must | resume redirect: only /authorize paths allowed check dropped (open redirect) | `test_oauth_surface.py::test_only_an_authorize_path_on_this_origin_is_a_resume_target` |
| G14-20 | must | resume redirect: '//', '://' and backslash checks dropped | `test_oauth_surface.py::test_only_an_authorize_path_on_this_origin_is_a_resume_target` |
| G14-21 | must | email restore: the link's address need not match the typed address (account takeover) | `test_oauth_surface.py::test_a_link_restores_only_the_address_it_was_sent_to` |
| G14-22 | should | email restore: the address is left on the identity provider's side | `test_oauth_surface.py::test_the_address_is_not_kept_at_the_identity_provider` |
| G14-23 | should | resume cookie loses HttpOnly | `test_oauth_surface.py::test_the_cookies_the_server_sets_cannot_be_read_by_scripts` |

## Survivors that are not gaps

| id | the wrong change | why no test tells it from the real code |
|---|---|---|
| G1-09 | rewrite layer 1 only (handle_tool) | equivalent while the other argument-rewriting layer holds; both together are killed (G1-S1) |
| G1-10 | rewrite layer 2 only (middleware.authorize) | equivalent while the other argument-rewriting layer holds; both together are killed (G1-S1) |
| G1-11 | rewrite layer 3 only (evaluate_chain) | equivalent: the chain's own rewrite only feeds its decision, and the arguments arrive already rewritten |
| G1-13 | whole-grant refusal removed (only the last of five layers against an unscoped call) | unreachable while any rewrite layer holds: the folder is always set before this check |
| G1-18 | walker scope check removed for named files | equivalent: the chain checks the same membership first |
| G1-S2 | second order: rewrite layers 2 and 3 removed together (layer 1 still rewrites the arguments) | one argument-rewriting layer still holds |
| G1-S3 | second order: rewrite layers 1 and 3 removed together (layer 2 still rewrites the arguments) | one argument-rewriting layer still holds |
| G5-05 | grep: a cut file listing (time) no longer makes the result PARTIAL | dead code: a cut listing returns earlier, so walk.time_exceeded is always false at this point |
| G5-18 | ls: a truncated listing is reported as COMPLETE | redundant: immediate_children sets truncated equal to more, so the second test never differs |
| G6-07 | scan order has no id tie-break | not a requirement: equal-sized files are ordered by name or by id, both deterministic; the contract does not say which |
| G6-11 | a repeated id in file_ids is scanned twice | masked by the second duplicate guard; both removed together is killed (G6-S1) |

## History

- **2026-11-23, first measurement.** The 431 tests in the repository killed 128 of 208 entries; 80 survived.
  Six kills turned out not to be kills: five were load flakes of one existing test (`test_a_refused_call_still_looks_up_every_named_id`, a race in the access check, see below) and are counted as survivors;
  the sixth (G7-01) fails only after other tests have run, and a direct test kills it alone.
- **Closing tests.** 203 tests in 22 files (commits `34fe4a7`, `eb7e378`) killed 71 of the 80 survivors. The measurement and the closing tests found two real defects:
  log redaction masked only the first word after `Authorization:` (fixed in `34fe4a7`), and the access check cancelled its id lookups that had not started when it refused a call, so which calls Drive saw depended on thread timing (fixed in `f222497`; the new `tests/unit/access_control/test_fetching.py` fails on the old code every time).
- **Final measurement, same day.** All 212 entries (the 208 above and 4 second-order ones) against the suite of 636 tests with nothing excluded, three parallel workers, and every kill re-run alone: 201 killed, 11 survive by design.
  The three entries on request limits (G11-18 to G11-20) were then re-measured after two tests were added that pin the rate limits and body caps by value (638 tests): the rate-limit test counts requests up to the limit, so a limit raised a thousandfold made it run for minutes instead of failing.

## What this list does not cover

A threat that is not on it is not covered. A killed entry means a test notices that change, not that the invariant holds in every other case.
The agent wrote the code, most of the tests, this list and the closing tests, so all of them share its reading of the invariants; the owner's review of the list is the check that does not.
The payload corpus in `tests/unit/test_documents_are_data.py` includes the markers the G12 entries use, so those three kills are regression pins, not proofs: no test can see a hidden behavior it is never fed.
