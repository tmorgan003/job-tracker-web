# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
A single user (the app's owner) tracking their own job search. No accounts, no multi-user access — the app runs locally against a single SQLite file.

## Product Purpose
A personal job application tracker: log applications, see their status at a glance, and edit or remove entries as the search progresses. Success is simply having an accurate, low-friction record of where things stand across active applications.

## Positioning
Not a market-facing product — a self-built personal tool. Its value is being lighter-weight and more tailored than a spreadsheet or a general-purpose tracker someone else built.

## Operating Context
Used solo, likely in short sessions while applying to jobs or checking status — add an entry right after applying, revisit to update status after interviews/responses, occasionally scan the full list for that "where do things stand" view.

## Capabilities and Constraints
- CRUD on applications: company, role, job description, date applied, status, notes, follow-up date, job posting URL, recruiter/hiring-manager contact (name/email/LinkedIn).
- Status pipeline expanded beyond applied/interview/offer/rejected to: saved, applied, phone screen, interview, onsite, negotiating, offer, rejected, withdrawn, ghosted.
- Per-application interview-round timeline (round name, date, outcome), managed from the edit page.
- Deletes are soft (undo window, ~1 day) rather than immediate/irreversible; expired soft-deletes are purged automatically.
- Dashboard stats bar (total applied, active pipeline, interview rate, offer rate) and a simple Applied → Interview → Offer funnel, computed from live data.
- Days-since-applied and days-since-last-status-change are computed automatically per row; overdue follow-up dates are highlighted in the table.
- CSV export/import for bulk data movement, plus a one-click raw SQLite file backup download.
- Company+role duplicates are flagged with a non-blocking warning rather than prevented.
- Dark mode (CSS-variable based, toggle + system-preference aware) and keyboard shortcuts (`n` new application, `/` search) for low-friction solo use.
- Backed by local SQLite (`job_applications.db`); Flask server-rendered pages, no client-side framework (vanilla JS only for interactivity).
- No authentication, no multi-user support — explicitly out of scope per current decision.

## Brand Commitments
Visual world: modern business / SaaS-utility aesthetic, calibrated against Linear and Notion as the craft bar — crisp, minimal, generous whitespace, hairline borders instead of heavy shadows, restrained type hierarchy, no decorative chrome. Palette is pinned to blues, greys, whites, and blacks only (no red/green/warm accents); status differentiation is carried by value and saturation within that palette rather than hue variety. This replaced an earlier rustic/graph-paper visual world per explicit user request (2026-08-08).

## Product Principles
- Keep it low-friction: adding or updating an entry should take seconds, not feel like data entry.
- Status at a glance matters more than depth of detail per entry.
- Single-user simplicity is a feature, not a gap to fill — resist adding accounts/auth complexity unless the user asks.
- Prefer the tool getting out of the way over configurability or extra workflow steps.
