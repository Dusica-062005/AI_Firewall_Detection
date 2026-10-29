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

## Quick start (all commands)

Windows PowerShell, starting from the `AI_Firewall_Detection` folder. Details for each step are
in [Setup](#setup) and [Running](#running).

### First time only

```powershell
# Backend: virtual environment, dependencies, spaCy model, settings
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m spacy download en_core_web_md
Copy-Item .env.example .env        # then set CLOUDLINK_API_KEY in backend\.env
cd ..

# Frontend: dependencies
cd frontend
npm install --legacy-peer-deps
cd ..

# Ollama (optional, for local AI summaries)
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

### Every time: start the app

One command (opens three windows):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1
```

Or start each process in its own terminal:

```powershell
# Terminal 1: mock CloudLink receiver (port 8100)
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.integrations.mock_cloudlink:app --host 127.0.0.1 --port 8100

# Terminal 2: firewall backend (port 8000)
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 3: Angular UI (port 4200)
cd frontend
npx ng serve --port 4200
```

If Ollama is installed but not running, start it with `ollama serve`.

Then open http://localhost:4200. Check http://localhost:8000/api/health if the UI reports the
backend as unreachable. Stop everything with `Ctrl+C` in each window.

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

### 3. Ollama 

1. Install Ollama from https://ollama.com/download.
2. Pull the configured model and make sure the service is running:

   ```powershell
   ollama pull llama3.2:3b
   ollama pull nomic-embed-text    # about 270 MB; only for the dial quality score (Measurements)
   ollama list
   ```

3. To use a different model, set `OLLAMA_MODEL` in `backend/.env`.
4. Cloud stand-in (Feature 4, section 3 of the project document): "cloud" is played by a larger
   local model than the local path. `ollama pull llama3.1:8b` (about 4.7 GB), then set
   `MOCK_CLOUD_MODEL=llama3.1:8b` and `CLOUDLINK_TIMEOUT_SECONDS=150` in `backend/.env` and restart
   the backend and the mock receiver. The receiver then summarizes the tokenized transcript with
   the 8B model, and the dial quality measurement compares local (3B) and cloud (8B) summaries on
   the same tokenized input. Leave `MOCK_CLOUD_MODEL` empty to switch it off.

### 4. Local transcription (audio)

`pip install -r requirements.txt` installs faster-whisper (CTranslate2, no torch), a pinned PyAV
(`av==14.2.0`; faster-whisper 1.2.1 does not work with PyAV 15+), python-multipart, psutil and
pyttsx3. The Whisper model (`WHISPER_MODEL=base`, about 145 MB) downloads once on the first audio
request and then works offline. Audio is processed from a temp file that is deleted right away;
it is never stored or sent.

To recreate the synthetic test recordings (offline Windows speech engine):

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\make_synthetic_audio.py
```

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
| `WHISPER_MODEL` / `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` | `base` / `cpu` / `int8` | Local transcription (faster-whisper) |
| `MAX_AUDIO_SECONDS` / `MAX_AUDIO_BYTES` | `300` / `26214400` | Audio upload limits (only the audio routes accept large bodies); `MAX_AUDIO_SECONDS` also ends a live call |
| `LIVE_CHUNK_SECONDS` / `LIVE_WINDOW_CHUNKS` | `4` / `3` | Live captions: seconds of audio per caption, and how many recent chunks detection looks back over |
| `BLEEP_STYLE` | `tone` | Audio bleeping of protected words: `tone` (1 kHz) or `silence` |
| `LIVE_ASSIST_BUDGET_S` / `POST_CALL_BUDGET_S` | `5` / `60` | Benchmark verdict and sizing budgets |
| `AUTO_DRAFT_BREACH_REPORTS` | `true` | Draft a breach report automatically when a canary run leaks or a receipt shows a protected value left |
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

There are two canary sets: **main** (200 calls) and **held-out** (100 calls from different
templates). Use the held-out set to check that a detection change generalizes; never tune
recognizers against its misses. Both are generated deterministically and committed. To
regenerate them after changing the templates (the output is byte-identical for the same script):

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\generate_canaries.py              # both sets
.\.venv\Scripts\python.exe scripts\generate_canaries.py --set holdout
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

## Audio, benchmark, sizing and breach reports

- **Audio (Inspector > Audio):** upload a synthetic `.wav`, `.mp3` or `.m4a`. It is transcribed
  locally, then processed like text. With "Bleep protected words" (WAV only) the response also
  contains the recording with every tokenized value replaced by a tone.
- **Live call (Inspector > Live call):** speak into the microphone, or stream a recording at
  real-time pace as a reliable demo. Audio goes over a WebSocket to the local backend, is
  transcribed in chunks (`LIVE_CHUNK_SECONDS`), and captions appear with names, IDs and every
  5+ digit number already replaced. Detection looks back over the last `LIVE_WINDOW_CHUNKS` chunks,
  so a value split across chunks is caught and earlier captions are corrected. Captions never leave
  the computer and are not stored. Nothing reaches the local model, the cloud, the audit trail or a
  receipt until you select End call: then the whole call is transcribed and processed once, like
  an uploaded file (summary, routing, receipt and optional bleep). Each step shows with its time,
  and the final protected transcript appears within seconds while the AI summaries (most of the
  wait on a CPU) are still running. Cancel processes nothing. If
  detection fails, the caption is withheld instead of shown raw.
- **Benchmark (Measurements > Benchmark):** times the real pipeline per stage (n, p50, p95) and
  throughput per concurrency level on this machine, and gives the NFR-2 verdict: real-time capable
  (warm p95 within `LIVE_ASSIST_BUDGET_S`) or post-call wrap-up. Each call also writes an audit
  event and a receipt.
- **Hardware Fit (sidebar):** enter seats and calls per hour. The answer comes only from a
  completed benchmark, with the formula, the run ID and the caveats; with no benchmark it says
  "Not measured yet". It never extrapolates to hardware or models that were not benchmarked.
- **Breach reports (Compliance > Breach reports):** draft a report from a canary run with leaks,
  a data-exposure incident or a time window. Drafts hold categories, counts and IDs only, carry
  "DRAFT for compliance review. Not filed. Not legal advice.", and can be verified against the
  records, reviewed, linked to an incident and downloaded as Markdown. Nothing is ever sent.
  A canary run with leaks drafts one automatically.
- **Audit evidence export (Audit Trail > Export evidence):** every audit event in the chosen range,
  their signed receipts and a chain verification, as JSON (or CSV for spreadsheets), for an auditor.
- **Local model down:** cloud egress fails closed too (NFR-5); detection and redaction still work.

**Roadmap (not built):** a real Mitel Edge / CloudLink integration (the receiver is a mock), real
telephony integration (live captions take the browser microphone, not a phone line), and
protection against re-identification from quasi-identifiers ("the only cardiologist in a small
town ...").

### Manual verification (Milestone C)

1. Start everything: `powershell -ExecutionPolicy Bypass -File scripts\start-demo.ps1`
2. Inspector > Audio: upload `backend/tests/fixtures/audio/appointment.wav` with bleeping on and
   select Transcribe and process. Expect the transcript, `[PERSON_1]` and `[PATIENT_ID_1]`, and a
   receipt whose body has an `audio` block. In the playback, the name and the ID are beeped.
3. Measurements > Benchmark: run it. Note the warm p95 and the verdict.
4. Hardware Fit: 300 seats and 1,200 calls/hour. The numbers in the formula match the benchmark
   table.
5. Measurements > Leak canaries: run the main and the held-out set and compare with Milestone B's
   numbers.
6. Compliance > Breach reports: draft from the canary run with leaks, select Verify (expect every
   count to match) and download the Markdown. Search it for a raw value: there is none outside the
   synthetic appendix.
7. Trust & Controls > Verify chain: CHAIN OK.
8. Inspector > Live call: stream `backend/tests/fixtures/audio/appointment.wav` (or speak "my name
   is John Smith, my patient ID is P 9482913"). Captions show `[PERSON_1]` and `[PATIENT_ID_1]`;
   the raw values never appear. Select End call (the recording ends it by itself): the full result
   and one receipt follow. Start again and select Cancel: no receipt is added.

## Tests

```powershell
# Backend: 286 tests (unit, integration, security). Uses real Presidio, a stub Ollama, a stub
# transcriber and the in-process mock receiver. No network or credentials needed. One test
# (marked slow) runs real faster-whisper and is skipped when the model is not cached.
cd backend
.\.venv\Scripts\python.exe -m pytest

# Frontend: 27 tests (Vitest via the Angular unit-test builder).
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
| `tests/integration/test_audio.py` | Transcription through the pipeline; receipts and audit hold only audio facts; temp file deleted on success and error; failures process and send nothing; size limits |
| `tests/integration/test_bleep.py` | Bleep ranges from word timings; only protected ranges change; WAV-only check before anything runs |
| `tests/integration/test_benchmark.py` | Nearest-rank percentiles; cold call separated; verdict flips at the budget; failed stages recorded; transcription timed |
| `tests/integration/test_sizing.py` | Exact formula and ceil boundaries; live vs post-call; failed levels never used; no benchmark means no numbers |
| `tests/security/test_breach_reports.py` | Counts match records; no raw values outside the synthetic appendix; DRAFT watermark; verify detects a changed record; nothing sent |
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
    audio/          local transcription (faster-whisper) and audio bleeping
    benchmark/      latency benchmark of the real pipeline
    sizing/         Hardware Fit Calculator
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
