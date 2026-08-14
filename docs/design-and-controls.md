# Design and Controls

## Operational problem

An internal helpdesk has to do more than fix isolated technical symptoms. It needs consistent intake, a defensible priority, visible SLA risk, safe diagnostic boundaries, useful notes for the next technician, accurate device and licence records, and confirmation that the user can work again.

This lab models those responsibilities without pretending to be a production IT service-management platform.

## Core decisions

### Priority is derived, not guessed

Impact and urgency are recorded separately and mapped to P1-P4. The mapping is intentionally simple enough for a Tier 1 technician to explain. A security category is escalated independently because a low apparent business impact does not make a suspected compromise safe to close locally.

### SLA state is calculated from the ticket record

The dashboard calculates due time from `opened_at` and the priority policy. Tickets are ordered by overdue, at-risk, and on-track state. This keeps attention on user impact and commitments instead of ticket age alone.

### Resolution requires evidence

The resolve command rejects empty or meaningless notes. A successful resolution updates the ticket and adds a timestamped event; the original request remains available for later review. A real service desk would also record technician identity and user confirmation through authenticated accounts.

### Tier 1 boundaries are explicit

The knowledge-base articles favour read-only inspection, known-good tests, approved request paths, and early escalation. They do not instruct a technician to grant access, disable security controls, erase evidence, forward malicious content, or make unapproved infrastructure changes.

### Operational records are portable

SQLite keeps the project easy to run and inspect. CSV exports make the ticket, asset, licence, and audit-event records reviewable without installing the application. A production system would use authentication, role-based access, encryption, retention policies, backups, and API integrations.

## Data model

- `tickets`: request, category, impact, urgency, priority, status, asset, and resolution notes
- `ticket_events`: timestamped creation and resolution history
- `assets`: tag, type, platform, lifecycle state, and assignment
- `software_licenses`: owned seats, assigned seats, and renewal date

## Validation strategy

The automated tests verify the priority matrix, seed integrity, resolved-ticket filtering, SLA queue order, knowledge-base search, security escalation, resolution/audit consistency, operational metrics, and CSV generation. GitHub Actions runs the same suite on every push and pull request.
