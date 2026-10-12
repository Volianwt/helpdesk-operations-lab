#!/usr/bin/env python3
"""SQLite-backed simulated Tier 1 helpdesk operations lab."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "helpdesk_lab.db"
KB_DIR = ROOT / "kb"

SLA_HOURS = {"P1": 1, "P2": 4, "P3": 24, "P4": 72}
ACTIVE_STATUSES = ("Open", "In Progress", "Escalated")
DEMO_TIME = datetime(2026, 8, 14, 16)

# These roles and actions belong to the synthetic scenario, not a real team.
SEED_FOLLOW_UP = {
    "INC-1001": ("Service Desk", "2026-08-14T15:00:00", "Check the mapped-drive test result with Finance."),
    "INC-1002": ("Service Desk", "2026-08-14T16:30:00", "Confirm the approved headset works in a Teams test call."),
    "INC-1003": ("Security", "2026-08-14T16:00:00", "Request the security owner’s acknowledgement of the escalation."),
    "REQ-1004": ("IT Operations", "2026-08-14T15:30:00", "Confirm manager approval and the remaining onboarding tasks."),
    "INC-1007": ("Event Support", "2026-08-14T16:10:00", "Test the spare HDMI cable before the room handover."),
    "INC-1009": ("Service Desk", "2026-08-14T17:00:00", "Record the known-good network test before escalation."),
}

ASSETS = [
    ("EVG-LT-014", "Laptop", "Windows 11", "Assigned", "Finance"),
    ("EVG-LT-021", "Laptop", "Windows 11", "Assigned", "Programs"),
    ("EVG-MAC-006", "MacBook", "macOS", "Assigned", "Marketing"),
    ("EVG-TAB-004", "Tablet", "iPadOS", "Loaner", "Events"),
    ("EVG-PRN-002", "Office printer", "Embedded", "Shared", "2nd Floor"),
    ("EVG-AV-003", "Projector", "Embedded", "Shared", "Event Space"),
    ("EVG-AV-009", "Wireless microphone", "N/A", "Shared", "Event Space"),
    ("EVG-PHN-018", "Yealink IP phone", "Embedded", "Assigned", "Reception"),
    ("EVG-LT-028", "Laptop", "Windows 11", "In stock", "IT Storage"),
    ("EVG-MAC-011", "MacBook", "macOS", "Repair", "Vendor"),
]

TICKETS = [
    ("INC-1001", "Finance cannot access shared drive", "Network", "high", "high", "2026-08-14T13:30:00", "Open", "EVG-LT-014"),
    ("INC-1002", "Teams microphone not detected before meeting", "Microsoft 365", "medium", "high", "2026-08-14T14:15:00", "In Progress", "EVG-LT-021"),
    ("INC-1003", "Suspicious attachment opened", "Security", "high", "high", "2026-08-14T15:20:00", "Escalated", "EVG-LT-021"),
    ("REQ-1004", "Create accounts and prepare laptop for new hire", "Onboarding", "medium", "medium", "2026-08-13T09:00:00", "In Progress", "EVG-LT-028"),
    ("INC-1005", "SharePoint folder access denied", "Microsoft 365", "low", "medium", "2026-08-14T10:30:00", "Open", "EVG-LT-014"),
    ("INC-1006", "Office printer shows offline", "Printing", "medium", "medium", "2026-08-14T11:45:00", "Resolved", "EVG-PRN-002"),
    ("INC-1007", "Projector has no HDMI signal", "AV/Event", "high", "high", "2026-08-14T15:35:00", "In Progress", "EVG-AV-003"),
    ("INC-1008", "IP phone cannot register", "Voice", "medium", "medium", "2026-08-14T08:00:00", "Open", "EVG-PHN-018"),
    ("INC-1009", "Laptop receives self-assigned IP address", "Network", "medium", "high", "2026-08-14T12:20:00", "Open", "EVG-LT-021"),
    ("REQ-1010", "Adobe Acrobat update request", "Software", "low", "low", "2026-08-12T09:30:00", "Open", "EVG-MAC-006"),
    ("INC-1011", "Tablet cannot join staff Wi-Fi", "Mobile", "low", "medium", "2026-08-14T09:10:00", "Open", "EVG-TAB-004"),
    ("REQ-1012", "Recover returned laptop and update inventory", "Offboarding", "medium", "low", "2026-08-13T14:00:00", "Resolved", "EVG-LT-028"),
]


def calculate_priority(impact: str, urgency: str) -> str:
    """Map impact/urgency to a transparent Tier 1 priority."""
    levels = {"low": 1, "medium": 2, "high": 3}
    if impact not in levels or urgency not in levels:
        raise ValueError("impact and urgency must be low, medium, or high")
    score = levels[impact] + levels[urgency]
    if score >= 6:
        return "P1"
    if score == 5:
        return "P2"
    if score in {3, 4}:
        return "P3"
    return "P4"


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(db_path: Path = DB_PATH, reset: bool = False) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and db_path.exists():
        db_path.unlink()
    with connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
                asset_tag TEXT PRIMARY KEY,
                asset_type TEXT NOT NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL,
                assignment TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                category TEXT NOT NULL,
                impact TEXT NOT NULL,
                urgency TEXT NOT NULL,
                priority TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                status TEXT NOT NULL,
                asset_tag TEXT,
                resolution_notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(asset_tag) REFERENCES assets(asset_tag)
            );
            CREATE TABLE IF NOT EXISTS software_licenses (
                product TEXT PRIMARY KEY,
                seats_owned INTEGER NOT NULL,
                seats_assigned INTEGER NOT NULL,
                renewal_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ticket_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(ticket_id) REFERENCES tickets(ticket_id)
            );
            """
        )
        # Additive migration also accepts databases created by the first version.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(tickets)")}
        for name in ("owner", "follow_up_due_at", "follow_up_notes"):
            if name not in columns:
                connection.execute(f"ALTER TABLE tickets ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_events_ticket_time ON ticket_events(ticket_id, created_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON ticket_events(created_at)")
        connection.executemany("INSERT OR IGNORE INTO assets VALUES (?, ?, ?, ?, ?)", ASSETS)
        for row in TICKETS:
            metadata = SEED_FOLLOW_UP.get(row[0], ("", "", ""))
            values = row[:5] + (calculate_priority(row[3], row[4]),) + row[5:] + ("",) + metadata
            cursor = connection.execute(
                """INSERT OR IGNORE INTO tickets
                (ticket_id, summary, category, impact, urgency, priority, opened_at,
                 status, asset_tag, resolution_notes, owner, follow_up_due_at, follow_up_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values,
            )
            if cursor.rowcount:
                connection.execute(
                    "INSERT INTO ticket_events (ticket_id, event_type, details, created_at) VALUES (?, 'CREATED', ?, ?)",
                    (row[0], "Synthetic scenario created; initial status: " + row[6], row[5]),
                )
        connection.executemany(
            "INSERT OR IGNORE INTO software_licenses VALUES (?, ?, ?, ?)",
            [("Microsoft 365", 85, 79, "2027-01-31"),
             ("Adobe Acrobat", 20, 18, "2026-12-15"),
             ("Remote Support", 8, 7, "2026-11-30")],
        )


def local_time(value: str | datetime) -> datetime:
    """Use one explicit clock convention; reject offset-aware timestamps."""
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is not None:
        raise ValueError("use a local date and time without a timezone offset (YYYY-MM-DDTHH:MM:SS)")
    return parsed


def clean_text(value: str, label: str, minimum: int = 1, maximum: int = 2000) -> str:
    value = " ".join(value.split())
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} must contain {minimum}–{maximum} characters")
    return value


def editable_ticket(connection: sqlite3.Connection, ticket_id: str, at: datetime) -> sqlite3.Row:
    ticket = connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        raise KeyError(f"unknown ticket: {ticket_id}")
    if ticket["status"] in {"Resolved", "Closed"}:
        raise ValueError(f"ticket {ticket_id} is already {ticket['status'].lower()}")
    latest = connection.execute(
        "SELECT MAX(created_at) FROM ticket_events WHERE ticket_id = ?", (ticket_id,)
    ).fetchone()[0]
    if at < local_time(ticket["opened_at"]) or (latest and at < local_time(latest)):
        raise ValueError("the update time cannot precede the ticket's latest recorded event")
    return ticket


def record_event(connection: sqlite3.Connection, ticket_id: str, kind: str, details: str, at: datetime) -> None:
    connection.execute(
        "INSERT INTO ticket_events (ticket_id, event_type, details, created_at) VALUES (?, ?, ?, ?)",
        (ticket_id, kind, details, at.isoformat(timespec="seconds")),
    )


def update_ticket(
    ticket_id: str, db_path: Path = DB_PATH, *, owner: str | None = None,
    status: str | None = None, follow_up_due: datetime | None = None,
    notes: str | None = None, clear_follow_up: bool = False, at: datetime | None = None,
) -> None:
    """Change a ticket and write the before/after values in the same transaction."""
    at = local_time(at or datetime.now())
    if status is not None and status not in ACTIVE_STATUSES:
        raise ValueError("status must be Open, In Progress, or Escalated; use resolve to close work")
    if clear_follow_up and (follow_up_due is not None or notes is not None):
        raise ValueError("clear-follow-up cannot be combined with a new due time or action")
    if (follow_up_due is None) != (notes is None):
        raise ValueError("a follow-up requires both a due time and an action note")
    changes = {}
    if owner is not None:
        changes["owner"] = clean_text(owner, "owner", maximum=100) if owner.strip() else ""
    if status is not None:
        changes["status"] = status
    if follow_up_due is not None:
        due = local_time(follow_up_due)
        if due < at:
            raise ValueError("follow-up due time cannot precede the update time")
        changes.update(follow_up_due_at=due.isoformat(timespec="seconds"),
                       follow_up_notes=clean_text(notes, "follow-up action", minimum=12))
    if clear_follow_up:
        changes.update(follow_up_due_at="", follow_up_notes="")
    if not changes:
        raise ValueError("provide an owner, status, or follow-up to update")
    with connect(db_path) as connection:
        ticket = editable_ticket(connection, ticket_id, at)
        changes = {key: value for key, value in changes.items() if ticket[key] != value}
        if not changes:
            raise ValueError("the ticket already has those values")
        query = ", ".join(f"{field} = ?" for field in changes)
        connection.execute(f"UPDATE tickets SET {query} WHERE ticket_id = ?", (*changes.values(), ticket_id))
        details = "; ".join(f"{key.replace('_', ' ').capitalize()}: {ticket[key] or '(none)'} → {value or '(none)'}"
                            for key, value in changes.items())
        record_event(connection, ticket_id, "UPDATED", details, at)


def add_note(ticket_id: str, notes: str, db_path: Path = DB_PATH, at: datetime | None = None) -> None:
    notes = clean_text(notes, "note", minimum=12)
    at = local_time(at or datetime.now())
    with connect(db_path) as connection:
        editable_ticket(connection, ticket_id, at)
        record_event(connection, ticket_id, "NOTE", notes, at)


def sla_state(priority: str, opened_at: datetime, as_of: datetime) -> tuple[str, datetime]:
    opened_at, as_of = local_time(opened_at), local_time(as_of)
    due_at = opened_at + timedelta(hours=SLA_HOURS[priority])
    remaining = due_at - as_of
    if remaining.total_seconds() <= 0:
        return "OVERDUE", due_at
    if remaining <= timedelta(hours=max(1, SLA_HOURS[priority] * 0.25)):
        return "AT RISK", due_at
    return "ON TRACK", due_at


def dashboard(db_path: Path = DB_PATH, as_of: datetime | None = None) -> list[dict[str, str]]:
    as_of = local_time(as_of or datetime.now())
    with connect(db_path) as connection:
        opened = connection.execute("SELECT opened_at FROM tickets").fetchall()
        if any(local_time(row["opened_at"]) > as_of for row in opened):
            raise ValueError("evaluation time cannot precede a recorded ticket opening time")
        rows = connection.execute(
            "SELECT * FROM tickets WHERE status NOT IN ('Resolved', 'Closed') ORDER BY opened_at"
        ).fetchall()
    result = []
    for row in rows:
        state, due_at = sla_state(row["priority"], datetime.fromisoformat(row["opened_at"]), as_of)
        escalation = escalation_reason(row["category"], row["priority"], state)
        result.append(
            {
                "ticket_id": row["ticket_id"],
                "priority": row["priority"],
                "state": state,
                "due_at": due_at.isoformat(timespec="minutes"),
                "escalation": escalation,
                "summary": row["summary"],
                "status": row["status"],
                "owner": row["owner"],
                "follow_up_due_at": row["follow_up_due_at"],
                "follow_up_notes": row["follow_up_notes"],
                "follow_up_state": ("DUE" if local_time(row["follow_up_due_at"]) <= as_of else "SCHEDULED") if row["follow_up_due_at"] else "NOT SET",
            }
        )
    return sorted(result, key=lambda item: ({"OVERDUE": 0, "AT RISK": 1, "ON TRACK": 2}[item["state"]], item["due_at"]))


def escalation_reason(category: str, priority: str, sla_status: str) -> str:
    """Return the clearest operational reason for escalation, if one applies."""
    if category.casefold() == "security":
        return "SECURITY"
    if priority == "P1":
        return "P1 IMPACT"
    if sla_status == "OVERDUE":
        return "SLA BREACH"
    if sla_status == "AT RISK":
        return "SLA RISK"
    return ""


def resolve_ticket(
    ticket_id: str,
    resolution_notes: str,
    db_path: Path = DB_PATH,
    resolved_at: datetime | None = None,
) -> None:
    """Resolve one ticket and record an auditable event."""
    clean_notes = clean_text(resolution_notes, "resolution notes", minimum=12)
    resolved_at = local_time(resolved_at or datetime.now())
    with connect(db_path) as connection:
        ticket = editable_ticket(connection, ticket_id, resolved_at)
        connection.execute(
            "UPDATE tickets SET status = 'Resolved', resolution_notes = ?, follow_up_due_at = '', follow_up_notes = '' WHERE ticket_id = ?",
            (clean_notes, ticket_id),
        )
        details = clean_notes
        if ticket["follow_up_due_at"]:
            details += f" [Cleared follow-up: {ticket['follow_up_due_at']} — {ticket['follow_up_notes']}]"
        record_event(connection, ticket_id, "RESOLVED", details, resolved_at)


def operational_metrics(db_path: Path = DB_PATH, as_of: datetime | None = None) -> dict[str, int]:
    """Produce a compact queue/inventory/licence summary for daily review."""
    queue = dashboard(db_path, as_of)
    with connect(db_path) as connection:
        resolved = connection.execute(
            "SELECT COUNT(*) FROM tickets WHERE status IN ('Resolved', 'Closed')"
        ).fetchone()[0]
        repair_assets = connection.execute(
            "SELECT COUNT(*) FROM assets WHERE status = 'Repair'"
        ).fetchone()[0]
        license_headroom = connection.execute(
            "SELECT SUM(seats_owned - seats_assigned) FROM software_licenses"
        ).fetchone()[0]
    return {
        "active_tickets": len(queue),
        "resolved_tickets": resolved,
        "overdue_tickets": sum(item["state"] == "OVERDUE" for item in queue),
        "at_risk_tickets": sum(item["state"] == "AT RISK" for item in queue),
        "escalations": sum(bool(item["escalation"]) for item in queue),
        "unassigned_tickets": sum(not item["owner"] for item in queue),
        "follow_ups_due": sum(item["follow_up_state"] == "DUE" for item in queue),
        "assets_in_repair": repair_assets,
        "unassigned_license_seats": license_headroom or 0,
    }


def export_operational_data(output_dir: Path, db_path: Path = DB_PATH) -> list[Path]:
    """Export operational records without external packages."""
    output_dir.mkdir(parents=True, exist_ok=True)
    exports = {
        "tickets.csv": "SELECT * FROM tickets ORDER BY ticket_id",
        "assets.csv": "SELECT * FROM assets ORDER BY asset_tag",
        "software_licenses.csv": "SELECT * FROM software_licenses ORDER BY product",
        "ticket_events.csv": "SELECT * FROM ticket_events ORDER BY event_id",
    }
    written = []
    with connect(db_path) as connection:
        for filename, query in exports.items():
            cursor = connection.execute(query)
            rows = cursor.fetchall()
            path = output_dir / filename
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(column[0] for column in cursor.description)
                writer.writerows(tuple(csv_safe(value) for value in row) for row in rows)
            written.append(path)
    return written


def csv_safe(value):
    # Spreadsheet software may interpret user-entered text as a formula.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def search_kb(query: str, kb_dir: Path = KB_DIR) -> list[tuple[str, str]]:
    terms = [term.casefold() for term in query.split() if term]
    matches = []
    for path in sorted(kb_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        haystack = text.casefold()
        score = sum(haystack.count(term) for term in terms)
        if score:
            title = next((line[2:] for line in text.splitlines() if line.startswith("# ")), path.stem)
            matches.append((title, path.name, score))
    matches.sort(key=lambda item: (-item[2], item[0]))
    return [(title, filename) for title, filename, _ in matches]


def print_rows(rows: list[dict[str, str]], fields: list[str]) -> None:
    widths = {field: max([len(field)] + [len(str(row[field])) for row in rows]) for field in fields}
    print("  ".join(field.upper().ljust(widths[field]) for field in fields))
    print("  ".join("-" * widths[field] for field in fields))
    for row in rows:
        print("  ".join(str(row[field]).ljust(widths[field]) for field in fields))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH, help="database path (default: data/helpdesk_lab.db)")
    commands = parser.add_subparsers(dest="command", required=True)
    init_parser = commands.add_parser("init", help="create, migrate, and seed without overwriting records")
    init_parser.add_argument("--reset", action="store_true", help="DELETE this database and reseed it")
    for name, help_text in (("dashboard", "show the active SLA queue"), ("metrics", "show queue and inventory metrics"),
                            ("report", "write a standalone interactive HTML snapshot"), ("weekly", "write a seven-day Markdown summary")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--as-of", type=local_time, help="local evaluation time, e.g. 2026-08-14T16:00:00")
        if name in ("report", "weekly"):
            command.add_argument("--output", type=Path, default=ROOT / "reports" / ("dashboard.html" if name == "report" else "weekly-summary.md"))
    commands.add_parser("tickets", help="list all tickets")
    commands.add_parser("assets", help="list all assets")
    kb_parser = commands.add_parser("kb", help="search knowledge-base articles")
    kb_parser.add_argument("query")
    for name, help_text in (("resolve", "resolve a ticket with an audit event"), ("note", "append a progress note"), ("update", "set ownership, status, and follow-up")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("ticket_id")
        command.add_argument("--at", type=local_time, help="local event time (defaults to now)")
        command.add_argument("--notes", required=name != "update")
        if name == "update":
            command.add_argument("--owner", help="responsible person or team; empty string removes the assignment")
            command.add_argument("--status", choices=ACTIVE_STATUSES)
            command.add_argument("--follow-up-due", type=local_time)
            command.add_argument("--clear-follow-up", action="store_true")
    export_parser = commands.add_parser("export", help="export tickets, assets, licences, and events to CSV")
    export_parser.add_argument("--output-dir", type=Path, default=ROOT / "exports")
    args = parser.parse_args()
    try:
        initialize(args.db, reset=args.command == "init" and args.reset)
        if args.command == "init":
            print(f"Database ready: {args.db}")
        elif args.command == "dashboard":
            print_rows(dashboard(args.db, args.as_of), ["ticket_id", "priority", "state", "due_at", "owner", "follow_up_state", "summary"])
        elif args.command in {"tickets", "assets"}:
            fields = ["ticket_id", "priority", "status", "owner", "category", "summary"] if args.command == "tickets" else ["asset_tag", "asset_type", "platform", "status", "assignment"]
            with connect(args.db) as connection:
                rows = [dict(row) for row in connection.execute(f"SELECT * FROM {args.command} ORDER BY {fields[0]}")]
            print_rows(rows, fields)
        elif args.command == "metrics":
            for name, value in operational_metrics(args.db, args.as_of).items():
                print(f"{name}: {value}")
        elif args.command == "kb":
            results = search_kb(args.query)
            if not results:
                print("No matching knowledge-base articles.")
            for title, filename in results:
                print(f"{title} ({filename})")
        elif args.command == "resolve":
            resolve_ticket(args.ticket_id, args.notes, args.db, args.at)
            print(f"Resolved {args.ticket_id} and recorded an audit event.")
        elif args.command == "note":
            add_note(args.ticket_id, args.notes, args.db, args.at)
            print(f"Added a progress note to {args.ticket_id}.")
        elif args.command == "update":
            update_ticket(args.ticket_id, args.db, owner=args.owner, status=args.status,
                          follow_up_due=args.follow_up_due, notes=args.notes,
                          clear_follow_up=args.clear_follow_up, at=args.at)
            print(f"Updated {args.ticket_id} and recorded the changes.")
        elif args.command == "export":
            for path in export_operational_data(args.output_dir, args.db):
                print(path)
        elif args.command in {"report", "weekly"}:
            from reporting import write_dashboard, write_weekly_summary
            writer = write_dashboard if args.command == "report" else write_weekly_summary
            writer(args.output, args.db, args.as_of)
            print(args.output)
    except (ValueError, KeyError, sqlite3.Error, OSError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
