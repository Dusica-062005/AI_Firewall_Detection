"""Breach Report Generator (Feature 8, FR-11). It DRAFTS reports; it never sends or files anything.

A draft is built only from stored records: signed receipts, leak-canary runs and incidents.
It holds categories, counts and IDs, never transcript text or entity values. For a canary run,
the synthetic surface text of the leaked test values may appear in an appendix labelled
"synthetic test data".

The selection (``query``) is stored on the report, so ``verify`` can recompute every count from
the records and show any difference. The receipt chain is verified at draft time and again on
verify.

Sources:
- canary_run: the planted values a completed canary run measured as leaked at the receiver.
- incident: the receipt of the incident's linked audit event (plus an optional time window).
- window: receipts in a time window where a protected value left the firewall, or where a
  category allowed by policy was sent to the cloud.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import BreachReportRecord, CanaryRunRecord, ReceiptRecord
from app.db.repositories import utcnow
from app.schemas.compliance import IncidentCreate

WATERMARK = "DRAFT for compliance review. Not filed. Not legal advice."
REGULATORS = [
    {"framework": "GDPR (EU)", "note": "Article 33: notify the supervisory authority without undue delay and, where "
     "feasible, within 72 hours of becoming aware, unless the breach is unlikely to result in a risk to individuals."},
    {"framework": "DPDP Act 2023 (India)", "note": "Notify the Data Protection Board and each affected Data "
     "Principal; form and timing are set by the DPDP Rules."},
    {"framework": "HIPAA Breach Notification Rule (US)", "note": "Notify affected individuals without unreasonable "
     "delay and no later than 60 days after discovery; HHS and, for 500 or more people in a state, the media."},
]
REGULATOR_NOTE = "Directional only, not legal advice. Confirm obligations with legal counsel before any notification."
# Fields that must be recomputable from the records; verify compares exactly these.
COUNTED = ("affected_requests", "categories", "reasons", "routes", "kill_switch", "dials", "receipt_ids", "window")


class ReportSourceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


class BreachReportService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        receipts,  # ReceiptService
        incidents,  # IncidentService
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sessions = sessions
        self._receipts = receipts
        self._incidents = incidents
        self._clock = clock

    # ---- Drafting ---------------------------------------------------------------------------

    def draft(self, source: str, ref: str | None = None, start: datetime | None = None,
              end: datetime | None = None, trigger: str = "manual") -> BreachReportRecord:
        """``trigger`` is "manual" (a person asked) or "auto" (monitoring detected an exposure)."""
        query = {"source": source, "ref": ref, "from": start.isoformat() if start else None,
                 "to": end.isoformat() if end else None, "trigger": trigger}
        counted, appendix = self._compute(query)
        if source == "canary_run" and not counted["affected_requests"]:
            raise ReportSourceError("NO_LEAKS", "This canary run measured no leaks, so there is nothing to report.")
        incident = self._incidents.get(ref) if source == "incident" else None
        content = self._content(query, counted, appendix, incident)
        now = self._clock()
        record = BreachReportRecord(
            report_id=f"brr-{uuid.uuid4().hex[:12]}", status="DRAFT", created_at=now, updated_at=now,
            source_type=source, source_ref=ref, query=query, content=content,
            incident_id=incident.incident_id if incident else None,
        )
        with self._sessions.begin() as s:
            s.add(record)
        return record

    def _compute(self, query: dict) -> tuple[dict, list[dict]]:
        """Select the affected records and count them. Returns (counted fields, synthetic appendix)."""
        source = query["source"]
        appendix: list[dict] = []
        leaked_types: Counter | None = None
        if source == "canary_run":
            run = self._canary_run(query["ref"])
            leaked_calls = {f"{run.run_id}-{leak['call_id']}" for leak in run.leaks or []}
            selected = [(r, b) for r, b in self._all_receipts() if r.request_id in leaked_calls]
            leaked_types = Counter(leak["type"] for leak in run.leaks or [])
            appendix = [{"call_id": l["call_id"], "type": l["type"], "field": l["field"], "surface": l["surface"]}
                        for l in run.leaks or []]
            reasons = Counter({"LEAK_MEASURED_AT_RECEIVER": len(leaked_calls)}) if leaked_calls else Counter()
        else:
            selected = []
            if source == "incident":
                incident = self._incidents.get(query["ref"])
                if incident is None:
                    raise ReportSourceError("INCIDENT_NOT_FOUND", "Incident not found.")
                if incident.related_event_id:
                    selected = [(r, b) for r, b in self._all_receipts() if b.get("event_id") == incident.related_event_id]
            if query["from"] and query["to"]:
                start, end = datetime.fromisoformat(query["from"]), datetime.fromisoformat(query["to"])
                seen = {r.receipt_id for r, _ in selected}
                selected += [
                    (r, b) for r, b in self._all_receipts()
                    if r.receipt_id not in seen and start <= _aware(r.created_at) <= end and self._exposed(b)
                ]
            reasons = Counter(self._reason(b) for _, b in selected)

        categories: Counter = Counter()
        for _, body in selected:
            if body.get("protected_values_left"):
                categories.update(body.get("entity_counts", {}).keys())
            categories.update(body.get("allowed_categories_sent", []))
        if leaked_types is not None:
            categories = leaked_types  # what was measured as leaked, by planted type
        times = sorted(_aware(r.created_at).isoformat() for r, _ in selected)
        counted = {
            "affected_requests": len({r.request_id for r, _ in selected}) if source != "canary_run"
            else sum(reasons.values()),
            "categories": dict(sorted(categories.items())),
            "reasons": dict(sorted(reasons.items())),
            "routes": dict(sorted(Counter(b.get("route", "NONE") for _, b in selected).items())),
            "kill_switch": dict(sorted(Counter("on" if b.get("kill_switch") else "off" for _, b in selected).items())),
            "dials": dict(sorted(Counter(b.get("dial", "-") for _, b in selected).items())),
            "receipt_ids": sorted(r.receipt_id for r, _ in selected),
            "window": {"first": times[0] if times else None, "last": times[-1] if times else None},
        }
        return counted, appendix

    @staticmethod
    def _exposed(body: dict) -> bool:
        return bool(body.get("protected_values_left")) or (bool(body.get("cloud_sent")) and bool(body.get("allowed_categories_sent")))

    @staticmethod
    def _reason(body: dict) -> str:
        if body.get("protected_values_left"):
            return "PROTECTED_VALUE_LEFT"
        if body.get("cloud_sent") and body.get("allowed_categories_sent"):
            return "ALLOWED_CATEGORY_SENT"
        return "LINKED_EVENT"

    def _content(self, query: dict, counted: dict, appendix: list[dict], incident) -> dict:
        chain = self._receipts.verify()
        n = counted["affected_requests"]
        cats = ", ".join(f"{k} x{v}" for k, v in counted["categories"].items()) or "none"
        what = {
            "canary_run": f"Leak-canary run {query['ref']} measured {n} synthetic test call(s) whose planted values "
                          f"reached the mock CloudLink receiver. Categories: {cats}.",
            "incident": f"Incident {query['ref']}: {n} linked request(s) found in the signed receipts. Categories: {cats}.",
            "window": f"Between {query['from']} and {query['to']}, {n} request(s) sent data to the cloud stand-in "
                      f"that a reviewer should assess. Categories: {cats}.",
        }[query["source"]]
        return {
            "watermark": WATERMARK,
            "auto_drafted": query.get("trigger") == "auto",
            "title": f"Draft breach report: {query['source'].replace('_', ' ')} {query['ref'] or ''}".strip(),
            "what_happened": what,
            **counted,
            "chain": {"ok": chain.ok, "count": chain.count, "reason": chain.reason},
            "incident": self._incident_info(incident),
            "regulators": REGULATORS,
            "regulator_note": REGULATOR_NOTE,
            "synthetic_appendix": appendix,
            "privacy": "Categories, counts and IDs only: no transcript text or entity values.",
        }

    @staticmethod
    def _incident_info(incident) -> dict | None:
        if incident is None:
            return None
        return {"incident_id": incident.incident_id, "status": incident.status, "severity": incident.severity,
                "contained_at": incident.contained_at.isoformat() if incident.contained_at else None,
                "sla_state": incident.sla_state}

    # ---- Automatic drafts (Feature 8: "automatically drafts a report") -------------------------

    def auto_draft_for_canary_run(self, run_id: str) -> BreachReportRecord | None:
        """Draft once for a canary run that measured leaks. Returns None when there is nothing to do."""
        if self.for_source("canary_run", run_id) is not None:
            return None
        try:
            return self.draft("canary_run", run_id, trigger="auto")
        except ReportSourceError:
            return None  # no leaks, or the run is not completed: nothing to report

    def auto_draft_for_receipt(self, receipt: ReceiptRecord) -> BreachReportRecord | None:
        """Draft for one receipt that shows a protected value left the firewall."""
        at = _aware(receipt.created_at)
        return self.draft("window", None, at, at, trigger="auto")

    def for_source(self, source: str, ref: str) -> BreachReportRecord | None:
        with self._sessions() as s:
            return s.scalars(
                select(BreachReportRecord).where(
                    BreachReportRecord.source_type == source, BreachReportRecord.source_ref == ref
                ).limit(1)
            ).first()

    # ---- Verification, review and incident link -----------------------------------------------

    def verify(self, report_id: str) -> dict | None:
        record = self.get(report_id)
        if record is None:
            return None
        try:
            counted, _ = self._compute(record.query)
        except ReportSourceError as exc:
            return {"ok": False, "mismatches": [{"field": "source", "report": record.query, "records": exc.message}],
                    "chain": None}
        mismatches = [
            {"field": f, "report": record.content.get(f), "records": counted[f]}
            for f in COUNTED if record.content.get(f) != counted[f]
        ]
        chain = self._receipts.verify()
        return {"ok": not mismatches and chain.ok, "mismatches": mismatches,
                "chain": {"ok": chain.ok, "count": chain.count, "reason": chain.reason}}

    def review(self, report_id: str, reviewer: str, decision: str, note: str) -> BreachReportRecord | None:
        with self._sessions.begin() as s:
            record = s.get(BreachReportRecord, report_id)
            if record is None:
                return None
            now = self._clock()
            record.status, record.reviewer, record.reviewed_at, record.review_note = decision, reviewer, now, note
            record.updated_at = now
        return self.get(report_id)

    def create_incident(self, report_id: str) -> BreachReportRecord | None:
        record = self.get(report_id)
        if record is None:
            return None
        event_id = next((b.get("event_id") for r, b in self._all_receipts()
                         if r.receipt_id in set(record.content["receipt_ids"]) and b.get("event_id")), None)
        incident = self._incidents.create(IncidentCreate(
            title=f"Data exposure: {record.content['affected_requests']} request(s), report {report_id}"[:120],
            description=f"{record.content['what_happened']} See draft breach report {report_id}."[:2000],
            incident_type="DATA_EXPOSURE", severity="HIGH", related_event_id=event_id,
        ))
        with self._sessions.begin() as s:
            stored = s.get(BreachReportRecord, report_id)
            stored.incident_id = incident.incident_id
            stored.content = {**stored.content, "incident": self._incident_info(incident)}
            stored.updated_at = self._clock()
        return self.get(report_id)

    # ---- Records ----------------------------------------------------------------------------

    def _all_receipts(self) -> list[tuple[ReceiptRecord, dict]]:
        return [(r, json.loads(r.body)) for r in self._receipts.all()]

    def _canary_run(self, run_id: str | None) -> CanaryRunRecord:
        with self._sessions() as s:
            run = s.get(CanaryRunRecord, run_id) if run_id else None
        if run is None:
            raise ReportSourceError("CANARY_RUN_NOT_FOUND", "Canary run not found.")
        if run.status != "COMPLETED":
            raise ReportSourceError("CANARY_RUN_NOT_COMPLETED", "The canary run is not completed.")
        return run

    def list(self) -> list[BreachReportRecord]:
        with self._sessions() as s:
            return list(s.scalars(select(BreachReportRecord).order_by(BreachReportRecord.created_at.desc())).all())

    def get(self, report_id: str) -> BreachReportRecord | None:
        with self._sessions() as s:
            return s.get(BreachReportRecord, report_id)


def render_markdown(record: BreachReportRecord) -> str:
    c = record.content

    def table(title: str, values: dict) -> list[str]:
        rows = [f"| {k} | {v} |" for k, v in values.items()] or ["| none | 0 |"]
        return [f"### {title}", "", "| Value | Count |", "|---|---|", *rows, ""]

    lines = [
        f"> **{WATERMARK}**",
        "",
        f"# {c['title']}",
        "",
        f"Report {record.report_id}, status {record.status}, drafted "
        f"{_aware(record.created_at).strftime('%Y-%m-%d %H:%M UTC')} by Mitel AI Data Firewall"
        f"{' automatically, when monitoring detected the exposure' if c.get('auto_drafted') else ''}.",
    ]
    if record.reviewer:
        lines.append(f"Reviewed by {record.reviewer} on {_aware(record.reviewed_at).strftime('%Y-%m-%d %H:%M UTC')}"
                     f"{': ' + record.review_note if record.review_note else ''}.")
    window = c["window"]
    lines += [
        "",
        "## What happened",
        "",
        c["what_happened"],
        "",
        f"- Affected requests: **{c['affected_requests']}**",
        f"- Time window: {window['first'] or '-'} to {window['last'] or '-'}",
        f"- Receipt chain: {'CHAIN OK' if c['chain']['ok'] else 'NOT VERIFIED'} ({c['chain']['reason']})",
        "",
        "## Data involved",
        "",
        *table("Categories", c["categories"]),
        *table("Reasons", c["reasons"]),
        *table("Routes", c["routes"]),
        *table("Kill switch at the time", c["kill_switch"]),
        *table("Dial position at the time", c["dials"]),
        "## Incident and containment",
        "",
    ]
    inc = c.get("incident")
    lines.append(
        f"- Incident {inc['incident_id']}: {inc['status']}, severity {inc['severity']}, contained "
        f"{inc['contained_at'] or 'not yet'}, SLA {inc['sla_state']}" if inc else "- No incident linked yet."
    )
    lines += ["", "## Signed receipts", ""]
    lines += [f"- {rid}" for rid in c["receipt_ids"]] or ["- none"]
    lines += ["", "## Regulators to consider", "", f"_{c['regulator_note']}_", ""]
    lines += [f"- **{r['framework']}**: {r['note']}" for r in c["regulators"]]
    lines += ["", f"_{c['privacy']}_"]
    if c["synthetic_appendix"]:
        lines += ["", "## Appendix: synthetic test data", "",
                  "Invented canary values from the leak-canary set, shown so the measurement can be checked.", "",
                  "| Call | Type | Payload field | Surface text (synthetic) |", "|---|---|---|---|"]
        lines += [f"| {a['call_id']} | {a['type']} | {a['field']} | {a['surface']} |" for a in c["synthetic_appendix"]]
    lines += ["", f"> **{WATERMARK}**", ""]
    return "\n".join(lines)
