# Threat model

Scope: the Innovation Day prototype running on a single trusted workstation with synthetic
data. This is not a production security assessment. The prototype has not had a formal
security review and must not be exposed beyond a trusted local environment without one.

## Assets

1. Communication content (transcripts) and the sensitive values inside them.
2. The policy configuration, which decides what AI may see and send.
3. The audit trail, which must be accurate and must not become a copy of the data.
4. Integration credentials (the CloudLink key, and the admin key if set).

## Trust boundaries

| Boundary | Trusted side | Untrusted side |
|---|---|---|
| Browser to API | Backend | Every request field, including any decision-like field |
| Firewall to local model | Firewall | Model output (treated as untrusted text) |
| Firewall to CloudLink | Firewall's validated payload | The network and receiver |
| Administrator to policy store | Administrator (optional admin key) | Anyone else who can reach the API |

## Threats and mitigations

| # | Threat | Mitigation in this prototype | Verified by |
|---|---|---|---|
| T1 | Client submits a pre-approved decision, destination or flag to bypass policy | Request models use `extra="forbid"`. Decisions are recomputed from the stored policy set on every request. The mode can only narrow. | `test_client_cannot_submit_decisions_or_destinations`, `test_mode_can_only_narrow_policy` |
| T2 | A broad ALLOW rule overrides a restriction | Most-restrictive-wins resolution; priority only breaks ties within one action | `test_broad_allow_cannot_override_restrictive_rule` |
| T3 | Detection, policy or redaction failure leads to permissive transmission | Each stage raises a typed error; the result becomes `PROCESSING_FAILED` and no AI or cloud call is made | `test_detection_failure_prevents_outbound`, `test_policy_evaluation_failure_prevents_outbound`, `test_redaction_failure_prevents_outbound`, `test_policy_store_failure_prevents_outbound` |
| T4 | No policy covers a request or an entity | No applicable policy blocks; uncovered entities default to LOCAL_ONLY | `test_no_applicable_policy_denies_by_default`, `test_unmatched_entity_gets_conservative_default` |
| T5 | Model output leaks a value or introduces a new identifier | The outbound validator checks protected values (whole-token match) and re-scans the payload for restricted categories; failure denies transmission | `test_model_output_leaking_a_protected_value_is_not_sent`, `test_model_output_with_new_restricted_entity_is_not_sent`, `test_rescan_failure_prevents_outbound` |
| T6 | Payload changed after validation | `ValidatedPayload` carries a SHA-256 fingerprint; the client refuses mismatches | `test_client_refuses_payload_modified_after_validation` |
| T7 | BLOCKED or LOCAL_ONLY content reaches the cloud | The client is never called for them; the receiver independently rejects them with 409 | `test_blocked_request_never_reaches_mock_cloudlink`, `test_local_only_request_never_reaches_mock_cloudlink`, `test_receiver_rejects_blocked_and_local_only_payloads` |
| T8 | Transcript or values persisted in audit or logs | `AuditEntry` has no text fields; logs use a field whitelist; validation errors omit input | `test_raw_values_are_not_written_to_audit_records`, `test_logs_do_not_contain_transcripts_or_values`, `test_validation_errors_do_not_echo_input` |
| T9 | Secrets exposed | Loaded from environment; `/api/config` reports only "configured"; `.env` is gitignored | `test_config_never_exposes_secrets` |
| T10 | Oversized or malformed requests exhaust resources | Body size limit (middleware), transcript length limit, strict schemas | `test_oversized_body_is_rejected`, `test_oversized_transcript_is_rejected`, `test_invalid_requests_are_rejected` |
| T11 | Cross-origin browser access | CORS allows only `CORS_ORIGINS`; no credentials | `test_cors_only_allows_configured_origin` |
| T12 | Unauthorized policy changes | Optional `ADMIN_API_KEY` guards create, update, delete, reset and purge (constant-time compare) | `test_admin_key_protects_policy_mutations` |
| T13 | Retry resends data under a stale decision | No automatic retries; each request is decided and sent at most once | Code review (`CloudLinkClient.send`) |
| T14 | Silent fallback to another AI service | There is no fallback path; failures are reported with their real status | `test_missing_model_is_reported_across_the_api` |
| T15 | Prompt injection in the transcript | The prompt marks the transcript as data; output is untrusted and re-validated before any outbound use | Validator tests above |
| T16 | Unknown profile falls back to global rules | Unknown profiles are rejected with 422 | `test_unknown_profile_is_rejected` |
| T17 | Raw call audio is stored or leaves the machine | Audio is transcribed locally (faster-whisper) from a temp file deleted in `finally`, also on error; it is never stored. Receipts record only format, duration, model and transcription time; audit records only transcription time. Bleeped audio is built in memory and returned, never written to disk | `test_temp_file_is_deleted_after_success_and_after_failure`, `test_receipt_and_audit_record_only_audio_facts`, `test_process_audio_returns_bleeped_wav_for_protected_words` |
| T18 | A transcription or audio failure leads to processing or sending anyway | Any transcription error (unreadable, too long, empty, model missing) returns an error before the pipeline runs; nothing is processed or sent. With `bleep=true` the WAV is checked before transcription | `test_transcription_failure_processes_and_sends_nothing`, `test_unexpected_transcriber_error_fails_closed`, `test_bleep_needs_wav_and_fails_before_processing` |
| T19 | Large uploads exhaust resources | Audio routes have their own limit (`MAX_AUDIO_BYTES`, `MAX_AUDIO_SECONDS`); every other route keeps `MAX_REQUEST_BYTES` | `test_oversized_audio_is_rejected_before_transcription`, `test_other_routes_keep_the_small_body_limit` |
| T20 | A breach report exposes the values it describes, or is mistaken for a filing | Reports hold categories, counts and IDs only; synthetic canary surface text appears only in a labelled appendix. Every draft carries "DRAFT for compliance review. Not filed. Not legal advice." Nothing is ever sent | `test_no_raw_values_outside_the_synthetic_appendix`, `test_markdown_carries_the_draft_watermark_at_top_and_bottom`, `test_drafting_sends_nothing` |
| T21 | A report, measurement or sizing figure is not backed by records | Reports store their selection and `/verify` recomputes every count; canary runs fail if the receiver log does not match what was sent; sizing uses only completed benchmark runs and never extrapolates | `test_verify_is_ok_then_detects_a_changed_record`, `test_receiver_log_mismatch_fails_the_run_instead_of_reporting_zero`, `test_no_benchmark_means_no_numbers` |

