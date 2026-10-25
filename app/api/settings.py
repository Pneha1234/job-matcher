"""Settings: weights (with a live re-rank preview), saved searches, locations, schedules."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbDep, OllamaDep, TasksDep
from app.llm import LLMError
from app.matching.score import final_pct
from app.matching.service import reweight
from app.normalize import fx, geo
from app.normalize.regions import CITY_GROUPS, REGIONS
from app.profile import store
from app.settings_store import AppSettings, Weights, get_value, load, save, set_value
from app.sources.registry import SOURCES
from app.sources.runner import api_keys
from app.util import dumps, loads

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def get_settings_(db: DbDep, ollama: OllamaDep):
    try:
        models = await ollama.list_models()
    except LLMError:
        models = []
    g = geo.load_geo()
    fx_meta = get_value(db, fx.KEY)
    return {
        "settings": load(db).model_dump(),
        "meta": {
            "models": models,
            "geonames": geo.is_downloaded(),
            "countries": sorted(
                # GeoNames says "The Netherlands"; list it under N.
                (
                    {"code": c, "name": n.removeprefix("The ")}
                    for c, n in (g.countries.items() if g else [])
                ),
                key=lambda x: x["name"],
            ),
            "regions": sorted(REGIONS),
            "city_groups": sorted(CITY_GROUPS),
            "fx_date": (fx_meta or {}).get("date"),
        },
    }


@router.put("/settings")
async def put_settings(db: DbDep, body: AppSettings):
    before = load(db)
    save(db, body)
    reweighted = 0
    if body.weights != before.weights:
        reweighted = reweight(db, body.weights)
    rates_changed = body.currency != before.currency
    if rates_changed:
        _reconvert_salaries(db, body.currency)
    return {"settings": body.model_dump(), "reweighted": reweighted}


def _reconvert_salaries(db, currency: str) -> None:
    from app.normalize.salary import Salary

    table = fx.rates(db)
    rows = db.execute(
        "SELECT id, salary_min, salary_max, salary_currency, salary_period FROM jobs "
        "WHERE salary_currency IS NOT NULL AND salary_period IS NOT NULL"
    ).fetchall()
    with db:
        for r in rows:
            lo, hi = Salary(r[1], r[2], r[3], r[4]).annual()
            a = fx.convert(lo, r[3], currency, table)
            b = fx.convert(hi, r[3], currency, table)
            db.execute(
                "UPDATE jobs SET salary_annual_min = ?, salary_annual_max = ? WHERE id = ?",
                (round(a) if a else None, round(b) if b else None, r[0]),
            )


class PreviewIn(BaseModel):
    weights: Weights
    limit: int = Field(5, ge=1, le=20)


@router.post("/settings/preview")
async def preview(db: DbDep, body: PreviewIn):
    """Top jobs under weights the user is still dragging; nothing is saved."""
    active = store.active(db)
    if not active:
        return []
    rows = db.execute(
        "SELECT ms.sub_scores, j.id, j.title, j.company_name FROM match_scores ms "
        "JOIN jobs j ON j.id = ms.job_id LEFT JOIN user_job_flags f ON f.job_id = j.id "
        "WHERE ms.profile_version_id = ? AND ms.status = 'scored' AND j.status = 'active' "
        "AND COALESCE(f.hidden, 0) = 0",
        (active["id"],),
    ).fetchall()
    ranked = []
    for r in rows:
        pct = final_pct(loads(r["sub_scores"], {}), body.weights)
        if pct is not None:
            ranked.append({"id": r["id"], "title": r["title"], "company": r["company_name"],
                           "pct": pct})  # fmt: skip
    ranked.sort(key=lambda x: x["pct"], reverse=True)
    return ranked[: body.limit]


class SearchIn(BaseModel):
    text: str = Field(min_length=1, max_length=160)


def _search_row(r) -> dict:
    f = loads(r["filters"], {})
    return {"id": r["id"], "query": f.get("query"), "location": f.get("location"),
            "label": f.get("label"), "archived": bool(r["is_archived"])}  # fmt: skip


@router.get("/searches")
async def searches(db: DbDep):
    rows = db.execute(
        "SELECT * FROM saved_searches WHERE is_archived = 0 ORDER BY position, id"
    ).fetchall()
    return [_search_row(r) for r in rows]


@router.post("/searches")
async def add_search(db: DbDep, body: SearchIn):
    """'Django developer · Utrecht' -> query + location (split on · or ' in ')."""
    text = body.text.strip()
    query, _, location = text.partition("·")
    if not location and " in " in text:
        query, _, location = text.rpartition(" in ")
    query, location = query.strip(), location.strip() or None
    if not query:
        raise HTTPException(422, {"fields": {"text": "Enter what to search for first."}})
    for r in db.execute("SELECT * FROM saved_searches"):
        f = loads(r["filters"], {})
        if (f.get("query") or "").lower() == query.lower() and (
            (f.get("location") or "").lower() == (location or "").lower()
        ):
            if r["is_archived"]:
                with db:
                    db.execute("UPDATE saved_searches SET is_archived = 0 WHERE id = ?", (r["id"],))
                return _search_row(db.execute("SELECT * FROM saved_searches WHERE id = ?",
                                              (r["id"],)).fetchone())  # fmt: skip
            raise HTTPException(422, {"fields": {"text": "You already have that search."}})
    position = db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM saved_searches").fetchone()[0]
    with db:
        new_id = db.execute(
            "INSERT INTO saved_searches (name, filters, position) VALUES (?, ?, ?)",
            (text, dumps({"query": query, "location": location, "label": text}), position),
        ).lastrowid
    return _search_row(
        db.execute("SELECT * FROM saved_searches WHERE id = ?", (new_id,)).fetchone()
    )


@router.post("/searches/{search_id}/archive")
async def archive_search(db: DbDep, search_id: int):
    with db:
        db.execute("UPDATE saved_searches SET is_archived = 1 WHERE id = ?", (search_id,))
    return {"id": search_id, "archived": True}


@router.post("/searches/{search_id}/restore")
async def restore_search(db: DbDep, search_id: int):
    with db:
        db.execute("UPDATE saved_searches SET is_archived = 0 WHERE id = ?", (search_id,))
    return {"id": search_id, "archived": False}


@router.post("/settings/geonames")
async def download_geonames(tasks: TasksDep):
    async def run(ctx):
        ctx.step(0)
        await geo.download()
        ctx.step(0, "done")
        return {"ok": True}

    return {"task_id": tasks.start("geonames", ["Downloading GeoNames (about 3 MB)"], run)}


@router.post("/settings/fx")
async def refresh_fx(db: DbDep):
    rates = await fx.refresh(db)
    _reconvert_salaries(db, load(db).currency)
    return {"currencies": len(rates)}


class KeyIn(BaseModel):
    source: str = Field(min_length=1, max_length=40)
    value: str = Field("", max_length=400)


@router.put("/settings/keys")
async def set_key(db: DbDep, body: KeyIn):
    """Free sign-up keys live only in the local database. An empty value removes a key."""
    source = SOURCES.get(body.source)
    if not source or not source.key_help:
        raise HTTPException(404, "That source doesn't take a key")
    keys = api_keys(db)
    if body.value.strip():
        keys[body.source] = body.value.strip()
    else:
        keys.pop(body.source, None)
    set_value(db, "api_keys", keys)
    return {"source": body.source, "has_key": body.source in keys}
