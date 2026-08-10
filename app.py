import csv
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

from flask import (
    Flask,
    Response,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from markupsafe import Markup, escape

DATABASE = Path(__file__).parent / "job_applications.db"

STATUS_LABELS = {
    "saved": "Saved",
    "applied": "Applied",
    "phone_screen": "Phone Screen",
    "interview": "Interview",
    "onsite": "Onsite",
    "negotiating": "Negotiating",
    "offer": "Offer",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
    "ghosted": "Ghosted",
}
STATUSES = list(STATUS_LABELS.keys())
TERMINAL_STATUSES = {"rejected", "withdrawn", "ghosted"}
ACTIVE_STATUSES = {"applied", "phone_screen", "interview", "onsite", "negotiating"}
INTERVIEW_STAGE_STATUSES = {"phone_screen", "interview", "onsite", "negotiating", "offer"}

ROUND_OUTCOME_LABELS = {
    "pending": "Pending",
    "passed": "Passed",
    "failed": "Failed",
    "cancelled": "Cancelled",
}
ROUND_OUTCOMES = list(ROUND_OUTCOME_LABELS.keys())

SORT_COLUMNS = {"date_applied", "status", "follow_up_date"}
UNDO_WINDOW = timedelta(days=1)

CSV_COLUMNS = [
    "company",
    "role",
    "job_description",
    "date_applied",
    "status",
    "notes",
    "follow_up_date",
    "job_url",
    "recruiter_name",
    "recruiter_email",
    "recruiter_linkedin",
]

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DATABASE) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                job_description TEXT,
                date_applied TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'applied',
                notes TEXT
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS interview_rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                round_name TEXT NOT NULL,
                round_date TEXT,
                outcome TEXT NOT NULL DEFAULT 'pending'
            )
            """
        )

        existing_columns = {row[1] for row in db.execute("PRAGMA table_info(applications)")}
        new_columns = {
            "follow_up_date": "TEXT",
            "job_url": "TEXT",
            "recruiter_name": "TEXT",
            "recruiter_email": "TEXT",
            "recruiter_linkedin": "TEXT",
            "last_status_change": "TEXT",
            "deleted_at": "TEXT",
        }
        for name, coltype in new_columns.items():
            if name not in existing_columns:
                db.execute(f"ALTER TABLE applications ADD COLUMN {name} {coltype}")

        db.execute(
            "UPDATE applications SET last_status_change = date_applied WHERE last_status_change IS NULL"
        )


def purge_expired_deletions(db):
    cutoff = (datetime.utcnow() - UNDO_WINDOW).isoformat()
    expired_ids = [
        row[0]
        for row in db.execute(
            "SELECT id FROM applications WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        )
    ]
    if not expired_ids:
        return
    placeholders = ",".join("?" for _ in expired_ids)
    db.execute(f"DELETE FROM interview_rounds WHERE application_id IN ({placeholders})", expired_ids)
    db.execute(f"DELETE FROM applications WHERE id IN ({placeholders})", expired_ids)
    db.commit()


def get_form_fields():
    status = request.form.get("status", "")
    return {
        "company": request.form.get("company", "").strip(),
        "role": request.form.get("role", "").strip(),
        "job_description": request.form.get("job_description", "").strip(),
        "date_applied": request.form.get("date_applied", "").strip(),
        "status": status if status in STATUSES else STATUSES[1],
        "notes": request.form.get("notes", "").strip(),
        "follow_up_date": request.form.get("follow_up_date", "").strip() or None,
        "job_url": request.form.get("job_url", "").strip(),
        "recruiter_name": request.form.get("recruiter_name", "").strip(),
        "recruiter_email": request.form.get("recruiter_email", "").strip(),
        "recruiter_linkedin": request.form.get("recruiter_linkedin", "").strip(),
    }


def validate_fields(fields):
    missing = []
    if not fields["company"]:
        missing.append("Company")
    if not fields["role"]:
        missing.append("Role")
    return missing


def missing_fields_message(missing):
    joined = " and ".join(missing)
    verb = "is" if len(missing) == 1 else "are"
    return f"{joined} {verb} required."


def find_duplicate(db, company, role, exclude_id=None):
    sql = (
        "SELECT id FROM applications WHERE deleted_at IS NULL "
        "AND LOWER(company) = LOWER(:company) AND LOWER(role) = LOWER(:role)"
    )
    params = {"company": company, "role": role}
    if exclude_id is not None:
        sql += " AND id != :id"
        params["id"] = exclude_id
    return db.execute(sql, params).fetchone()


def compute_stats(db):
    rows = db.execute("SELECT status FROM applications WHERE deleted_at IS NULL").fetchall()
    total_applied = sum(1 for r in rows if r["status"] != "saved")
    active_pipeline = sum(1 for r in rows if r["status"] in ACTIVE_STATUSES)
    offer_count = sum(1 for r in rows if r["status"] == "offer")

    interview_stage_placeholders = ",".join("?" for _ in INTERVIEW_STAGE_STATUSES)
    interview_reached = db.execute(
        f"""
        SELECT COUNT(DISTINCT a.id) FROM applications a
        LEFT JOIN interview_rounds r ON r.application_id = a.id
        WHERE a.deleted_at IS NULL AND a.status != 'saved'
        AND (r.id IS NOT NULL OR a.status IN ({interview_stage_placeholders}))
        """,
        list(INTERVIEW_STAGE_STATUSES),
    ).fetchone()[0]

    interview_rate = round(interview_reached / total_applied * 100) if total_applied else 0
    offer_rate = round(offer_count / total_applied * 100) if total_applied else 0

    funnel = [
        ("Applied", total_applied),
        ("Interview", interview_reached),
        ("Offer", offer_count),
    ]

    return {
        "total_applied": total_applied,
        "active_pipeline": active_pipeline,
        "interview_rate": interview_rate,
        "offer_rate": offer_rate,
        "funnel": funnel,
    }


def avg_days(values):
    return round(sum(values) / len(values), 1) if values else None


def compute_reports(db):
    today = date.today()

    apps = db.execute(
        "SELECT id, company, role, date_applied, status, last_status_change, "
        "follow_up_date, recruiter_name, recruiter_email, recruiter_linkedin "
        "FROM applications WHERE deleted_at IS NULL"
    ).fetchall()
    total_count = len(apps)
    considered = [a for a in apps if a["status"] != "saved"]
    total_considered = len(considered)

    round_rows = db.execute(
        "SELECT application_id, round_name, round_date, outcome FROM interview_rounds"
    ).fetchall()
    rounds_by_app_id = {}
    for r in round_rows:
        rounds_by_app_id.setdefault(r["application_id"], []).append(r)

    def reached_interview(a):
        return a["id"] in rounds_by_app_id or a["status"] in INTERVIEW_STAGE_STATUSES

    offer_count = sum(1 for a in considered if a["status"] == "offer")
    rejected_count = sum(1 for a in considered if a["status"] == "rejected")
    interview_reached = sum(1 for a in considered if reached_interview(a))

    overview = {
        "total_applications": total_count,
        "total_applied": total_considered,
        "active_pipeline": sum(1 for a in considered if a["status"] in ACTIVE_STATUSES),
        "interview_rate": round(interview_reached / total_considered * 100) if total_considered else 0,
        "offer_rate": round(offer_count / total_considered * 100) if total_considered else 0,
        "rejection_rate": round(rejected_count / total_considered * 100) if total_considered else 0,
    }

    # Status breakdown, most common first.
    status_counts = {}
    for a in apps:
        status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1
    status_breakdown = [
        (STATUS_LABELS[s], status_counts.get(s, 0)) for s in STATUSES if status_counts.get(s, 0) > 0
    ]
    status_breakdown.sort(key=lambda item: item[1], reverse=True)
    max_status_count = max((c for _, c in status_breakdown), default=0)

    # Applications submitted per month, last 12 months.
    month_keys = []
    for offset in range(11, -1, -1):
        total_month = today.month - 1 - offset
        year = today.year + total_month // 12
        month = total_month % 12 + 1
        month_keys.append(f"{year:04d}-{month:02d}")
    month_counts = {}
    for a in considered:
        key = (a["date_applied"] or "")[:7]
        if key in month_keys:
            month_counts[key] = month_counts.get(key, 0) + 1
    volume_by_month = [
        (datetime.strptime(k, "%Y-%m").strftime("%b %Y"), month_counts.get(k, 0)) for k in month_keys
    ]
    max_month_count = max((c for _, c in volume_by_month), default=0)

    # Time-in-pipeline metrics.
    days_to_interview, days_to_offer, days_to_rejection, active_ages = [], [], [], []
    for a in apps:
        try:
            applied = date.fromisoformat(a["date_applied"])
        except (TypeError, ValueError):
            continue
        app_rounds = [r for r in rounds_by_app_id.get(a["id"], []) if r["round_date"]]
        if app_rounds:
            try:
                first_round = min(date.fromisoformat(r["round_date"]) for r in app_rounds)
                days_to_interview.append((first_round - applied).days)
            except ValueError:
                pass
        if a["status"] == "offer" and a["last_status_change"]:
            try:
                days_to_offer.append((date.fromisoformat(a["last_status_change"]) - applied).days)
            except ValueError:
                pass
        if a["status"] == "rejected" and a["last_status_change"]:
            try:
                days_to_rejection.append((date.fromisoformat(a["last_status_change"]) - applied).days)
            except ValueError:
                pass
        if a["status"] in ACTIVE_STATUSES:
            active_ages.append((today - applied).days)

    time_metrics = {
        "avg_days_to_interview": avg_days(days_to_interview),
        "avg_days_to_offer": avg_days(days_to_offer),
        "avg_days_to_rejection": avg_days(days_to_rejection),
        "avg_active_age": avg_days(active_ages),
        "oldest_active_age": max(active_ages) if active_ages else None,
    }

    # Interview round performance, grouped by round name.
    round_perf = {}
    for r in round_rows:
        entry = round_perf.setdefault(r["round_name"], {o: 0 for o in ROUND_OUTCOMES})
        entry[r["outcome"]] = entry.get(r["outcome"], 0) + 1
    round_performance = []
    for name, counts in round_perf.items():
        total = sum(counts.values())
        decided = counts["passed"] + counts["failed"]
        pass_rate = round(counts["passed"] / decided * 100) if decided else None
        round_performance.append(
            {"name": name, "total": total, "counts": counts, "pass_rate": pass_rate}
        )
    round_performance.sort(key=lambda r: r["total"], reverse=True)

    # Repeat applications by company.
    company_stats = {}
    for a in apps:
        key = a["company"].strip().lower()
        entry = company_stats.setdefault(key, {"company": a["company"], "count": 0, "offers": 0, "rejections": 0})
        entry["count"] += 1
        if a["status"] == "offer":
            entry["offers"] += 1
        if a["status"] == "rejected":
            entry["rejections"] += 1
    repeat_companies = sorted(
        (c for c in company_stats.values() if c["count"] > 1),
        key=lambda c: c["count"],
        reverse=True,
    )[:10]

    # Recruiter contact impact.
    def has_recruiter(a):
        return bool(a["recruiter_name"] or a["recruiter_email"] or a["recruiter_linkedin"])

    with_recruiter = [a for a in considered if has_recruiter(a)]
    without_recruiter = [a for a in considered if not has_recruiter(a)]

    def interview_rate(subset):
        return round(sum(1 for a in subset if reached_interview(a)) / len(subset) * 100) if subset else None

    recruiter_impact = {
        "with_count": len(with_recruiter),
        "with_rate": interview_rate(with_recruiter),
        "without_count": len(without_recruiter),
        "without_rate": interview_rate(without_recruiter),
    }

    # Follow-up compliance.
    overdue_followups = []
    upcoming_followups = []
    for a in apps:
        if not a["follow_up_date"] or a["status"] in TERMINAL_STATUSES:
            continue
        try:
            fu = date.fromisoformat(a["follow_up_date"])
        except ValueError:
            continue
        if fu < today:
            overdue_followups.append(a)
        elif fu <= today + timedelta(days=7):
            upcoming_followups.append(a)
    overdue_followups.sort(key=lambda a: a["follow_up_date"])
    upcoming_followups.sort(key=lambda a: a["follow_up_date"])

    return {
        "overview": overview,
        "status_breakdown": status_breakdown,
        "max_status_count": max_status_count,
        "volume_by_month": volume_by_month,
        "max_month_count": max_month_count,
        "time_metrics": time_metrics,
        "round_performance": round_performance,
        "round_outcome_labels": ROUND_OUTCOME_LABELS,
        "repeat_companies": repeat_companies,
        "recruiter_impact": recruiter_impact,
        "overdue_followups": overdue_followups,
        "upcoming_followups": upcoming_followups,
    }


def annotate_application(row):
    a = dict(row)
    today = date.today()
    try:
        a["days_since_applied"] = (today - date.fromisoformat(a["date_applied"])).days
    except (TypeError, ValueError):
        a["days_since_applied"] = None
    status_change = a["last_status_change"] or a["date_applied"]
    try:
        a["days_since_status_change"] = (today - date.fromisoformat(status_change)).days
    except (TypeError, ValueError):
        a["days_since_status_change"] = None
    try:
        a["follow_up_passed"] = bool(
            a["follow_up_date"] and date.fromisoformat(a["follow_up_date"]) < today
        )
    except ValueError:
        a["follow_up_passed"] = False
    return a


@app.route("/")
def index():
    db = get_db()
    purge_expired_deletions(db)

    query = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "")
    if status_filter not in STATUSES:
        status_filter = ""
    sort = request.args.get("sort", "date_applied")
    if sort not in SORT_COLUMNS:
        sort = "date_applied"
    direction = request.args.get("dir", "desc")
    if direction not in ("asc", "desc"):
        direction = "desc"

    total_count = db.execute(
        "SELECT COUNT(*) FROM applications WHERE deleted_at IS NULL"
    ).fetchone()[0]

    sql = "SELECT * FROM applications WHERE deleted_at IS NULL"
    params = {}
    if query:
        sql += " AND LOWER(company) LIKE LOWER(:q)"
        params["q"] = f"%{query}%"
    if status_filter:
        sql += " AND status = :status"
        params["status"] = status_filter
    sql += f" ORDER BY {sort} {direction.upper()}, id DESC"

    applications = [annotate_application(r) for r in db.execute(sql, params).fetchall()]

    rounds_by_app = {}
    if applications:
        app_ids = [a["id"] for a in applications]
        placeholders = ",".join("?" for _ in app_ids)
        for r in db.execute(
            f"SELECT * FROM interview_rounds WHERE application_id IN ({placeholders}) "
            "ORDER BY round_date IS NULL, round_date, id",
            app_ids,
        ):
            rounds_by_app.setdefault(r["application_id"], []).append(dict(r))

    return render_template(
        "index.html",
        applications=applications,
        rounds_by_app=rounds_by_app,
        round_outcome_labels=ROUND_OUTCOME_LABELS,
        statuses=STATUSES,
        status_labels=STATUS_LABELS,
        today=date.today().isoformat(),
        query=query,
        status_filter=status_filter,
        sort=sort,
        direction=direction,
        total_count=total_count,
        filters_active=bool(query or status_filter),
        stats=compute_stats(db),
    )


@app.route("/reports")
def reports():
    db = get_db()
    purge_expired_deletions(db)
    return render_template("reports.html", reports=compute_reports(db), today=date.today().isoformat())


@app.route("/add", methods=["POST"])
def add():
    fields = get_form_fields()
    missing = validate_fields(fields)
    if missing:
        flash(missing_fields_message(missing), "error")
        return redirect(url_for("index"))
    db = get_db()
    duplicate = find_duplicate(db, fields["company"], fields["role"])
    fields["last_status_change"] = fields["date_applied"] or date.today().isoformat()
    db.execute(
        """
        INSERT INTO applications (
            company, role, job_description, date_applied, status, notes,
            follow_up_date, job_url, recruiter_name, recruiter_email, recruiter_linkedin,
            last_status_change
        )
        VALUES (
            :company, :role, :job_description, :date_applied, :status, :notes,
            :follow_up_date, :job_url, :recruiter_name, :recruiter_email, :recruiter_linkedin,
            :last_status_change
        )
        """,
        fields,
    )
    db.commit()
    if duplicate:
        flash(
            f"Heads up: you already have an application for {fields['company']} — {fields['role']}.",
            "warning",
        )
    flash("Application saved.", "success")
    return redirect(url_for("index"))


@app.route("/edit/<int:app_id>")
def edit(app_id):
    db = get_db()
    application = db.execute(
        "SELECT * FROM applications WHERE id = ? AND deleted_at IS NULL", (app_id,)
    ).fetchone()
    if application is None:
        return redirect(url_for("index"))
    rounds = db.execute(
        "SELECT * FROM interview_rounds WHERE application_id = ? ORDER BY round_date IS NULL, round_date, id",
        (app_id,),
    ).fetchall()
    return render_template(
        "edit.html",
        application=application,
        statuses=STATUSES,
        status_labels=STATUS_LABELS,
        rounds=rounds,
        round_outcomes=ROUND_OUTCOMES,
        round_outcome_labels=ROUND_OUTCOME_LABELS,
    )


@app.route("/edit/<int:app_id>", methods=["POST"])
def update(app_id):
    fields = get_form_fields()
    missing = validate_fields(fields)
    if missing:
        flash(missing_fields_message(missing), "error")
        return redirect(url_for("edit", app_id=app_id))

    db = get_db()
    current = db.execute("SELECT status, last_status_change FROM applications WHERE id = ?", (app_id,)).fetchone()
    duplicate = find_duplicate(db, fields["company"], fields["role"], exclude_id=app_id)

    fields["id"] = app_id
    fields["last_status_change"] = (
        date.today().isoformat()
        if current and current["status"] != fields["status"]
        else (current["last_status_change"] if current else date.today().isoformat())
    )
    db.execute(
        """
        UPDATE applications
        SET company = :company,
            role = :role,
            job_description = :job_description,
            date_applied = :date_applied,
            status = :status,
            notes = :notes,
            follow_up_date = :follow_up_date,
            job_url = :job_url,
            recruiter_name = :recruiter_name,
            recruiter_email = :recruiter_email,
            recruiter_linkedin = :recruiter_linkedin,
            last_status_change = :last_status_change
        WHERE id = :id
        """,
        fields,
    )
    db.commit()
    if duplicate:
        flash(
            f"Heads up: you already have another application for {fields['company']} — {fields['role']}.",
            "warning",
        )
    flash("Application updated.", "success")
    return redirect(url_for("index"))


@app.route("/delete/<int:app_id>", methods=["POST"])
def delete(app_id):
    db = get_db()
    application = db.execute("SELECT company, role FROM applications WHERE id = ?", (app_id,)).fetchone()
    if application is None:
        return redirect(url_for("index"))
    db.execute(
        "UPDATE applications SET deleted_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), app_id),
    )
    db.commit()
    undo_url = url_for("restore", app_id=app_id)
    message = Markup(
        f"Deleted {escape(application['company'])} — {escape(application['role'])}. "
        f'<a href="{undo_url}" class="undo-link" data-undo>Undo</a>'
    )
    flash(message, "undo")
    return redirect(url_for("index"))


@app.route("/restore/<int:app_id>", methods=["GET", "POST"])
def restore(app_id):
    db = get_db()
    db.execute(
        "UPDATE applications SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL", (app_id,)
    )
    db.commit()
    flash("Application restored.", "success")
    return redirect(url_for("index"))


@app.route("/rounds/<int:app_id>/add", methods=["POST"])
def add_round(app_id):
    db = get_db()
    application = db.execute(
        "SELECT id FROM applications WHERE id = ? AND deleted_at IS NULL", (app_id,)
    ).fetchone()
    if application is None:
        return redirect(url_for("index"))

    round_name = request.form.get("round_name", "").strip()
    round_date = request.form.get("round_date", "").strip() or None
    outcome = request.form.get("outcome", "")
    if outcome not in ROUND_OUTCOMES:
        outcome = ROUND_OUTCOMES[0]

    if not round_name:
        flash("Round name is required.", "error")
        return redirect(url_for("edit", app_id=app_id))

    db.execute(
        "INSERT INTO interview_rounds (application_id, round_name, round_date, outcome) VALUES (?, ?, ?, ?)",
        (app_id, round_name, round_date, outcome),
    )
    db.commit()
    flash("Interview round added.", "success")
    return redirect(url_for("edit", app_id=app_id))


@app.route("/rounds/<int:round_id>/delete", methods=["POST"])
def delete_round(round_id):
    db = get_db()
    round_row = db.execute(
        "SELECT application_id FROM interview_rounds WHERE id = ?", (round_id,)
    ).fetchone()
    if round_row is None:
        return redirect(url_for("index"))
    db.execute("DELETE FROM interview_rounds WHERE id = ?", (round_id,))
    db.commit()
    flash("Interview round removed.", "success")
    return redirect(url_for("edit", app_id=round_row["application_id"]))


@app.route("/export")
def export_csv():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM applications WHERE deleted_at IS NULL ORDER BY id"
    ).fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([row[col] for col in CSV_COLUMNS])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=job_applications_export.csv"},
    )


@app.route("/import/template")
def import_csv_template():
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    writer.writerow(
        [
            "Acme Corp",
            "Senior Software Engineer",
            "Backend role building payments infra.",
            date.today().isoformat(),
            "applied",
            "Referred by Jane.",
            "",
            "https://example.com/jobs/123",
            "Jane Recruiter",
            "jane@example.com",
            "https://linkedin.com/in/janerecruiter",
        ]
    )
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=job_applications_import_template.csv"},
    )


IMPORT_DATE_FORMATS = (
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%m-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
)

STATUS_LABEL_TO_KEY = {label.lower(): key for key, label in STATUS_LABELS.items()}


def parse_import_date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    for fmt in IMPORT_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_import_status(value):
    value = (value or "").strip()
    if not value:
        return None
    key = value.lower().replace(" ", "_").replace("-", "_")
    if key in STATUS_LABELS:
        return key
    return STATUS_LABEL_TO_KEY.get(value.lower())


@app.route("/import", methods=["POST"])
def import_csv():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("index"))

    try:
        content = file.stream.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("Could not read that file as UTF-8 CSV.", "error")
        return redirect(url_for("index"))

    reader = csv.DictReader(StringIO(content))
    db = get_db()
    imported = 0
    skipped = 0
    today = date.today().isoformat()

    for row in reader:
        company = (row.get("company") or "").strip()
        role = (row.get("role") or "").strip()
        if not company or not role:
            skipped += 1
            continue
        status = parse_import_status(row.get("status")) or "applied"
        date_applied = parse_import_date(row.get("date_applied")) or today
        follow_up_date = parse_import_date(row.get("follow_up_date"))

        db.execute(
            """
            INSERT INTO applications (
                company, role, job_description, date_applied, status, notes,
                follow_up_date, job_url, recruiter_name, recruiter_email, recruiter_linkedin,
                last_status_change
            )
            VALUES (:company, :role, :job_description, :date_applied, :status, :notes,
                    :follow_up_date, :job_url, :recruiter_name, :recruiter_email, :recruiter_linkedin,
                    :last_status_change)
            """,
            {
                "company": company,
                "role": role,
                "job_description": (row.get("job_description") or "").strip(),
                "date_applied": date_applied,
                "status": status,
                "notes": (row.get("notes") or "").strip(),
                "follow_up_date": follow_up_date,
                "job_url": (row.get("job_url") or "").strip(),
                "recruiter_name": (row.get("recruiter_name") or "").strip(),
                "recruiter_email": (row.get("recruiter_email") or "").strip(),
                "recruiter_linkedin": (row.get("recruiter_linkedin") or "").strip(),
                "last_status_change": date_applied,
            },
        )
        imported += 1

    db.commit()
    flash(f"Imported {imported} application(s), skipped {skipped}.", "success" if imported else "error")
    return redirect(url_for("index"))


@app.route("/backup")
def backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(
        DATABASE,
        as_attachment=True,
        download_name=f"job_applications_backup_{timestamp}.db",
    )


init_db()

if __name__ == "__main__":
    app.run(debug=True)
