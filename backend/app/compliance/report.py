"""Markdown rendering of an evidence pack, for download or attachment."""

from __future__ import annotations

from app.schemas.compliance import EvidencePack

_STATUS_LABEL = {"PASS": "Pass", "PARTIAL": "Partial", "FAIL": "Fail"}


def _cell(value: object) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _date(value) -> str:
    return value.strftime("%Y-%m-%d") if value else "-"


def render_markdown(pack: EvidencePack) -> str:
    lines = [
        f"# {pack.framework_name} evidence pack",
        "",
        f"Generated {pack.generated_at.strftime('%Y-%m-%d %H:%M UTC')} by Mitel AI Data Firewall.",
        f"**Compliance score: {pack.score}%**",
        "",
        f"> {pack.disclaimer}",
        "",
        "## Controls",
        "",
        "| Status | Control | Reference | Evidence |",
        "|---|---|---|---|",
    ]
    for c in pack.controls:
        lines.append(f"| {_STATUS_LABEL[c.status]} | {_cell(c.title)} | {_cell(c.reference)} | {_cell(c.evidence)} |")

    gaps = [c for c in pack.controls if c.status != "PASS"]
    lines += ["", "## Gaps and remediation", ""]
    lines += [f"- **{c.title}** ({_STATUS_LABEL[c.status]}): {c.remediation}" for c in gaps] or ["- No gaps found."]

    lines += [
        "",
        "## AI system inventory",
        "",
        "| System | Owner | Hosting | Status | Last reviewed | Next review | Overdue |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in pack.ai_systems:
        lines.append(
            f"| {_cell(s.name)} | {_cell(s.owner)} | {s.hosting.title()} | {s.status.replace('_', ' ').title()} "
            f"| {_date(s.last_reviewed_at)} | {_date(s.next_review_due)} | {'Yes' if s.review_overdue else 'No'} |"
        )

    p = pack.policies
    lines += [
        "",
        "## Policy configuration",
        "",
        f"Policy set {p.policy_version}: {p.enabled} of {p.total} rules enabled.",
        "",
        "| Rule | Action | Destination | Categories | Profiles | Enabled |",
        "|---|---|---|---|---|---|",
    ]
    for r in p.rules:
        lines.append(
            f"| {_cell(r.name)} | {r.action} | {r.destination} | {_cell(', '.join(r.categories))} "
            f"| {_cell(', '.join(r.profiles) or 'All')} | {'Yes' if r.enabled else 'No'} |"
        )

    a, i, d = pack.audit, pack.incidents, pack.data_requests
    lines += [
        "",
        "## Audit trail",
        "",
        f"- Events retained: {a.event_count} (retention {a.retention_days} days)",
        f"- Stores transcripts: {'Yes' if a.stores_raw_transcripts else 'No'}. Stores detected values: {'Yes' if a.stores_entity_values else 'No'}.",
        "",
        "## Incidents",
        "",
        f"- Total {i.total}: {i.open} open, {i.closed} closed",
        f"- Contained within SLA: {i.contained_within_sla}. Missed SLA: {i.sla_missed}. Open and past deadline: {i.sla_breached_open}.",
        "",
        "## Data-subject requests",
        "",
        f"- Total {d.total}: {d.open} open, {d.completed} completed ({d.completed_on_time} on time, {d.completed_late} late)",
        f"- Open and overdue: {d.overdue_open}",
        "",
    ]
    return "\n".join(lines)
