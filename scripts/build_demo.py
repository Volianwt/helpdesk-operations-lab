#!/usr/bin/env python3
"""Regenerate the checked-in synthetic report without touching the working DB."""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from helpdesk_lab import DEMO_TIME, add_note, initialize, resolve_ticket, update_ticket
from reporting import write_dashboard, write_weekly_summary


def main():
    with tempfile.TemporaryDirectory(prefix="helpdesk-demo-") as directory:
        db = Path(directory) / "demo.db"
        initialize(db)
        update_ticket("INC-1001", db, owner="Service Desk", follow_up_due=datetime(2026, 8, 14, 15, 45),
                      notes="Confirm Finance can open the shared folder after the mapped-drive test.",
                      at=datetime(2026, 8, 14, 14))
        add_note("INC-1001", "DNS lookup succeeds; waiting for Finance to confirm the mapped-drive test result.", db, datetime(2026, 8, 14, 14, 30))
        add_note("INC-1003", "Security escalation recorded. Waiting for the responsible security owner to acknowledge the handover.", db, datetime(2026, 8, 14, 15, 30))
        resolve_ticket("INC-1002", "Selected the approved headset and confirmed a successful Teams test call in the simulated scenario.", db, datetime(2026, 8, 14, 15, 50))
        write_dashboard(ROOT / "docs" / "demo-dashboard.html", db, DEMO_TIME)
        write_weekly_summary(ROOT / "docs" / "demo-weekly-summary.md", db, DEMO_TIME)
    print("Updated docs/demo-dashboard.html and docs/demo-weekly-summary.md from a temporary database.")


if __name__ == "__main__":
    main()
