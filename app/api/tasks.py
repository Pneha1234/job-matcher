"""Background task status for the UI's progress displays, plus the sidebar summary."""

from fastapi import APIRouter, HTTPException

from app.api.deps import DbDep, TasksDep
from app.profile import store
from app.tasks import get_task

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}")
async def task(db: DbDep, task_id: int):
    found = get_task(db, task_id)
    if not found:
        raise HTTPException(404, "Task not found")
    return found


@router.get("/tasks")
async def tasks(db: DbDep, runner: TasksDep, kind: str | None = None):
    sql = "SELECT id FROM tasks WHERE status = 'running'"
    args: tuple = ()
    if kind:
        sql += " AND kind = ?"
        args = (kind,)
    return [get_task(db, r["id"]) for r in db.execute(sql + " ORDER BY id DESC", args)]


@router.get("/summary")
async def summary(db: DbDep, runner: TasksDep):
    active = store.active(db)
    last = db.execute(
        "SELECT finished_at FROM scrape_runs WHERE finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    jobs = db.execute(
        "SELECT COUNT(*) FROM jobs j LEFT JOIN user_job_flags f ON f.job_id = j.id "
        "WHERE j.status = 'active' AND j.duplicate_of IS NULL AND COALESCE(f.hidden, 0) = 0"
    ).fetchone()[0]
    apps = db.execute(
        "SELECT COUNT(*) FROM applications WHERE status IN ('applied', 'interviewing', 'offer')"
    ).fetchone()[0]
    # The latest run per source that failed or found nothing.
    attention = db.execute(
        "SELECT COUNT(*) FROM scrape_runs r WHERE r.id = (SELECT MAX(id) FROM scrape_runs x "
        "WHERE x.source = r.source AND x.status != 'running') AND (r.status = 'error' OR "
        "(r.status = 'ok' AND r.found = 0))"
    ).fetchone()[0]
    scoring = runner.is_running("score")
    return {
        "profile": {"id": active["id"], "label": active["label"]} if active else None,
        "jobs_active": jobs,
        "applications_open": apps,
        "sources_attention": attention,
        "last_scrape_at": last["finished_at"] if last else None,
        "scoring_task_id": scoring,
    }
