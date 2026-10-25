"""Jobs: ranked list with filters, detail drawer, actions, manual import, cover letters."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import DbDep, OllamaDep, TasksDep
from app.jobs_query import JobFilters, job_map, list_jobs
from app.llm import LLMError
from app.matching.service import score_job, start_rescore
from app.normalize.geo import load_geo
from app.profile import store
from app.settings_store import load as load_settings
from app.sources.manual import ImportError_, import_job
from app.tracker import service as tracker
from app.util import loads

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
async def jobs(db: DbDep, flt: Annotated[JobFilters, Query()]):
    active = store.active(db)
    return list_jobs(db, flt, load_settings(db), active["id"] if active else None)


@router.get("/jobs/map")
async def jobs_map(db: DbDep, flt: Annotated[JobFilters, Query()]):
    active = store.active(db)
    return job_map(db, flt, load_settings(db), active["id"] if active else None)


@router.get("/geo/cities")
async def geo_cities(q: str):
    geo = load_geo()
    if geo is None:
        return []
    return [
        {"name": c.name, "region": geo.admin1.get(f"{c.country}.{c.admin1}"),
         "country": c.country, "lat": c.lat, "lon": c.lon}  # fmt: skip
        for c in geo.search(q)
    ]


@router.get("/jobs/new-count")
async def new_count(db: DbDep, since: str):
    n = db.execute(
        "SELECT COUNT(*) FROM jobs WHERE status = 'active' AND duplicate_of IS NULL "
        "AND first_seen_at > ?",
        (since,),
    ).fetchone()[0]
    return {"count": n}


@router.get("/jobs/{job_id}")
async def job_detail(db: DbDep, job_id: int):
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    active = store.active(db)
    active_id = active["id"] if active else -1
    score = db.execute(
        "SELECT ms.*, pv.label FROM match_scores ms JOIN profile_versions pv "
        "ON pv.id = ms.profile_version_id WHERE ms.job_id = ? "
        "ORDER BY (ms.profile_version_id = ?) DESC, ms.scored_at DESC LIMIT 1",
        (job_id, active_id),
    ).fetchone()
    app = db.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    flags = db.execute("SELECT * FROM user_job_flags WHERE job_id = ?", (job_id,)).fetchone()
    out = dict(job)
    for key in ("remote_eligibility", "language_reqs", "extra"):
        out[key] = loads(out[key], None)
    out["locations"] = [
        dict(r)
        for r in db.execute(
            "SELECT raw, city, region, country_code, lat, lon, resolved FROM job_locations "
            "WHERE job_id = ?",
            (job_id,),
        )
    ]
    out["sources"] = [
        dict(r)
        for r in db.execute(
            "SELECT source, url, status, first_seen_at, last_seen_at FROM job_sources "
            "WHERE job_id = ? ORDER BY first_seen_at",
            (job_id,),
        )
    ]
    out["match"] = None
    if score:
        subs = loads(score["sub_scores"], {}) or {}
        out["match"] = {
            "status": score["status"],
            "pct": score["final_pct"],
            "sub_scores": {k: subs.get(k) for k in ("required", "nice", "seniority", "domain",
                                                     "location")},  # fmt: skip
            "assessment": subs.get("assessment"),
            "location_reason": subs.get("location_reason"),
            "matched": loads(score["matched_skills"], []) or [],
            "missing": loads(score["missing_skills"], []) or [],
            "explanation": score["explanation"],
            "error": score["error"],
            "model": score["model"],
            "scored_at": score["scored_at"],
            "version_label": score["label"],
            "stale_version": score["profile_version_id"] != active_id,
        }
    out["application"] = dict(app) if app and app["status"] != "archived" else None
    out["hidden"] = bool(flags["hidden"]) if flags else False
    return out


class ApplicationIn(BaseModel):
    status: Literal["saved", "applied", "interviewing", "offer", "rejected", "withdrawn",
                    "archived"]  # fmt: skip
    note: str | None = Field(None, max_length=1000)


@router.put("/jobs/{job_id}/application")
async def set_application(db: DbDep, job_id: int, body: ApplicationIn):
    try:
        return tracker.set_status(db, job_id, body.status, body.note)
    except tracker.TrackerError as e:
        raise HTTPException(404, str(e)) from e


class FlagsIn(BaseModel):
    hidden: bool
    reason: str | None = Field(None, max_length=200)


@router.put("/jobs/{job_id}/flags")
async def set_flags(db: DbDep, job_id: int, body: FlagsIn):
    try:
        return tracker.set_hidden(db, job_id, body.hidden, body.reason)
    except tracker.TrackerError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/jobs/{job_id}/score")
async def rescore_one(db: DbDep, ollama: OllamaDep, tasks: TasksDep, job_id: int):
    active = store.active_profile(db)
    if not active:
        raise HTTPException(409, "Save a profile first")
    if not db.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone():
        raise HTTPException(404, "Job not found")
    version_id, profile = active

    async def run(ctx):
        ctx.step(0)
        row = await score_job(db, ollama, load_settings(db), version_id, profile, job_id)
        ctx.step(0, "done" if row["status"] == "scored" else "error", row.get("error"))
        return {"job_id": job_id, "status": row["status"], "error": row.get("error")}

    return {"task_id": tasks.start("score_one", ["Scoring with the local model"], run)}


@router.post("/scoring/run")
async def run_scoring(db: DbDep, ollama: OllamaDep, tasks: TasksDep):
    task_id = start_rescore(db, ollama, tasks)
    if task_id is None:
        raise HTTPException(409, "Save a profile first")
    return {"task_id": task_id}


class CoverLetter(BaseModel):
    letter: str = Field(min_length=200, max_length=4000)


COVER_SYSTEM = (
    "Write a short, specific cover letter (about 180 words) from the candidate to the "
    "company, in plain first person. Use only facts from the profile; never invent "
    "employers, numbers or degrees. Mention one or two concrete overlaps with the posting "
    "and address the main gap honestly if there is one. No placeholders in brackets."
)


@router.post("/jobs/{job_id}/cover-letter")
async def cover_letter(db: DbDep, ollama: OllamaDep, tasks: TasksDep, job_id: int):
    active = store.active_profile(db)
    if not active:
        raise HTTPException(409, "Save a profile first")
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    _, profile = active

    async def run(ctx):
        ctx.step(0)
        prompt = (
            f"PROFILE:\n{profile.as_text()}\n\nJOB: {job['title']} at {job['company_name']}\n"
            f"{(job['description'] or '')[:5000]}"
        )
        try:
            out = await ollama.generate_json(
                prompt,
                CoverLetter,
                system=COVER_SYSTEM,
                model=load_settings(db).model_name(),
                temperature=0.4,
            )
        except LLMError as e:
            raise RuntimeError(f"The local model couldn't write a draft: {e}") from e
        ctx.step(0, "done")
        return {"letter": out.letter}

    return {"task_id": tasks.start("cover_letter", ["Drafting with the local model"], run)}


class ImportIn(BaseModel):
    url: str | None = Field(None, max_length=2000)
    text: str | None = Field(None, max_length=50_000)


@router.post("/jobs/import")
async def import_posting(db: DbDep, ollama: OllamaDep, tasks: TasksDep, body: ImportIn):
    url = (body.url or "").strip() or None
    if url and not url.lower().startswith(("http://", "https://")):
        url = f"https://{url}"
    if not url and not (body.text or "").strip():
        raise HTTPException(422, {"fields": {"url": "Paste a job link or the posting text."}})

    async def run(ctx):
        ctx.step(0)
        try:
            result = await import_job(db, ollama, load_settings(db), url, body.text)
        except (ImportError_, LLMError) as e:
            raise RuntimeError(str(e)) from e
        ctx.step(0, "done", f"{result['title']} at {result['company']}")
        active = store.active_profile(db)
        if active:
            ctx.add_step("Scoring with the local model", "running")
            row = await score_job(db, ollama, load_settings(db), active[0], active[1],
                                  result["job_id"])  # fmt: skip
            ctx.step(1, "done" if row["status"] == "scored" else "error", row.get("error"))
        return result

    return {"task_id": tasks.start("import", ["Reading the posting"], run)}
