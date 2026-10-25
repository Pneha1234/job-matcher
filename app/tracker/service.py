"""Applications (kanban) with a full status history, and per-job flags (hidden)."""

import csv
import io
import sqlite3
from typing import Literal

from app.util import days_ago, now_iso, parse_iso, utcnow

Status = Literal["saved", "applied", "interviewing", "offer", "rejected", "withdrawn", "archived"]
FOLLOW_UP_DAYS = 14


class TrackerError(ValueError):
    pass


def _job_exists(conn: sqlite3.Connection, job_id: int) -> None:
    if not conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone():
        raise TrackerError("Job not found")


def set_status(conn: sqlite3.Connection, job_id: int, status: Status, note: str | None = None):
    _job_exists(conn, job_id)
    now = now_iso()
    with conn:
        row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        previous = row["status"] if row else None
        if previous == status:
            return {"application": get(conn, row["id"]), "previous_status": previous}
        if row:
            applied_at = row["applied_at"]
            if status == "applied" and not applied_at:
                applied_at = now
            conn.execute(
                "UPDATE applications SET status = ?, applied_at = ?, status_changed_at = ?, "
                "updated_at = ? WHERE id = ?",
                (status, applied_at, now, now, row["id"]),
            )
            app_id = row["id"]
        else:
            app_id = conn.execute(
                "INSERT INTO applications (job_id, status, applied_at, status_changed_at) "
                "VALUES (?, ?, ?, ?)",
                (job_id, status, now if status in ("applied",) else None, now),
            ).lastrowid
        conn.execute(
            "INSERT INTO application_events (application_id, from_status, to_status, note) "
            "VALUES (?, ?, ?, ?)",
            (app_id, previous, status, note),
        )
    return {"application": get(conn, app_id), "previous_status": previous or "archived"}


def set_notes(conn: sqlite3.Connection, app_id: int, notes: str) -> dict:
    with conn:
        cur = conn.execute(
            "UPDATE applications SET notes = ?, updated_at = ? WHERE id = ?",
            (notes[:5000], now_iso(), app_id),
        )
    if not cur.rowcount:
        raise TrackerError("Application not found")
    return get(conn, app_id)


BOARD_SQL = """
SELECT a.*, j.title, j.company_name, j.status AS job_status, j.expired_reason,
    (SELECT url FROM job_sources s WHERE s.job_id = j.id ORDER BY s.id LIMIT 1) AS url,
    ms.final_pct
FROM applications a JOIN jobs j ON j.id = a.job_id
LEFT JOIN match_scores ms ON ms.job_id = j.id AND ms.profile_version_id =
    (SELECT id FROM profile_versions WHERE is_active = 1)
"""


def _shape(r: sqlite3.Row) -> dict:
    applied = parse_iso(r["applied_at"])
    days = (utcnow() - applied).days if applied else None
    return {
        "id": r["id"],
        "job_id": r["job_id"],
        "status": r["status"],
        "title": r["title"],
        "company": r["company_name"],
        "url": r["url"],
        "match_pct": r["final_pct"],
        "applied_at": r["applied_at"],
        "days_since_applied": days,
        "follow_up": r["status"] == "applied" and days is not None and days >= FOLLOW_UP_DAYS,
        "posting_expired": r["job_status"] != "active",
        "expired_reason": r["expired_reason"],
        "notes": r["notes"],
        "status_changed_at": r["status_changed_at"],
        "updated_at": r["updated_at"],
    }


def get(conn: sqlite3.Connection, app_id: int) -> dict:
    row = conn.execute(f"{BOARD_SQL} WHERE a.id = ?", (app_id,)).fetchone()
    if not row:
        raise TrackerError("Application not found")
    return _shape(row)


def board(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"{BOARD_SQL} WHERE a.status != 'archived' ORDER BY a.status_changed_at DESC"
    ).fetchall()
    return [_shape(r) for r in rows]


def events(conn: sqlite3.Connection, app_id: int) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT from_status, to_status, note, at FROM application_events "
            "WHERE application_id = ? ORDER BY at, id",
            (app_id,),
        )
    ]


def export_csv(conn: sqlite3.Connection) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["Company", "Title", "Status", "Match %", "Applied at", "Posting", "URL", "Notes"]
    )
    for a in board(conn):
        writer.writerow(
            [
                a["company"],
                a["title"],
                a["status"],
                a["match_pct"] if a["match_pct"] is not None else "",
                (a["applied_at"] or "")[:10],
                "expired" if a["posting_expired"] else "active",
                a["url"] or "",
                a["notes"],
            ]
        )
    return out.getvalue()


def set_hidden(conn: sqlite3.Connection, job_id: int, hidden: bool, reason: str | None = None):
    _job_exists(conn, job_id)
    with conn:
        conn.execute(
            "INSERT INTO user_job_flags (job_id, hidden, not_interested_reason, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (job_id) DO UPDATE SET hidden = excluded.hidden, "
            "not_interested_reason = COALESCE(excluded.not_interested_reason, "
            "user_job_flags.not_interested_reason), updated_at = excluded.updated_at",
            (job_id, int(hidden), reason, now_iso()),
        )
    return {"job_id": job_id, "hidden": hidden}


def counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM applications GROUP BY status").fetchall()
    by = {r["status"]: r["n"] for r in rows}
    recent = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE applied_at >= ?", (days_ago(30),)
    ).fetchone()[0]
    return {"by_status": by, "applied_30d": recent}
