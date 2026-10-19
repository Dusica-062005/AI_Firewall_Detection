# Architecture

Mitel AI Data Firewall is one governance boundary between communication workloads and AI
services. Before AI sees communication data, the firewall decides what AI is allowed to see,
process and send.

## Components

```
                 Browser (Angular, localhost:4200)
                              |
                              |  HTTPS/HTTP JSON  (CORS: configured origin only)
                              v
+--------------------------------------------------------------------------+
| Firewall backend (FastAPI, localhost:8000)                               |
|                                                                          |
|  API routes  ->  ProcessingService (orchestration, timing, audit)        |
|                    |                                                     |
|                    v                                                     |
|                  FirewallService  (the governance boundary)              |
|                    1 Detection      SensitiveDataAnalyzer (Presidio)     |
|                    2 Policy match   PolicyEngine (deterministic)         |
|                    3 Resolution     most restrictive wins                |
|                    4 Protection     Redactor (Presidio Anonymizer)       |
|                    5 Verification   redaction integrity check            |
|                    |                                                     |
|          +---------+-----------+                                         |
|          | local AI authorized |  cloud authorized                       |
|          v                     v                                         |
|   Summarizer -> OllamaClient   OutboundValidator -> CloudLinkClient ------+--> Mock CloudLink
|          |       (local:11434)       (re-scan, value check, binding)     |    receiver (8100)
|          v                                                               |
|   AuditService -> SQLite (policies, privacy-safe audit events)           |
+--------------------------------------------------------------------------+
```

| Component | Location | Responsibility |
|---|---|---|
| Angular UI | `frontend/src/app` | Overview, Inspector, Policies, Audit, Settings. Never decides anything; displays backend results. |
| API layer | `backend/app/api` | Request validation, request IDs, size limits, error envelope, CORS, admin-key check. No business logic. |
| ProcessingService | `backend/app/services/processing_service.py` | Runs the workflow, measures each stage, calls AI only when authorized, writes the audit event. |
| FirewallService | `backend/app/services/firewall_service.py` | Detection, policy evaluation, redaction and cloud payload construction. Fails closed at every step. |
| SensitiveDataAnalyzer | `backend/app/detection` | Presidio plus custom context recognizers; deterministic overlap resolution; repeated-value propagation. |
| PolicyEngine | `backend/app/policy/engine.py` | Pure function from entities and policies to a decision. No I/O, no FastAPI. |
| Redactor | `backend/app/security/redactor.py` | Presidio Anonymizer replacement, cross-checked against an independent span replacement. |
| OutboundValidator | `backend/app/security/outbound_validator.py` | Final gate before the cloud. Issues a `ValidatedPayload` bound to one request and decision. |
| CloudLinkClient | `backend/app/integrations/cloudlink_client.py` | Adapter that only sends a `ValidatedPayload` whose fingerprint still matches. No retries. |
| Mock CloudLink | `backend/app/integrations/mock_cloudlink.py` | Separate process. Validates schema and key, rejects BLOCKED and LOCAL_ONLY, keeps receipts in memory. |
| OllamaClient / Summarizer | `backend/app/ai` | Local model calls with timeout, honest failure states and output validation. No fallback. |
| Persistence | `backend/app/db` | SQLAlchemy models and repositories. Schema created with `metadata.create_all()` on start. |

## Processing sequence

1. **Received.** Pydantic validates the request (`extra="forbid"`: clients cannot send decisions,
   destinations or approval flags). The body size and transcript length are limited. Unknown
   profiles are rejected.
2. **Analyzed.** Presidio and the custom recognizers detect entities. Overlaps are resolved
   deterministically (score, then length, then custom recognizer, then name). Later
   repetitions of a detected value are also flagged.
3. **Policy evaluated.** The engine loads the authoritative policy set from the database and
   resolves an action and destination per entity and per request.
4. **Protected.** Every entity whose action is not ALLOW is replaced with `[CATEGORY]`. The
   output must equal an independent right-to-left replacement and contain no protected value.
5. **Local AI / Cloud decision.**
   - The local model runs only if the decision is not BLOCK and the destination is LOCAL or
     CLOUD. It receives the protected text only.
   - The cloud handoff runs only if the destination is CLOUD, the mode is `full` and the final
     payload passes validation. The model summary is untrusted and is re-validated.
6. **Audited.** One event with categories, counts, decisions and measured stage latency. No
   transcript text and no entity values.

Any failure in steps 2 to 4 produces `PROCESSING_FAILED`: nothing further runs, and nothing is
sent. A `BLOCKED` decision is a policy outcome, not a failure.

## Policy model and precedence

A policy is a rule: entity categories (or `ANY`), an action, a destination, a priority and
conditions (profiles, channels, minimum confidence).

| Action | Allowed destinations | Effect |
|---|---|---|
| ALLOW | LOCAL, CLOUD | Value stays in text; still subject to every outbound check. |
| REDACT | LOCAL, CLOUD | Value replaced with a placeholder before any AI call. |
| LOCAL_ONLY | LOCAL | Value replaced; cloud transmission prohibited. |
| BLOCK | NONE | No local model call and no outbound request. |

Resolution rules, enforced in `PolicyEngine`:

1. Only enabled policies whose profile and channel conditions match apply.
2. For each entity, the most restrictive action wins: BLOCK > LOCAL_ONLY > REDACT > ALLOW.
   Priority (lower number first) only chooses which of several same-action rules is reported
   as decisive. A broad ALLOW can never override a restriction.
3. The destination is the most restrictive of all matching rules: NONE < LOCAL < CLOUD.
4. `ANY` rules apply to the whole request, including requests without entities.
5. An entity no rule covers receives `UNMATCHED_ENTITY_ACTION` (LOCAL_ONLY by default).
6. If no rule applies at all the request is blocked (deny by default).
7. Cloud transmission requires destination CLOUD and a passing outbound validation.

The three seed profiles demonstrate the outcomes on the same transcript:

| Profile | Decisive rule | Result |
|---|---|---|
| `standard` | `redact-patient-id` | REDACTED, sanitized payload sent to the mock receiver |
| `healthcare` | `healthcare-phi-local-only` | LOCAL_ONLY, local summary only |
| `restricted` | `restricted-block-phi` | BLOCKED, no model or cloud call |

## Data handling

| Data | Where it exists | Persisted |
|---|---|---|
| Raw transcript | Request memory only | No |
| Detected values | Request memory; returned to the Inspector when `EXPOSE_DETECTED_VALUES=true` | No |
| Protected text / summary | Request memory; returned to the Inspector | No |
| Cloud payload | Sent to the mock receiver, which keeps the last 20 in memory | No (receiver memory only) |
| Audit event | SQLite `audit_events` | Yes: categories, counts, decisions, latency, IDs |
| Policies | SQLite `policies`; seeded from `default.yaml` | Yes |

Logs are JSON lines with request IDs and a whitelist of fields. Request bodies are never
logged, and validation errors are returned without the submitted input.

## Chart colours

The Overview decision chart uses one fixed colour per decision: ALLOWED `#16805D`, REDACTED
`#245A9B`, LOCAL_ONLY `#5B8FD0`, BLOCKED `#B42318`, FAILED `#B7791F`. The palette was checked
for lightness, chroma, colour-vision-deficiency separation and contrast against white. Every
chart also has a legend and tooltips, and the same counts are available as text in the KPI
cards and audit table.

## Replacing the mock with a real integration

`CloudLinkClient` is the only outbound adapter. A production integration would implement
the same `send(ValidatedPayload)` contract with approved Mitel endpoints and authentication.
The validator and the policy engine do not change.
