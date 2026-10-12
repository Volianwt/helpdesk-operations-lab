"""Portable snapshots and weekly handover summaries from the local database."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from helpdesk_lab import DB_PATH, ROOT, connect, dashboard, local_time, operational_metrics


def snapshot(db_path: Path = DB_PATH, as_of: datetime | None = None) -> dict:
    """Read the current records; the evaluation clock does not rewind their state."""
    as_of = local_time(as_of or datetime.now())
    queue = dashboard(db_path, as_of)
    by_id = {row["ticket_id"]: row for row in queue}
    with connect(db_path) as connection:
        tickets = [dict(row) for row in connection.execute("SELECT * FROM tickets ORDER BY priority, opened_at, ticket_id")]
        events = [dict(row) for row in connection.execute("SELECT * FROM ticket_events ORDER BY created_at DESC, event_id DESC")]
        assets = [dict(row) for row in connection.execute("SELECT * FROM assets ORDER BY asset_tag")]
        licenses = [dict(row) for row in connection.execute("SELECT * FROM software_licenses ORDER BY product")]
    for ticket in tickets:
        ticket.update(by_id.get(ticket["ticket_id"], {
            "state": "RESOLVED", "due_at": "", "escalation": "", "follow_up_state": "COMPLETE",
        }))
    start = as_of - timedelta(days=7)
    activity = [event for event in events if start < local_time(event["created_at"]) <= as_of]
    counts = Counter(event["event_type"] for event in activity)
    return {
        "as_of": as_of.isoformat(timespec="seconds"),
        "window_start": start.isoformat(timespec="seconds"),
        "tickets": tickets, "events": events, "assets": assets, "licenses": licenses,
        "metrics": operational_metrics(db_path, as_of),
        "activity": activity,
        "activity_counts": {kind: counts[kind] for kind in ("CREATED", "UPDATED", "NOTE", "RESOLVED")},
    }


def md(value: object) -> str:
    """Keep entered text on one Markdown table cell and out of HTML markup."""
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ").replace("\r", " ")
    for character in ("\\", "|", "[", "]", "`", "*", "_"):
        text = text.replace(character, "\\" + character)
    return text


def weekly_markdown(data: dict) -> str:
    metrics = data["metrics"]
    counts = data["activity_counts"]
    active = [ticket for ticket in data["tickets"] if ticket["status"] not in ("Resolved", "Closed")]
    lines = [
        "# Weekly operations summary", "",
        f"Evaluation time: **{data['as_of'].replace('T', ' ')}** (local lab time).",
        f"Activity window: after {data['window_start'].replace('T', ' ')} through {data['as_of'].replace('T', ' ')}.", "",
        "This is a synthetic lab snapshot. Queue counts use the current stored ticket state; they are not a reconstruction of the backlog at a historical date. The evaluation time controls deadline checks and the seven-day activity window.", "",
        "## Current queue", "",
        "| Measure | Count |", "| --- | ---: |",
        f"| Active tickets | {metrics['active_tickets']} |",
        f"| Overdue SLA targets | {metrics['overdue_tickets']} |",
        f"| At-risk SLA targets | {metrics['at_risk_tickets']} |",
        f"| Follow-ups due | {metrics['follow_ups_due']} |",
        f"| Unassigned tickets | {metrics['unassigned_tickets']} |", "",
        "SLA targets use elapsed clock hours (P1: 1, P2: 4, P3: 24, P4: 72). They do not pause for weekends or escalations. A deadline is overdue at its due time.", "",
        "## Recorded activity in the last seven days", "",
        "| Event | Count |", "| --- | ---: |",
        f"| Created | {counts['CREATED']} |", f"| Updated | {counts['UPDATED']} |",
        f"| Progress notes | {counts['NOTE']} |", f"| Resolved | {counts['RESOLVED']} |", "",
        "Resolution activity counts recorded RESOLVED events, not tickets currently marked resolved. Initially resolved seed records have no recorded resolution event.", "",
        "## Actions to follow up", "",
        "| Ticket | Owner | SLA state | Follow-up due | Next action |", "| --- | --- | --- | --- | --- |",
    ]
    ordered = sorted(active, key=lambda ticket: ({"OVERDUE": 0, "AT RISK": 1, "ON TRACK": 2}[ticket["state"]], ticket["due_at"]))
    for ticket in ordered:
        lines.append("| " + " | ".join(md(value) for value in (
            ticket["ticket_id"], ticket["owner"] or "Unassigned", ticket["state"],
            ticket["follow_up_due_at"].replace("T", " ") or "Not scheduled", ticket["follow_up_notes"] or "Assign an owner and record the next action.",
        )) + " |")
    if not active:
        lines.append("| — | — | No active tickets | — | — |")
    lines += ["", "## Activity log", "", "| Time | Ticket | Event | Detail |", "| --- | --- | --- | --- |"]
    for event in data["activity"]:
        lines.append("| " + " | ".join(md(event[key]) for key in ("created_at", "ticket_id", "event_type", "details")) + " |")
    if not data["activity"]:
        lines.append("| — | — | No events in this window | — |")
    lines += ["", "## Inventory", "",
              f"{len(data['assets'])} assets recorded; {metrics['assets_in_repair']} in repair. {metrics['unassigned_license_seats']} unassigned software seats across {len(data['licenses'])} products.", ""]
    return "\n".join(lines)


def write_weekly_summary(output: Path, db_path: Path = DB_PATH, as_of: datetime | None = None) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(weekly_markdown(snapshot(db_path, as_of)), encoding="utf-8")
    return output


def write_dashboard(output: Path, db_path: Path = DB_PATH, as_of: datetime | None = None) -> Path:
    data = snapshot(db_path, as_of)
    data["weekly_markdown"] = weekly_markdown(data)
    # Script-safe JSON is necessary even with type=application/json: the HTML
    # parser otherwise treats a user-entered </script> as the end of the element.
    payload = json.dumps(data, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    template = (ROOT / "report_template.html").read_text(encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("__SNAPSHOT_JSON__", payload), encoding="utf-8")
    return output
