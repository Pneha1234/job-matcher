"""What changed recently, for desktop notifications and the daily digest."""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.api.deps import DbDep
from app.profile import store
from app.settings_store import load
from app.tracker import service as tracker
from app.util import days_ago

router = APIRouter(tags=["digest"])


def top_matches(db, since: str, threshold: int) -> list[dict]:
    active = store.active(db)
    if not active:
        return []
    rows = db.execute(
        "SELECT j.id, j.title, j.company_name, ms.final_pct, ms.scored_at FROM match_scores ms "
        "JOIN jobs j ON j.id = ms.job_id LEFT JOIN user_job_flags f ON f.job_id = j.id "
        "LEFT JOIN applications a ON a.job_id = j.id "
        "WHERE ms.profile_version_id = ? AND ms.status = 'scored' AND ms.final_pct >= ? "
        "AND ms.scored_at > ? AND j.status = 'active' AND j.duplicate_of IS NULL "
        "AND COALESCE(f.hidden, 0) = 0 AND COALESCE(a.status, 'archived') = 'archived' "
        "ORDER BY ms.final_pct DESC",
        (active["id"], threshold, since),
    ).fetchall()
    return [
        {"id": r["id"], "title": r["title"], "company": r["company_name"],
         "pct": r["final_pct"], "scored_at": r["scored_at"]}  # fmt: skip
        for r in rows
    ]


@router.get("/notifications")
async def notifications(db: DbDep, since: str):
    """New matches at or above the notify threshold, scored after ``since``."""
    settings = load(db)
    if not settings.notify:
        return []
    return top_matches(db, since, settings.notify_threshold)[:10]


def build_digest(db, days: int = 1) -> dict:
    since = days_ago(days)
    settings = load(db)
    board = tracker.board(db)
    expired = db.execute(
        "SELECT j.title, j.company_name, j.expired_reason FROM applications a "
        "JOIN jobs j ON j.id = a.job_id WHERE a.status IN ('saved', 'applied', 'interviewing') "
        "AND j.status != 'active' AND j.updated_at > ?",
        (since,),
    ).fetchall()
    new_jobs = db.execute(
        "SELECT COUNT(*) FROM jobs WHERE first_seen_at > ? AND duplicate_of IS NULL", (since,)
    ).fetchone()[0]
    return {
        "days": days,
        "threshold": settings.notify_threshold,
        "new_jobs": new_jobs,
        "top_matches": top_matches(db, since, settings.notify_threshold)[:20],
        "follow_ups": [
            {"id": a["id"], "job_id": a["job_id"], "title": a["title"],
             "company": a["company"], "days": a["days_since_applied"]}  # fmt: skip
            for a in board
            if a["follow_up"]
        ],
        "expired_tracked": [
            {"title": r["title"], "company": r["company_name"], "reason": r["expired_reason"]}
            for r in expired
        ],
    }


@router.get("/digest")
async def digest(db: DbDep, days: int = 1):
    return build_digest(db, max(1, min(days, 30)))


@router.get("/digest.md", response_class=PlainTextResponse)
async def digest_markdown(db: DbDep, days: int = 1):
    d = build_digest(db, max(1, min(days, 30)))
    period = "today" if d["days"] == 1 else f"the last {d['days']} days"
    lines = [f"# Job Matcher digest for {period}", "", f"{d['new_jobs']} new jobs found.", ""]
    lines.append(f"## New matches at {d['threshold']}% or more")
    matches = [f"- {m['pct']:.0f}% · {m['title']} at {m['company']}" for m in d["top_matches"]]
    lines += matches or ["- None"]
    lines += ["", "## Follow up"]
    follow = [f"- {f['company']}: {f['title']} (applied {f['days']} days ago)"
              for f in d["follow_ups"]]  # fmt: skip
    lines += follow or ["- Nothing due"]
    if d["expired_tracked"]:
        lines += ["", "## Tracked postings that closed"]
        lines += [f"- {e['company']}: {e['title']} ({e['reason']})" for e in d["expired_tracked"]]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/markdown")
