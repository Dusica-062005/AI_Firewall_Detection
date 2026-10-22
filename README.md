# Mitel AI Data Firewall

A locally runnable Innovation Day prototype of a privacy and AI governance gateway for
communication workloads.

> Before AI sees communication data, Mitel AI Data Firewall decides what AI is allowed to see,
> process and send.

The firewall accepts a synthetic transcript and processes it in this order:

1. Detect sensitive entities (Microsoft Presidio plus custom recognizers).
2. Evaluate the stored policy set, deterministically: the most restrictive rule wins.
3. Redact the transcript, then verify the redaction.
4. Summarize with a local Ollama model, only when policy allows it.
5. Hand a validated, sanitized payload to a mock CloudLink receiver, only when policy allows it.
6. Record a privacy-safe audit event.

The Angular UI shows every step, decision and measured latency.

This is a prototype. It uses synthetic data, a mock CloudLink integration and plain HTTP on
localhost. It has not had a formal security review. See [docs/threat-model.md](docs/threat-model.md).

## Contents

- [Architecture](docs/architecture.md): components, processing sequence, policy precedence, data handling
- [API contract](docs/api-contract.md): endpoints, schemas, real request and response examples
- [Threat model](docs/threat-model.md): threats, mitigations, the tests that verify them, known limits
- [Demo script](docs/demo-script.md): the five-minute Innovation Day walkthrough

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11 - 3.14 | Verified with 3.14.6 on Windows 11 |
| Node.js | 22 LTS | Verified with 22.23.1 and npm 10.9.8 |
| Angular CLI | 22 | Installed locally by `npm install`; use `npx ng` |
| Ollama | optional | Needed only for local summaries. Detection and policy work without it. |
| Docker | optional | Only for the Compose alternative |

## Setup

Run these commands from the repository root. The examples use Windows PowerShell; macOS and
Linux equivalents are noted.

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m spacy download en_core_web_md
Copy-Item .env.example .env        # macOS/Linux: cp .env.example .env
```

On macOS or Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe`.

Edit `backend/.env` and replace `CLOUDLINK_API_KEY` with any local secret. The firewall and the
mock receiver read the same value.

#### Presidio configuration

- The spaCy model is set by `SPACY_MODEL` (default `en_core_web_md`, about 40 MB).
  `en_core_web_lg` is more accurate. Install it with `python -m spacy download en_core_web_lg`
  and set `SPACY_MODEL=en_core_web_lg`.
- Entity categories, Presidio mappings and custom recognizers are in
  `backend/app/policies/detection.yaml`. Restart the backend after editing.
- `DETECTION_SCORE_THRESHOLD` (default 0.35) drops weaker matches. Entities below
  `DETECTION_LOW_CONFIDENCE_THRESHOLD` (0.6) are flagged as low confidence, and they are
  still protected.

### 2. Frontend

```powershell
cd frontend
npm install --legacy-peer-deps
```

