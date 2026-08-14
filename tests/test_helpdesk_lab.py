import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpdesk_lab import (
    calculate_priority,
    connect,
    dashboard,
    export_operational_data,
    initialize,
    operational_metrics,
    resolve_ticket,
    search_kb,
)


class HelpdeskLabTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "lab.db"
        initialize(self.db_path, reset=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_priority_matrix(self):
        self.assertEqual(calculate_priority("high", "high"), "P1")
        self.assertEqual(calculate_priority("medium", "high"), "P2")
        self.assertEqual(calculate_priority("medium", "medium"), "P3")
        self.assertEqual(calculate_priority("low", "low"), "P4")

    def test_seeded_record_counts(self):
        with connect(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0], 12)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM assets").fetchone()[0], 10)

    def test_dashboard_excludes_resolved_tickets(self):
        rows = dashboard(self.db_path, datetime.fromisoformat("2026-08-14T16:00:00"))
        ids = {row["ticket_id"] for row in rows}
        self.assertNotIn("INC-1006", ids)
        self.assertNotIn("REQ-1012", ids)
        self.assertIn("INC-1003", ids)

    def test_dashboard_orders_overdue_first(self):
        rows = dashboard(self.db_path, datetime.fromisoformat("2026-08-14T16:00:00"))
        states = [row["state"] for row in rows]
        self.assertEqual(states, sorted(states, key={"OVERDUE": 0, "AT RISK": 1, "ON TRACK": 2}.get))

    def test_knowledge_base_search(self):
        results = search_kb("Teams microphone")
        self.assertTrue(results)
        self.assertEqual(results[0][1], "microsoft_365_teams_sharepoint.md")

    def test_security_ticket_is_flagged_for_escalation(self):
        rows = dashboard(self.db_path, datetime.fromisoformat("2026-08-14T16:00:00"))
        security = next(row for row in rows if row["ticket_id"] == "INC-1003")
        self.assertEqual(security["escalation"], "SECURITY")

    def test_resolution_updates_ticket_and_audit_trail(self):
        resolve_ticket(
            "INC-1002",
            "Selected the approved headset and confirmed a successful Teams test call.",
            self.db_path,
            datetime.fromisoformat("2026-08-14T16:10:00"),
        )
        with connect(self.db_path) as connection:
            ticket = connection.execute(
                "SELECT status, resolution_notes FROM tickets WHERE ticket_id = 'INC-1002'"
            ).fetchone()
            event = connection.execute(
                "SELECT event_type, details FROM ticket_events WHERE ticket_id = 'INC-1002' ORDER BY event_id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(ticket["status"], "Resolved")
        self.assertIn("successful Teams test call", ticket["resolution_notes"])
        self.assertEqual(event["event_type"], "RESOLVED")

    def test_metrics_and_csv_exports(self):
        metrics = operational_metrics(self.db_path, datetime.fromisoformat("2026-08-14T16:00:00"))
        self.assertEqual(metrics["active_tickets"], 10)
        self.assertGreater(metrics["escalations"], 0)
        export_dir = Path(self.temp_dir.name) / "exports"
        files = export_operational_data(export_dir, self.db_path)
        self.assertEqual(len(files), 4)
        self.assertTrue(all(path.exists() and path.stat().st_size > 0 for path in files))


if __name__ == "__main__":
    unittest.main()