## Known limitations and residual risk

- **Detection is probabilistic.** spaCy NER misses unusual or lowercase names. The custom
  PATIENT_ID and ACCOUNT_NUMBER recognizers need context words, so a bare number is not
  treated as an identifier. Recognizer-by-recognizer limitations are listed on the Settings
  page and in `backend/app/policies/detection.yaml`. The prototype never claims complete
  detection.
- **The re-scan uses the same detector**, so it cannot catch what the detector misses. The
  protected-value check covers known values only.
- **No authentication on read endpoints**, and policy mutations are open unless
  `ADMIN_API_KEY` is set. Suitable only for a trusted local machine.
- **The Inspector shows detected values** when `EXPOSE_DETECTED_VALUES=true`. Use synthetic
  data only, or disable it.
- **Transport security**: services use plain HTTP on localhost. Production would need TLS and
  real service authentication.
- **Custom regex recognizers** are trusted administrator configuration. Matching has a
  1-second timeout, but patterns should be kept simple.
- **The mock receiver keeps the last 20 payloads in memory** for demonstration.
- **SQLite** is single-node and unencrypted at rest. The audit data it holds is designed to be
  non-sensitive, but an encrypted store would be needed for real deployments.
- **Mitel CloudLink** is not integrated. No real endpoints, credentials or authentication
  schemes are assumed.