`--legacy-peer-deps` works around an npm 10 resolver error ("Cannot read properties of null
(reading 'edgesOut')") seen with the Angular 22 packages.

The API location is read at runtime from `frontend/public/config.json`:

```json
{ "apiBaseUrl": "http://localhost:8000/api" }
```

### 3. Ollama (optional)

1. Install Ollama from https://ollama.com/download.
2. Pull the configured model and make sure the service is running:

   ```powershell
   ollama pull llama3.2:3b
   ollama pull nomic-embed-text    # about 270 MB; only for the dial quality score (Measurements)
   ollama list
   ```

3. To use a different model, set `OLLAMA_MODEL` in `backend/.env`.

If Ollama is missing, not running, or the model is not pulled, the UI reports
`Unreachable` or `Model missing` and summaries show as unavailable. The firewall never falls
back to any other model.

## Environment variables

All settings live in `backend/.env`; see [backend/.env.example](backend/.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `CORS_ORIGINS` | `http://localhost:4200` | Allowed browser origins (comma-separated) |
| `DATABASE_URL` | `sqlite:///./data/firewall.db` | Policies and audit metadata |
| `AUDIT_RETENTION_DAYS` | `30` | Older audit events are purged on start or on demand |
| `MAX_TRANSCRIPT_CHARS` / `MAX_REQUEST_BYTES` | `10000` / `65536` | Input limits |
| `SPACY_MODEL` | `en_core_web_md` | spaCy model used by Presidio |
| `EXPOSE_DETECTED_VALUES` | `true` | Return detected values to the Inspector (synthetic demo only; never stored) |
| `UNMATCHED_ENTITY_ACTION` | `LOCAL_ONLY` | Action for detected entities no policy covers (`LOCAL_ONLY` or `BLOCK`) |
| `NORMALIZE_NUMBERS` | `true` | Detect spoken and split identifiers ("P four eight two", "nau aath saat", "P48. Sorry, 2913") |
| `QUALITY_EMBED_MODEL` / `QUALITY_REFERENCE_MODEL` | `nomic-embed-text` / empty | Dial quality score: embedding model, and the model that summarizes the raw samples (empty: `MOCK_CLOUD_MODEL`, else `OLLAMA_MODEL`) |
| `RECEIVED_LOG_FILE` | `./data/received.log` | Every payload the mock receiver accepts; leak canaries measure against it |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `OLLAMA_TIMEOUT_SECONDS` | `http://localhost:11434` / `llama3.2:3b` / `45` | Local model |
| `CLOUDLINK_BASE_URL` / `CLOUDLINK_API_KEY` / `CLOUDLINK_TIMEOUT_SECONDS` | `http://localhost:8100` / placeholder / `5` | Mock receiver |
| `ADMIN_API_KEY` | empty | When set, policy changes and audit purge require the `X-Admin-Key` header (enter it on the Settings page) |

## Database initialization

Nothing to run manually. On start, the backend creates `backend/data/firewall.db`
(`SQLAlchemy metadata.create_all`). If the policy table is empty, it seeds it from
`backend/app/policies/default.yaml`. Policies and audit events persist across restarts.
To start fresh, stop the backend and delete the `backend/data` folder. **Reset to defaults**
on the Policies page re-seeds the policies without touching the audit trail.

## Running

Start three processes. The helper script opens each one in its own window:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1
```

Or run them manually, in three terminals:

```powershell
# 1. Mock CloudLink receiver (simulated integration, separate process)
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.integrations.mock_cloudlink:app --host 127.0.0.1 --port 8100

# 2. Firewall backend
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. Angular UI
cd frontend
npx ng serve --port 4200
```

| URL | What |
|---|---|
| http://localhost:4200 | Angular UI |
| http://localhost:8000/api/health | Firewall health |
| http://localhost:8000/docs | Interactive API documentation |
| http://localhost:8100/health | Mock CloudLink receiver (simulated) |
| http://localhost:11434 | Ollama (optional) |

### Docker Compose (optional)

```powershell
$env:CLOUDLINK_API_KEY = "a-local-secret"
docker compose up --build
```

This starts the mock receiver, the backend and an nginx-served UI on the same ports. Ollama is
expected on the host. The Compose file passes `docker compose config` validation, but the
images were not built in the development environment (the Docker daemon was not running), so
treat this path as unverified.

## Measurements (leak canaries, languages, dial quality)

The **Measurements** page turns protection claims into stored, measured numbers. Every number
comes from a stored run and is shown with its sample size (n), run ID, rule version and machine.
With no run, the page says "Not measured yet".

- **Leak canaries:** 200 synthetic hospital calls with planted fake identities (English,
  Hinglish, Hindi, Kannada and Tamil, in Latin and native scripts; plain, spelled digits, split
  IDs and mixed). Each batch runs every call through the real pipeline and reports detection
  recall and the leak rate measured at the mock receiver.
- **Languages:** recall and leak rate per language and script from the latest canary run.
- **Dial quality:** similarity of each dial position's summary to the raw-text summary
  (needs `ollama pull nomic-embed-text`). It is a similarity number, not a human quality rating.

Run a canary batch from the UI (Measurements > Leak canaries > Run canary batch), or with the API:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/canaries/runs -ContentType 'application/json' -Body '{"normalize_on": true}'
Invoke-RestMethod http://localhost:8000/api/canaries/runs
```

The canary set is generated deterministically and committed. To regenerate it after changing the
templates (the output is byte-identical for the same script):

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\generate_canaries.py
```

Canary batches go through the real pipeline, so each call also writes an audit event and a
signed receipt (request ID `{run_id}-{call_id}`). Leaks are read from `RECEIVED_LOG_FILE`; the
mock receiver and the backend must use the same file, otherwise the run fails rather than
reporting a leak rate it did not measure.

### Manual verification

1. Start everything: `powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1`
2. Inspector: paste "My patient ID is P nine four eight two nine one three, call me." and
   Process. Expect `[PATIENT_ID_1]` covering the spoken digits.
3. Measurements > Leak canaries: run once with "Normalize spoken numbers" off, once on, then
   compare. The spelled_digits and split_id rows should improve.
4. Check the leak rate against what really reached `backend/data/received.log`: open the file
   and search for a value from the leaks table.
5. Trust & Controls > kill switch on > run canaries again. Expect 0 payloads sent and a leak
   rate of 0. Turn it off.
6. Measurements > Dial quality: run it. Scores appear per position, and the Trust & Controls
   dial card shows them.
7. Verify the receipt chain still says CHAIN OK. Canary runs add one receipt per call, each
   recording `normalize_on`.

## Tests

```powershell
# Backend: 188 tests (unit, integration, security). Uses real Presidio, a stub Ollama
# and the in-process mock receiver. No network or credentials needed.
cd backend
.\.venv\Scripts\python.exe -m pytest

# Frontend: 19 tests (Vitest via the Angular unit-test builder).
cd frontend
npx ng test --watch=false

# Frontend production build
npx ng build
```

| Test file | Covers |
|---|---|
| `tests/unit/test_detection.py` | Names and patient IDs; multiple entities; bare numbers ignored; overlap resolution; repeated values |
| `tests/unit/test_redactor.py` | Correct span replacement; overlapping or mismatched spans rejected; leftover values rejected |
| `tests/unit/test_policy_engine.py` | Broad ALLOW cannot override; LOCAL_ONLY and BLOCK precedence; deny by default; conditions; determinism; the three seed outcomes |
| `tests/unit/test_policy_validation.py` | Invalid policies and policy files rejected |
| `tests/unit/test_ollama.py` | Missing model, timeout, unreachable, empty or oversized output; no fabricated success |
| `tests/security/test_outbound_enforcement.py` | Permitted payloads reach the receiver; blocked, local-only and failure cases never do; client-supplied decisions rejected; tampering refused |
| `tests/security/test_audit_privacy.py` | No raw values in the database, audit API, logs or validation errors |
| `tests/integration/test_api.py` | Invalid and oversized requests; policy CRUD and live effect; persistence across restarts; admin key; audit filters; metrics; CORS; config secrecy |
| `tests/unit/test_normalizer.py` | Spoken English and Hindi digits, double/triple, native-script digits, split IDs, span mapping; normalization off keeps the old behaviour |
| `tests/unit/test_canary_set.py` | Canary file format, exact spans, coverage minimums, byte-identical regeneration |
| `tests/security/test_canaries.py` | Exact recall and leak rate on a hand-checked set; leaks measured at the real receiver; log mismatch fails the run; kill switch; determinism; compare deltas; admin key |
| `tests/integration/test_quality.py` | Cosine scores, reference cache, null (not 0) without a summary, missing embedding model, raw text never reaches the mock cloud |
| `frontend/src/**/*.spec.ts` | Error normalization; unreachable backend; validation errors; unavailable metrics; missing model; blocked result rendering |

## Five-minute demo

A quick version is below. The full script with talking points is in
[docs/demo-script.md](docs/demo-script.md).

1. **Overview:** firewall status, local model status and the Mock CloudLink label.
2. **Inspector, standard profile:** the result is **REDACTED**. `John Smith` becomes
   `[PERSON]` and `48291` becomes `[PATIENT_ID]`. The Cloud handoff tab shows the validation
   checks, the exact payload and the mock receiver's receipt.
3. **Healthcare profile:** **LOCAL ONLY**. The local summary may run, and nothing is sent to
   the cloud.
4. **Restricted profile:** **BLOCKED**. There is no model call and no outbound request.
5. **Policies:** disable the baseline rule and rerun the general question. It is **BLOCKED**
   by deny-by-default. Re-enable the rule afterwards.
6. **Audit Trail:** open an event to show categories, counts, the decisive rule and stage
   latency. No transcript text is stored.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Top bar says **Backend unreachable** | The backend is not running on port 8000, or `frontend/public/config.json` points elsewhere. |
| Detection shows **UNAVAILABLE**; requests return `PROCESSING_FAILED` | The spaCy model is not installed. Run `python -m spacy download en_core_web_md` in the backend venv. This state is fail-closed by design. |
| Local AI **Unreachable** | Ollama is not running. Start it, or continue the demo without summaries. |
| Local AI **Model missing** | Run `ollama pull <OLLAMA_MODEL>`. |
| Local AI **Timeout** | The first call loads the model into memory. Retry, or raise `OLLAMA_TIMEOUT_SECONDS`. |
| Summary step takes about 2 s even though Ollama is off | On Windows, refusing a connection to a closed localhost port takes about 2 seconds. This is real measured latency; start Ollama or ignore it. |
| Cloud handoff **Unavailable** | The mock receiver is not running on port 8100. |
| Cloud handoff **Rejected** (401) | `CLOUDLINK_API_KEY` differs between the two processes. Both read `backend/.env`; restart both. |
| Policy changes return 401 | `ADMIN_API_KEY` is set. Enter it under **Settings > Administrator access**. |
| `npm install` fails with `edgesOut` | Use `npm install --legacy-peer-deps`. |
| CORS error in the browser console | The UI origin is not in `CORS_ORIGINS`. Add it and restart the backend. |
| `Port 4200 is already in use` | Stop the other dev server, or run `npx ng serve --port 4300` and add `http://localhost:4300` to `CORS_ORIGINS`. |

## Repository layout

```
backend/
  app/
    api/            routes, middleware (request IDs, limits, logging), errors, deps
    schemas/        Pydantic request/response models
    services/       firewall_service (enforcement), processing_service (workflow), policy_service
    detection/      Presidio analyzer wrapper, custom recognizers, spoken-number normalizer
    canaries/       canary set (canaries.json), models and the leak-canary runner
    quality/        dial quality measurement (embedding similarity)
    policy/         engine (decisions), models, loader, validation
    security/       redactor, outbound_validator
    ai/             ollama_client, summarizer
    integrations/   cloudlink_client (adapter), mock_cloudlink (separate receiver), contracts
    audit/          audit service and metrics
    db/             SQLAlchemy models, session, repositories
    policies/       default.yaml (seed policies), detection.yaml (recognizers)
  tests/            unit, integration, security
frontend/src/app/
  core/             models, API service, interceptors, runtime config, status and notifications
  layout/           sidebar, topbar, main layout
  shared/           status badge, dialogs, alerts, chart, pipes, icon registry
  features/         overview, inspector, policies, audit, settings
docs/               architecture, API contract, threat model, demo script
scripts/            start-demo.ps1
```
