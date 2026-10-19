# Five-minute Innovation Day demo

**Message:** before AI sees communication data, the firewall decides what AI is allowed to see,
process and send, and it proves the decision in the audit trail.

## Before the audience arrives

1. Start the three services (`scripts\start-demo.ps1`, or the commands in the README).
2. Optional: start Ollama with the model pulled (`ollama pull llama3.2:3b`) so local summaries
   are generated. Without it, the demo still works and shows an honest "Unavailable" status.
3. Open http://localhost:4200 and check that the top bar shows **Firewall active**.
4. For a clean dashboard, stop the backend, delete `backend/data/firewall.db`, and start it
   again. Policies are re-seeded automatically.

## 0:00 - Overview (30 s)

- "This is one governance boundary between communication workloads and every AI service."
- Point to the system status card: the firewall is enforcing, the local model status is real,
  and CloudLink is clearly labelled **Mock**.
- Select **Inspect Transcript**.

## 0:30 - Redacted and sent (90 s)

1. Sample: **Appointment request (standard)**, then **Load sample**. Mode: **Full pipeline**.
   Select **Process**.
2. **Final decision: REDACTED.** Walk the processing sequence left to right: Received,
   Analyzed, Policy evaluated, Protected, Local AI / Cloud, Audited.
3. **Before and after:** `John Smith` becomes `[PERSON]` and `48291` becomes `[PATIENT_ID]`.
   The patient ID is found by a custom recognizer; a bare number would not be.
4. **Detected sensitive entities:** category, confidence, position and the rule that decided.
5. **Local AI summary** tab: the model only ever received the protected text. If Ollama is
   down, say so: "No fabricated answer, and no fallback to a cloud model."
6. **Cloud handoff** tab: six validation checks passed, then the **exact payload** that was
   sent and the **mock receiver's real response** with a receipt ID.

## 2:00 - Same transcript, local only (45 s)

1. Change **Policy profile** to **Healthcare PHI local-only** (or load the healthcare sample),
   then **Process**.
2. **LOCAL ONLY.** The summary may run locally. The Cloud handoff tab reads **Not authorized**
   and "No data reached the CloudLink receiver."
3. "The broad baseline ALLOW rule still exists. It cannot override the more restrictive rule."

## 2:45 - Same transcript, blocked (30 s)

1. Profile **Restricted lockdown**, then **Process**.
2. **BLOCKED.** The Local AI / Cloud step is red: no model call and no outbound request.
   Total time is a few milliseconds, because nothing left the firewall.

## 3:15 - Change policy live (60 s)

1. Open **Policy Management** and explain the four precedence rules on the page.
2. Disable **Baseline sanitized cloud handoff** with its switch.
3. Back in the Inspector, run **General question (no sensitive data)**. Result: **BLOCKED**,
   because no enabled policy permits it (deny by default).
4. Re-enable the baseline rule. The change persists in the database; no code changes.

## 4:15 - Audit trail (45 s)

1. Open **Audit Trail** and filter **Decision = Blocked**.
2. Open an event. Point out the categories and counts (`PERSON x1`, `PATIENT_ID x1`), the
   decisive rule, the policy-set version and the measured latency per stage.
3. "No transcript text and no detected values are stored. Only the facts needed to explain the
   decision."

## Likely questions

- **Is detection perfect?** No. Settings lists every recognizer's limitations, and the policy
  handles uncertainty conservatively: uncovered entities stay local.
- **What if the model repeats a name?** The outbound validator re-checks the final payload for
  protected values and re-scans it. On failure nothing is sent (`VALIDATION_FAILED`).
- **Is this connected to CloudLink?** No. It is a mock receiver behind an adapter designed
  to be swapped for an approved integration.
- **Can the UI force a decision?** No. The API rejects unknown fields, and the backend
  recomputes every decision.
