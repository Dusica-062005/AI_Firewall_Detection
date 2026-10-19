# API contract

Base URL: `http://localhost:8000/api` (configurable in `frontend/public/config.json`).
Interactive schema: `http://localhost:8000/docs` (generated from the Pydantic models).

## Conventions

- JSON request and response bodies. Unknown request fields are rejected (`422`).
- Every response has an `X-Request-ID` header. A client may send its own `X-Request-ID`
  (8-64 characters, letters, digits and hyphens); otherwise one is generated.
- Errors always use this envelope. It never contains stack traces, paths, environment
  values or the submitted input.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request failed validation.",
    "request_id": "20f50798-b77b-4211-8114-7b676e253a8d",
    "details": [{ "loc": ["body", "decision"], "msg": "Extra inputs are not permitted", "type": "extra_forbidden" }]
  }
}
```

| Status | Code examples | Meaning |
|---|---|---|
| 401 | `UNAUTHORIZED` | `X-Admin-Key` missing or wrong (only when `ADMIN_API_KEY` is set) |
| 404 | `POLICY_NOT_FOUND`, `AUDIT_EVENT_NOT_FOUND` | Resource does not exist |
| 409 | `POLICY_EXISTS` | Policy ID already used |
| 413 | `PAYLOAD_TOO_LARGE`, `TRANSCRIPT_TOO_LARGE` | Body over `MAX_REQUEST_BYTES` or transcript over `MAX_TRANSCRIPT_CHARS` |
| 422 | `VALIDATION_ERROR`, `UNKNOWN_PROFILE`, `POLICY_INVALID` | Schema or semantic validation failed |
| 500 | `INTERNAL_ERROR` | Unexpected error; nothing was sent to any AI service |
| 503 | `POLICY_UNAVAILABLE` | Policy configuration failed to load; processing disabled |

A `BLOCKED` or `PROCESSING_FAILED` decision is returned with HTTP `200`. It is a valid result
of the firewall, not an API error.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | - | Application status and dependency availability |
| GET | `/metrics/summary?window_hours=24` | - | Counts, entity categories, latency statistics, hourly timeline |
| POST | `/inspect` | - | Detect and evaluate policy; never calls a model or the cloud |
| POST | `/process` | - | Full policy-controlled workflow |
| GET | `/policies` | - | List policies and the active policy-set version |
| POST | `/policies` | admin | Create a policy |
| GET | `/policies/{policy_id}` | - | Get one policy |
| PUT | `/policies/{policy_id}` | admin | Replace a policy's editable fields (version increments) |
| DELETE | `/policies/{policy_id}` | admin | Delete a policy |
| POST | `/policies/validate` | - | Validate without saving; returns errors and precedence warnings |
| POST | `/policies/reset` | admin | Replace all policies with the seed file |
| GET | `/policies/profiles` | - | Known profiles with applicable-policy counts |
| GET | `/policies/entity-categories` | - | Categories a policy may reference |
| GET | `/audit` | - | Paginated, filterable audit events |
| GET | `/audit/{event_id}` | - | One privacy-safe audit event |
| POST | `/audit/purge` | admin | Apply the retention period now |
| GET | `/integrations/status` | - | Ollama and mock CloudLink availability |
| GET | `/config` | - | Safe configuration (secrets are reported only as configured or not) |
| GET | `/samples` | - | Synthetic demo transcripts |

"admin" means `X-Admin-Key` is required when `ADMIN_API_KEY` is set. Without it the API is
intended only for a trusted local environment.

## POST /process

Request (`ProcessRequest`):

| Field | Type | Default | Notes |
|---|---|---|---|
| `transcript` | string | required | Not blank; at most `MAX_TRANSCRIPT_CHARS` |
| `profile` | string | `standard` | Must be a known profile |
| `channel` | `voice` \| `chat` \| `email` \| `sms` | `voice` | Used by channel conditions |
| `mode` | `inspect` \| `local` \| `full` | `full` | Can only narrow what policy allows |

```bash
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"transcript":"My name is John Smith, my patient ID is 48291, and I need help with my appointment.","profile":"standard","channel":"voice","mode":"full"}'
```

Response (`FirewallResult`, abbreviated real response with Ollama stopped):

```json
{
  "request_id": "e183a00a-c3b5-4dfb-849b-8cfa35165dcf",
  "event_id": "evt-9c0e539efbe94c89",
  "operation": "PROCESS",
  "mode": "full",
  "profile": "standard",
  "channel": "voice",
  "decision": "REDACTED",
  "status": "COMPLETED_WITH_WARNINGS",
  "authorized_destination": "CLOUD",
  "policy_version": "ps-81fe423a2391",
  "decisive_policy_id": "redact-patient-id",
  "error_category": "LOCAL_MODEL_UNAVAILABLE",
  "reasons": ["Detected categories: PATIENT_ID, PERSON.", "..."],
  "warnings": ["Ollama is not reachable at the configured URL."],
  "transcript_chars": 83,
  "entities": [
    {
      "entity_type": "PERSON", "start": 11, "end": 21, "score": 0.85, "low_confidence": false,
      "recognizer": "SpacyRecognizer", "value": "John Smith", "action": "REDACT", "destination": "CLOUD",
      "policy_id": "redact-contact-identifiers", "policy_name": "Redact contact identifiers",
      "reason": "Redact contact identifiers applies REDACT to PERSON."
    },
    {
      "entity_type": "PATIENT_ID", "start": 40, "end": 45, "score": 0.9, "low_confidence": false,
      "recognizer": "patient-id-contextual", "value": "48291", "action": "REDACT", "destination": "CLOUD",
      "policy_id": "redact-patient-id", "policy_name": "Redact patient identifiers",
      "reason": "Redact patient identifiers applies REDACT to PATIENT_ID."
    }
  ],
  "entity_counts": { "PERSON": 1, "PATIENT_ID": 1 },
  "matched_policies": [
    { "policy_id": "redact-patient-id", "name": "Redact patient identifiers", "action": "REDACT",
      "destination": "CLOUD", "priority": 150, "matched_categories": ["PATIENT_ID"] }
  ],
  "redacted_transcript": "My name is [PERSON], my patient ID is [PATIENT_ID], and I need help with my appointment.",
  "summary": {
    "status": "UNAVAILABLE", "text": null, "model": "llama3.2:3b", "latency_ms": 2325.41,
    "message": "Ollama is not reachable at the configured URL."
  },
  "outbound": {
    "status": "SENT",
    "reached_receiver": true,
    "simulated": true,
    "target": "http://localhost:8100/v1/handoff",
    "payload": {
      "schema_version": "1.0", "request_id": "e183a00a-c3b5-4dfb-849b-8cfa35165dcf",
      "decision": "REDACTED", "destination": "CLOUD", "profile": "standard", "channel": "voice",
      "policy_version": "ps-81fe423a2391", "entity_categories": ["PATIENT_ID", "PERSON"],
      "sanitized_summary": null,
      "sanitized_transcript": "My name is [PERSON], my patient ID is [PATIENT_ID], and I need help with my appointment.",
      "created_at": "2026-09-29T09:18:30.248125Z"
    },
    "receiver_response": {
      "receipt_id": "clk-d98fc9c46565", "request_id": "e183a00a-c3b5-4dfb-849b-8cfa35165dcf",
      "status": "ACCEPTED", "simulated": true, "received_at": "2026-09-29T09:18:30.535131+00:00",
      "summary_chars": 0, "transcript_chars": 88, "entity_categories": ["PATIENT_ID", "PERSON"]
    },
    "http_status": 200,
    "latency_ms": 274.33,
    "validation": [
      { "name": "policy_authorization", "passed": true, "detail": "Policy authorizes cloud transmission." },
      { "name": "schema", "passed": true, "detail": "Payload matches the CloudLink handoff schema." },
      { "name": "decision_binding", "passed": true, "detail": "Payload is bound to this request and policy decision." },
      { "name": "size", "passed": true, "detail": "Payload size 420 bytes (limit 131072)." },
      { "name": "no_protected_values", "passed": true, "detail": "No protected values appear in the payload." },
      { "name": "rescan", "passed": true, "detail": "Re-scan found no restricted entities in the payload." }
    ],
    "message": "Mock CloudLink receiver accepted the payload."
  },
  "steps": [
    { "key": "received", "label": "Received", "status": "COMPLETED", "duration_ms": null, "detail": "..." },
    { "key": "analyzed", "label": "Analyzed", "status": "COMPLETED", "duration_ms": 11.04, "detail": "..." },
    { "key": "policy", "label": "Policy evaluated", "status": "COMPLETED", "duration_ms": 0.92, "detail": "..." },
    { "key": "protected", "label": "Protected", "status": "COMPLETED", "duration_ms": 0.16, "detail": "..." },
    { "key": "ai", "label": "Local AI / Cloud", "status": "WARNING", "duration_ms": 2599.74, "detail": "..." },
    { "key": "audited", "label": "Audited", "status": "COMPLETED", "duration_ms": 6.1, "detail": "..." }
  ],
  "latency": {
    "detection_ms": 11.04, "policy_ms": 0.92, "protection_ms": 0.16, "local_ai_ms": 2325.41,
    "validation_ms": 16.02, "cloud_ms": 274.33, "audit_ms": 6.1, "total_ms": 2628.67
  },
  "created_at": "2026-09-29T09:18:30.540000Z"
}
```

### Field vocabularies

| Field | Values |
|---|---|
| `decision` | `ALLOWED`, `REDACTED`, `LOCAL_ONLY`, `BLOCKED`, `PROCESSING_FAILED` |
| `status` | `COMPLETED`, `COMPLETED_WITH_WARNINGS`, `FAILED` |
| `authorized_destination` | `NONE`, `LOCAL`, `CLOUD` |
| `summary.status` | `GENERATED`, `NOT_AUTHORIZED`, `SKIPPED_BY_MODE`, `UNAVAILABLE`, `MODEL_MISSING`, `TIMEOUT`, `INVALID_OUTPUT`, `ERROR` |
| `outbound.status` | `SENT`, `NOT_AUTHORIZED`, `SKIPPED_BY_MODE`, `VALIDATION_FAILED`, `REJECTED`, `UNAVAILABLE`, `ERROR` |
| `steps[].status` | `COMPLETED`, `WARNING`, `BLOCKED`, `FAILED`, `SKIPPED` |
| `error_category` | `DETECTION_FAILURE`, `POLICY_LOAD_FAILURE`, `POLICY_EVALUATION_FAILURE`, `REDACTION_FAILURE`, or the first warning code |

`outbound.reached_receiver` is `true` only when an HTTP response came back from the receiver.
`outbound.payload` is present only when a request was attempted. `latency.total_ms` excludes
the audit write, which is reported separately as `audit_ms`.

`entities[].value` is returned only when `EXPOSE_DETECTED_VALUES=true` (the synthetic-data
default). It is never stored.

## POST /inspect

Same request body without `mode`, and the same `FirewallResult` response, with
`operation: "INSPECT"`. `summary.status` and `outbound.status` are always `SKIPPED_BY_MODE`
(or `NOT_AUTHORIZED` after a failure). An audit event is recorded.

## Policies

`PolicyCreate` / `PolicyUpdate` body:

```json
{
  "policy_id": "block-names-for-billing",
  "name": "Block names for billing",
  "description": "Optional text, up to 500 characters.",
  "enabled": true,
  "priority": 40,
  "entity_categories": ["PERSON"],
  "action": "BLOCK",
  "destination": "NONE",
  "conditions": { "profiles": ["standard"], "channels": [], "min_confidence": 0.0 }
}
```

- `policy_id` is optional on create (generated from the name) and not accepted on update.
- `entity_categories`: known categories, or `["ANY"]` alone. `REDACT` cannot use `ANY`.
- `action`/`destination` pairs: ALLOW or REDACT with LOCAL or CLOUD; LOCAL_ONLY with LOCAL;
  BLOCK with NONE.
- `priority` 1-1000. `min_confidence` 0-1. Profiles use 2-40 lowercase letters, digits or hyphens.

`Policy` responses add `policy_id`, `version`, `created_at` and `updated_at`.

`POST /policies/validate` returns:

```json
{ "valid": true, "errors": [], "warnings": ["'Redact contact identifiers' ... takes precedence ..."] }
```

## GET /audit

Query parameters: `page` (default 1), `page_size` (1-200, default 25), `date_from`, `date_to`
(ISO 8601), `decision`, `policy_id` (matches any matched policy), `status`, `destination`,
`request_id` (substring).

```json
{
  "items": [
    {
      "event_id": "evt-9c0e539efbe94c89",
      "request_id": "e183a00a-c3b5-4dfb-849b-8cfa35165dcf",
      "created_at": "2026-09-29T09:18:30.538281Z",
      "operation": "PROCESS", "mode": "full", "profile": "standard", "channel": "voice",
      "decision": "REDACTED", "status": "COMPLETED_WITH_WARNINGS", "destination": "CLOUD",
      "local_ai_status": "UNAVAILABLE", "cloud_status": "SENT",
      "policy_version": "ps-81fe423a2391", "decisive_policy_id": "redact-patient-id",
      "policy_ids": ["redact-patient-id", "redact-contact-identifiers", "baseline-sanitized-cloud"],
      "entity_counts": { "PERSON": 1, "PATIENT_ID": 1 },
      "latency_ms": { "detection_ms": 11.04, "policy_ms": 0.92, "protection_ms": 0.16,
                      "local_ai_ms": 2325.41, "validation_ms": 16.02, "cloud_ms": 274.33 },
      "total_latency_ms": 2628.67,
      "error_category": "LOCAL_MODEL_UNAVAILABLE",
      "transcript_chars": 83,
      "warnings": ["LOCAL_MODEL_UNAVAILABLE"],
      "cloud_receipt_id": "clk-d98fc9c46565"
    }
  ],
  "total": 22, "page": 1, "page_size": 1
}
```

## GET /health

```json
{
  "status": "degraded",
  "version": "0.1.0",
  "time": "2026-09-29T09:20:00Z",
  "components": {
    "database": { "status": "READY", "message": "Database reachable." },
    "detection": { "status": "READY", "message": "Presidio loaded with spaCy model en_core_web_md." },
    "policies": { "status": "READY", "message": "Policy configuration loaded." },
    "ollama": { "status": "UNREACHABLE", "message": "Ollama is not running or not reachable at the configured URL." },
    "cloudlink": { "status": "CONNECTED", "message": "Mock CloudLink receiver is reachable. (simulated)" }
  }
}
```

`status` is `ok` only when every component is available. Enforcement depends on
`database`, `detection` and `policies`; the AI integrations are optional.

## GET /integrations/status

```json
{
  "checked_at": "2026-09-29T09:20:00Z",
  "ollama": {
    "status": "MODEL_MISSING", "base_url": "http://localhost:11434", "model": "llama3.2:3b",
    "model_available": false, "available_models": ["mistral:latest"], "latency_ms": 4.2,
    "message": "Ollama is running but model 'llama3.2:3b' is not installed. Run: ollama pull llama3.2:3b"
  },
  "cloudlink": {
    "status": "CONNECTED", "base_url": "http://localhost:8100", "simulated": true,
    "receipts_count": 3, "latency_ms": 2.1, "message": "Mock CloudLink receiver is reachable."
  }
}
```

## GET /metrics/summary

Aggregates over retained audit events. Keys: `total_requests`, `decision_counts`,
`status_counts`, `destination_counts`, `entity_category_counts`, `total_entities`,
`cloud_handoffs_sent`, `local_summaries_generated`, `latency` (`total`, `detection`, `policy`,
`local_ai`, `cloud`, each with `count`, `avg_ms`, `p50_ms`, `p95_ms`, `max_ms`) and `timeline`
(hourly buckets for `window_hours` with per-decision counts).

## Mock CloudLink receiver (port 8100, simulated)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status":"ok","simulated":true,"receipts_count":N,"rejected_count":N}` |
| POST | `/v1/handoff` | Requires `X-CloudLink-Key` when `CLOUDLINK_API_KEY` is set. Returns `200 ACCEPTED`, `401`, `409` (decision not ALLOWED/REDACTED or destination not CLOUD) or `422` (schema) |
| GET | `/v1/receipts` | Recent receipt metadata (no payload text) |

The browser never calls the receiver; only the backend's `CloudLinkClient` does.
