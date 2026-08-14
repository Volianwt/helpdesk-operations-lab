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
        connection.executemany(
            "INSERT OR REPLACE INTO assets VALUES (?, ?, ?, ?, ?)", ASSETS
        )
        ticket_rows = [row[:5] + (calculate_priority(row[3], row[4]),) + row[5:] + ("",) for row in TICKETS]
        connection.executemany(
            "INSERT OR REPLACE INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ticket_rows,
        )
        connection.executemany(
            "INSERT OR REPLACE INTO software_licenses VALUES (?, ?, ?, ?)",
            [
                ("Microsoft 365", 85, 79, "2027-01-31"),
                ("Adobe Acrobat", 20, 18, "2026-12-15"),
                ("Remote Support", 8, 7, "2026-11-30"),
            ],
        )
        for ticket in TICKETS:
            connection.execute(
                """
                INSERT INTO ticket_events (ticket_id, event_type, details, created_at)
                SELECT ?, 'CREATED', 'Seeded simulated incident', ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM ticket_events WHERE ticket_id = ? AND event_type = 'CREATED'
                )
                """,
                (ticket[0], ticket[5], ticket[0]),
            )


def sla_state(priority: str, opened_at: datetime, as_of: datetime) -> tuple[str, datetime]:
    due_at = opened_at + timedelta(hours=SLA_HOURS[priority])
    remaining = due_at - as_of
    if remaining.total_seconds() < 0:
        return "OVERDUE", due_at
    if remaining <= timedelta(hours=max(1, SLA_HOURS[priority] * 0.25)):
        return "AT RISK", due_at
    return "ON TRACK", due_at


def dashboard(db_path: Path = DB_PATH, as_of: datetime | None = None) -> list[dict[str, str]]:
    as_of = as_of or datetime.now()
    with connect(db_path) as connection:
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
    clean_notes = " ".join(resolution_notes.split())
    if len(clean_notes) < 12:
        raise ValueError("resolution notes must explain the verified outcome")
    resolved_at = resolved_at or datetime.now()
    with connect(db_path) as connection:
        ticket = connection.execute(
            "SELECT status FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if ticket is None:
            raise KeyError(f"unknown ticket: {ticket_id}")
        if ticket["status"] in {"Resolved", "Closed"}:
            raise ValueError(f"ticket {ticket_id} is already {ticket['status'].lower()}")
        connection.execute(
            "UPDATE tickets SET status = 'Resolved', resolution_notes = ? WHERE ticket_id = ?",
            (clean_notes, ticket_id),
        )
        connection.execute(
            "INSERT INTO ticket_events (ticket_id, event_type, details, created_at) VALUES (?, 'RESOLVED', ?, ?)",
            (ticket_id, clean_notes, resolved_at.isoformat(timespec="seconds")),
        )


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
        "assets_in_repair": repair_assets,
        "unassigned_license_seats": license_headroom,
    }


def export_operational_data(output_dir: Path, db_path: Path = DB_PATH) -> list[Path]:
    """Export recruiter-readable operational records without external packages."""
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
            rows = connection.execute(query).fetchall()
            path = output_dir / filename
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(rows[0].keys() if rows else [])
                writer.writerows(tuple(row) for row in rows)
            written.append(path)
    return written


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
    widths = {field: max(len(field), *(len(str(row[field])) for row in rows)) for field in fields}
    print("  ".join(field.upper().ljust(widths[field]) for field in fields))
    print("  ".join("-" * widths[field] for field in fields))
    for row in rows:
        print("  ".join(str(row[field]).ljust(widths[field]) for field in fields))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="create and seed the lab database")
    init_parser.add_argument("--reset", action="store_true")
    dashboard_parser = subparsers.add_parser("dashboard", help="show the active SLA queue")
    dashboard_parser.add_argument("--as-of", type=datetime.fromisoformat)
    subparsers.add_parser("tickets", help="list all tickets")
    subparsers.add_parser("assets", help="list all assets")
    subparsers.add_parser("metrics", help="show queue and inventory metrics")
    kb_parser = subparsers.add_parser("kb", help="search knowledge-base articles")
    kb_parser.add_argument("query")
    resolve_parser = subparsers.add_parser("resolve", help="resolve a ticket with an audit event")
    resolve_parser.add_argument("ticket_id")
    resolve_parser.add_argument("--notes", required=True)
    export_parser = subparsers.add_parser("export", help="export tickets, assets, licences, and events to CSV")
    export_parser.add_argument("--output-dir", type=Path, default=ROOT / "exports")
    args = parser.parse_args()

    if args.command == "init":
        initialize(reset=args.reset)
        print(f"Initialized {DB_PATH} with {len(TICKETS)} tickets and {len(ASSETS)} assets.")
        return

    if not DB_PATH.exists():
        initialize()

    if args.command == "dashboard":
        print_rows(dashboard(as_of=args.as_of), ["ticket_id", "priority", "state", "due_at", "escalation", "summary"])
    elif args.command == "tickets":
        with connect() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT ticket_id, priority, status, category, summary FROM tickets ORDER BY ticket_id"
            )]
        print_rows(rows, ["ticket_id", "priority", "status", "category", "summary"])
    elif args.command == "assets":
        with connect() as connection:
            rows = [dict(row) for row in connection.execute("SELECT * FROM assets ORDER BY asset_tag")]
        print_rows(rows, ["asset_tag", "asset_type", "platform", "status", "assignment"])
    elif args.command == "metrics":
        for name, value in operational_metrics().items():
            print(f"{name}: {value}")
    elif args.command == "kb":
        results = search_kb(args.query)
        if not results:
            print("No matching knowledge-base articles.")
        for title, filename in results:
            print(f"{title} ({filename})")
    elif args.command == "resolve":
        resolve_ticket(args.ticket_id, args.notes)
        print(f"Resolved {args.ticket_id} and recorded an audit event.")
    elif args.command == "export":
        for path in export_operational_data(args.output_dir):
            print(path)


if __name__ == "__main__":
    main()
