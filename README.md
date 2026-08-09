# Job Application Tracker

A personal, self-hosted job application tracker. Log applications, track their status through your pipeline, and keep interview rounds, contacts, and follow-up dates in one place. No accounts, no cloud, no tracking. Runs locally against a SQLite file you own.

## Features

- Full CRUD on applications: company, role, job description, date applied, status, notes, follow-up date, job posting URL, and recruiter contact (name, email, LinkedIn).
- Ten-stage status pipeline: Saved, Applied, Phone Screen, Interview, Onsite, Negotiating, Offer, Rejected, Withdrawn, Ghosted.
- Per-application interview round timeline with dates and outcomes.
- Soft deletes with a one-day undo window.
- Dashboard stats: total applied, active pipeline, interview rate, offer rate, and a simple Applied to Interview to Offer funnel.
- Automatic days-since-applied and days-since-last-update tracking, with overdue follow-ups highlighted.
- Search and filter by company and status.
- CSV export and import for bulk data moves.
- One-click raw SQLite backup download.
- Dark mode and keyboard shortcuts (`n` for new application, `/` for search).

## Requirements

- Python 3.9 or later
- Flask

## Setup

Clone the repository, then from the project folder:

```
pip install -r requirements.txt
python app.py
```

The app runs at `http://127.0.0.1:5000` by default. On first run it creates a local `job_applications.db` SQLite file in the project folder. This file is not tracked in git, since it holds your personal data.

## Usage

Add an application from the form on the main page. Update its status, add interview rounds, and set a follow-up date from the edit page. Use the search box and status filter to find entries once your list grows. Export your data to CSV or download a raw database backup anytime from the toolbar.

## Data and privacy

All data stays local in `job_applications.db`. Nothing is sent anywhere. If you back this project up or move it to another machine, copy that file along with the repo; it is intentionally excluded from git via `.gitignore`.

## Development notes

This app runs with Flask's debug server (`app.run(debug=True)`), which is fine for local personal use but is not meant to be exposed to the internet or run in production as-is. If you ever want to deploy it beyond your own machine, put it behind a production WSGI server (gunicorn, waitress) and turn debug mode off.

## License

MIT. See `LICENSE`.
