"""Sources page: health, run now / run all, pause / resume, company crawl list."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbDep, OllamaDep, TasksDep
from app.config import get_settings
from app.matching.service import start_rescore
from app.sources import registry
from app.sources.base import PoliteClient
from app.sources.discover import discover
from app.sources.health import source_rows
from app.sources.runner import board_from_url, run_source, set_paused
from app.tasks import TaskRunner

router = APIRouter(tags=["sources"])


def running_sources(db, tasks: TaskRunner) -> dict[str, int]:
    out = {}
    for name in registry.SOURCES:
        task_id = tasks.is_running(f"source:{name}")
        if task_id:
            out[name] = task_id
    if all_id := tasks.is_running("sources:all"):
        out.setdefault("*", all_id)
    return out


@router.get("/sources")
async def sources(db: DbDep, tasks: TasksDep):
    running = running_sources(db, tasks)
    rows = source_rows(db, running)
    return {"sources": rows, "run_all_task_id": running.get("*")}


def start_source_task(db, ollama, tasks: TaskRunner, name: str) -> int:
    running = tasks.is_running(f"source:{name}")
    if running:
        return running

    async def run(ctx):
        ctx.step(0)
        result = await run_source(db, name)
        ctx.step(0, "done" if result["status"] == "ok" else "error",
                 f"{result.get('found', 0)} found, {result.get('new', 0)} new")  # fmt: skip
        if result.get("new"):
            start_rescore(db, ollama, tasks)
        return result

    return tasks.start(f"source:{name}", [f"Running {registry.get(name).label}"], run)


@router.post("/sources/{name}/run")
async def run_now(db: DbDep, ollama: OllamaDep, tasks: TasksDep, name: str):
    if name not in registry.SOURCES:
        raise HTTPException(404, "Unknown source")
    return {"task_id": start_source_task(db, ollama, tasks, name)}


async def run_all_sources(ctx, db, ollama, tasks: TaskRunner, names: list[str]) -> dict:
    totals = {"found": 0, "new": 0}
    for i, name in enumerate(names):
        ctx.step(i)
        result = await run_source(db, name)
        totals["found"] += result.get("found", 0)
        totals["new"] += result.get("new", 0)
        state = "done" if result["status"] == "ok" else "error"
        detail = result.get("reason") or f"{result.get('found', 0)} found"
        ctx.step(i, state, detail)
    if totals["new"]:
        start_rescore(db, ollama, tasks)
    return totals


@router.post("/sources/run-all")
async def run_all(db: DbDep, ollama: OllamaDep, tasks: TasksDep):
    running = tasks.is_running("sources:all")
    if running:
        return {"task_id": running}
    names = list(registry.SOURCES)
    labels = [f"{registry.get(n).label}" for n in names]
    task_id = tasks.start(
        "sources:all", labels, lambda ctx: run_all_sources(ctx, db, ollama, tasks, names)
    )
    return {"task_id": task_id}


@router.post("/sources/{name}/pause")
async def pause(db: DbDep, name: str):
    if name not in registry.SOURCES:
        raise HTTPException(404, "Unknown source")
    set_paused(db, name, "Paused by you", None)
    return {"name": name, "paused": True}


@router.post("/sources/{name}/resume")
async def resume(db: DbDep, name: str):
    if name not in registry.SOURCES:
        raise HTTPException(404, "Unknown source")
    set_paused(db, name, None, None)
    return {"name": name, "paused": False}


@router.get("/companies")
async def companies(db: DbDep, platform: str | None = None):
    sql = "SELECT * FROM companies"
    args: tuple = ()
    if platform:
        sql += " WHERE platform = ?"
        args = (platform,)
    rows = db.execute(sql + " ORDER BY status, name COLLATE NOCASE", args).fetchall()
    return [dict(r) for r in rows]


class CompanyIn(BaseModel):
    url: str = Field(min_length=4, max_length=500)
    name: str | None = Field(None, max_length=120)


@router.post("/companies")
async def add_company(db: DbDep, body: CompanyIn):
    url = body.url.strip()
    found = board_from_url(url)
    if found:
        platform, slug = found
        careers = None
    elif url.lower().startswith(("http://", "https://")) or "." in url:
        platform, slug = "jsonld", None
        careers = url if url.lower().startswith("http") else f"https://{url}"
    else:
        raise HTTPException(422, {"fields": {"url": "Paste a careers page or job board link."}})
    name = (body.name or "").strip() or (slug or careers or "").split("|")[0].replace("-", " ")
    with db:
        existing = db.execute(
            "SELECT id FROM companies WHERE platform = ? AND (slug = ? OR careers_url = ?)",
            (platform, slug, careers),
        ).fetchone()
        if existing:
            db.execute("UPDATE companies SET status = 'active' WHERE id = ?", (existing["id"],))
            company_id = existing["id"]
        else:
            company_id = db.execute(
                "INSERT INTO companies (name, platform, slug, careers_url) VALUES (?, ?, ?, ?)",
                (name.title() if name.islower() else name, platform, slug or careers, careers),
            ).lastrowid
    return dict(db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone())


class CompanyPatch(BaseModel):
    status: str = Field(pattern="^(active|paused)$")


@router.patch("/companies/{company_id}")
async def patch_company(db: DbDep, company_id: int, body: CompanyPatch):
    with db:
        cur = db.execute("UPDATE companies SET status = ? WHERE id = ?", (body.status, company_id))
    if not cur.rowcount:
        raise HTTPException(404, "Company not found")
    return dict(db.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone())


@router.post("/companies/discover")
async def discover_companies(db: DbDep, tasks: TasksDep):
    async def run(ctx):
        ctx.step(0)
        cfg = get_settings()
        http = PoliteClient(
            "commoncrawl", db, budget=20, delay=(cfg.scrape_delay_min, cfg.scrape_delay_max)
        )
        try:
            added = await discover(db, http)
        finally:
            await http.aclose()
        ctx.step(0, "done", ", ".join(f"{k}: +{v}" for k, v in added.items()))
        return added

    return {"task_id": tasks.start("discover", ["Searching the Common Crawl index"], run)}
