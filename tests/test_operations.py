import contextlib
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from helpdesk_lab import (
    DEMO_TIME, add_note, connect, dashboard, export_operational_data, initialize,
    local_time, operational_metrics, print_rows, resolve_ticket, sla_state, update_ticket,
)
from reporting import snapshot, weekly_markdown, write_dashboard, write_weekly_summary


class ScriptCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "test.db"
        initialize(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def read_ticket(self, ticket_id="INC-1001"):
        with connect(self.db) as connection:
            return dict(connection.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone())

    def test_reinitialization_preserves_work_and_inventory_without_duplicate_events(self):
        update_ticket("INC-1001", self.db, owner="Assigned operator", at=DEMO_TIME)
        resolve_ticket("INC-1002", "Verified headset output in a complete test call.", self.db, DEMO_TIME)
        with connect(self.db) as connection:
            connection.execute("UPDATE assets SET assignment = 'Changed desk' WHERE asset_tag = 'EVG-LT-014'")
            connection.execute("UPDATE software_licenses SET seats_assigned = 80 WHERE product = 'Microsoft 365'")
            event_count = connection.execute("SELECT COUNT(*) FROM ticket_events").fetchone()[0]
        initialize(self.db)
        initialize(self.db)
        self.assertEqual(self.read_ticket()["owner"], "Assigned operator")
        self.assertEqual(self.read_ticket("INC-1002")["status"], "Resolved")
        with connect(self.db) as connection:
            self.assertEqual(connection.execute("SELECT assignment FROM assets WHERE asset_tag = 'EVG-LT-014'").fetchone()[0], "Changed desk")
            self.assertEqual(connection.execute("SELECT seats_assigned FROM software_licenses WHERE product = 'Microsoft 365'").fetchone()[0], 80)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ticket_events").fetchone()[0], event_count)

    def test_legacy_schema_migration_preserves_existing_fields(self):
        legacy = self.root / "legacy.db"
        with sqlite3.connect(legacy) as connection:
            connection.executescript("""
                CREATE TABLE tickets (ticket_id TEXT PRIMARY KEY, summary TEXT NOT NULL,
                    category TEXT NOT NULL, impact TEXT NOT NULL, urgency TEXT NOT NULL,
                    priority TEXT NOT NULL, opened_at TEXT NOT NULL, status TEXT NOT NULL,
                    asset_tag TEXT, resolution_notes TEXT NOT NULL DEFAULT '');
                INSERT INTO tickets VALUES ('INC-1001', 'Existing edited summary', 'Network',
                    'high', 'high', 'P1', '2026-08-14T13:30:00', 'Resolved', NULL, 'Existing verification note');
            """)
        initialize(legacy)
        with connect(legacy) as connection:
            ticket = connection.execute("SELECT * FROM tickets WHERE ticket_id = 'INC-1001'").fetchone()
        self.assertEqual(ticket["summary"], "Existing edited summary")
        self.assertEqual(ticket["resolution_notes"], "Existing verification note")
        self.assertEqual(ticket["status"], "Resolved")
        self.assertEqual(ticket["owner"], "")
        self.assertEqual(ticket["follow_up_due_at"], "")

    def test_update_records_before_after_values_and_required_follow_up(self):
        due = DEMO_TIME + timedelta(hours=1)
        update_ticket("INC-1001", self.db, owner="Network Support", status="Escalated", follow_up_due=due,
                      notes="Confirm the shared folder test with the user.", at=DEMO_TIME)
        ticket = self.read_ticket()
        self.assertEqual(ticket["owner"], "Network Support")
        self.assertEqual(ticket["status"], "Escalated")
        self.assertEqual(ticket["follow_up_due_at"], "2026-08-14T17:00:00")
        with connect(self.db) as connection:
            event = connection.execute("SELECT * FROM ticket_events ORDER BY event_id DESC LIMIT 1").fetchone()
        self.assertEqual(event["event_type"], "UPDATED")
        self.assertIn("Service Desk → Network Support", event["details"])
        self.assertIn("Open → Escalated", event["details"])

    def test_invalid_update_is_rejected_without_mutation(self):
        before = self.read_ticket()
        attempts = [
            {"follow_up_due": DEMO_TIME}, {"notes": "A useful follow-up note"},
            {"follow_up_due": DEMO_TIME - timedelta(minutes=1), "notes": "A useful follow-up note"},
            {"status": "Resolved"}, {"owner": "X" * 101},
            {"clear_follow_up": True, "notes": "A useful follow-up note"},
            {"owner": "Assigned operator", "at": datetime(2026, 8, 14, 12)},
            {},
        ]
        for values in attempts:
            values.setdefault("at", DEMO_TIME)
            with self.subTest(values=values), self.assertRaises(ValueError):
                update_ticket("INC-1001", self.db, **values)
        self.assertEqual(self.read_ticket(), before)

    def test_event_failure_rolls_back_ticket_change(self):
        with connect(self.db) as connection:
            connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON ticket_events BEGIN SELECT RAISE(ABORT, 'event write failed'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            update_ticket("INC-1001", self.db, owner="New owner", at=DEMO_TIME)
        self.assertEqual(self.read_ticket()["owner"], "Service Desk")

    def test_resolution_clears_follow_up_and_preserves_it_in_history(self):
        resolve_ticket("INC-1001", "Confirmed the mapped drive opens the expected folder.", self.db, DEMO_TIME)
        ticket = self.read_ticket()
        self.assertEqual(ticket["follow_up_due_at"], "")
        self.assertEqual(ticket["follow_up_notes"], "")
        with connect(self.db) as connection:
            detail = connection.execute("SELECT details FROM ticket_events WHERE event_type = 'RESOLVED'").fetchone()[0]
        self.assertIn("Cleared follow-up", detail)
        for action in (lambda: resolve_ticket("INC-1001", "Confirmed the resolution a second time.", self.db, DEMO_TIME),
                       lambda: add_note("INC-1001", "This note should be rejected.", self.db, DEMO_TIME),
                       lambda: update_ticket("INC-1001", self.db, owner="New owner", at=DEMO_TIME)):
            with self.assertRaises(ValueError):
                action()

    def test_unknown_ticket_and_event_time_validation(self):
        with self.assertRaises(KeyError):
            add_note("MISSING", "A valid progress note.", self.db, DEMO_TIME)
        add_note("INC-1001", "A valid progress note.", self.db, DEMO_TIME)
        with self.assertRaises(ValueError):
            add_note("INC-1001", "A note before the last event.", self.db, DEMO_TIME - timedelta(seconds=1))
        with self.assertRaises(ValueError):
            local_time(DEMO_TIME.replace(tzinfo=timezone.utc))

    def test_deadline_boundaries_and_follow_up_are_independent(self):
        opened = datetime(2026, 8, 14, 12)
        self.assertEqual(sla_state("P2", opened, datetime(2026, 8, 14, 14, 59, 59))[0], "ON TRACK")
        self.assertEqual(sla_state("P2", opened, datetime(2026, 8, 14, 15))[0], "AT RISK")
        self.assertEqual(sla_state("P2", opened, DEMO_TIME)[0], "OVERDUE")
        row = next(row for row in dashboard(self.db, DEMO_TIME) if row["ticket_id"] == "INC-1003")
        self.assertEqual(row["state"], "AT RISK")
        self.assertEqual(row["follow_up_state"], "DUE")
        update_ticket("INC-1003", self.db, clear_follow_up=True, at=DEMO_TIME)
        row = next(row for row in dashboard(self.db, DEMO_TIME) if row["ticket_id"] == "INC-1003")
        self.assertEqual(row["state"], "AT RISK")
        self.assertEqual(row["follow_up_state"], "NOT SET")

    def test_evaluation_before_opening_is_rejected_across_reports(self):
        earlier = datetime(2026, 8, 14, 15)
        for reader in (dashboard, operational_metrics, snapshot):
            with self.subTest(reader=reader.__name__), self.assertRaises(ValueError):
                reader(self.db, earlier)

    def test_weekly_window_is_open_start_closed_end_and_counts_events(self):
        with connect(self.db) as connection:
            for seconds, kind in ((-7 * 24 * 3600, "NOTE"), (-7 * 24 * 3600 + 1, "NOTE"), (0, "NOTE"), (1, "NOTE")):
                at = DEMO_TIME + timedelta(seconds=seconds)
                connection.execute("INSERT INTO ticket_events (ticket_id,event_type,details,created_at) VALUES ('INC-1001', ?, 'Boundary event', ?)", (kind, at.isoformat()))
        report = snapshot(self.db, DEMO_TIME)
        self.assertEqual(report["activity_counts"]["NOTE"], 2)
        self.assertEqual(report["activity_counts"]["RESOLVED"], 0)
        self.assertEqual(report["metrics"]["resolved_tickets"], 2)
        self.assertIn("not a reconstruction", weekly_markdown(report))

    def test_report_escapes_html_scripts_and_markdown_table_text(self):
        payload = '</script><script>alert("x")</script> | [link](javascript:x)\nnext'
        with connect(self.db) as connection:
            connection.execute("UPDATE tickets SET summary = ? WHERE ticket_id = 'INC-1001'", (payload,))
            connection.execute("INSERT INTO ticket_events (ticket_id,event_type,details,created_at) VALUES ('INC-1001','NOTE',?,?)", (payload, DEMO_TIME.isoformat()))
        output = self.root / "report.html"
        write_dashboard(output, self.db, DEMO_TIME)
        content = output.read_text()
        parser = ScriptCollector()
        parser.feed(content)
        self.assertEqual(len(parser.scripts), 2)
        record = json.loads(parser.scripts[0])
        self.assertEqual(next(t for t in record["tickets"] if t["ticket_id"] == "INC-1001")["summary"], payload)
        self.assertNotIn(payload, content)
        markdown = weekly_markdown(record)
        self.assertIn("&lt;/script&gt;", markdown)
        self.assertIn("\\|", markdown)
        self.assertNotIn("[link](javascript:x)", markdown)

    def test_empty_queue_and_exports_keep_their_structure(self):
        with connect(self.db) as connection:
            connection.execute("DELETE FROM ticket_events")
            connection.execute("DELETE FROM tickets")
        self.assertEqual(dashboard(self.db, DEMO_TIME), [])
        self.assertEqual(operational_metrics(self.db, DEMO_TIME)["active_tickets"], 0)
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            print_rows([], ["ticket_id", "summary"])
        self.assertIn("TICKET_ID", captured.getvalue())
        write_dashboard(self.root / "empty.html", self.db, DEMO_TIME)
        write_weekly_summary(self.root / "empty.md", self.db, DEMO_TIME)
        self.assertIn("No active tickets", (self.root / "empty.md").read_text())
        export_operational_data(self.root / "export", self.db)
        with (self.root / "export" / "tickets.csv").open() as handle:
            header = next(csv.reader(handle))
        self.assertIn("owner", header)
        self.assertIn("ticket_id", header)

    def test_csv_neutralizes_formula_like_user_text(self):
        with connect(self.db) as connection:
            connection.execute("UPDATE tickets SET summary = '=1+1' WHERE ticket_id = 'INC-1001'")
        export_operational_data(self.root / "export", self.db)
        with (self.root / "export" / "tickets.csv").open() as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(row["summary"], "'=1+1")


if __name__ == "__main__":
    unittest.main()
