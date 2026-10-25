"""Profile wizard: upload and parse, review drafts, save versions."""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import DbDep, OllamaDep, TasksDep
from app.matching.service import start_rescore
from app.profile import store
from app.profile.links import github_username, normalise_url
from app.profile.parse import InputError, linkedin_export, resume_text
from app.profile.schema import ProfileData
from app.profile.service import ParseInputs, run_parse, run_reparse, steps_for, store_upload

router = APIRouter(prefix="/profile", tags=["profile"])


def _bad(errors: dict[str, str]) -> HTTPException:
    return HTTPException(status_code=422, detail={"fields": errors})


@router.post("/parse")
async def parse(
    db: DbDep,
    ollama: OllamaDep,
    tasks: TasksDep,
    resume: Annotated[UploadFile | None, File()] = None,
    github: Annotated[str, Form()] = "",
    portfolio: Annotated[str, Form()] = "",
    linkedin: Annotated[UploadFile | None, File()] = None,
):
    errors: dict[str, str] = {}
    text = gh = pf = li = None
    if resume is None or not resume.filename:
        errors["resume"] = "Add your resume first."
    else:
        data = await resume.read()
        try:
            text = resume_text(resume.filename, data)
            store_upload(resume.filename, data)
        except InputError as e:
            errors["resume"] = str(e)
    if github.strip():
        try:
            gh = github_username(github)
        except InputError as e:
            errors["github"] = str(e)
    if portfolio.strip():
        try:
            pf = normalise_url(portfolio)
        except InputError as e:
            errors["portfolio"] = str(e)
    if linkedin is not None and linkedin.filename:
        try:
            li = linkedin_export(await linkedin.read())
        except InputError as e:
            errors["linkedin"] = str(e)
    if errors:
        raise _bad(errors)

    inputs = ParseInputs(
        resume_filename=resume.filename,
        resume_text=text,
        github_username=gh,
        portfolio_url=pf,
        linkedin=li,
    )
    task_id = tasks.start(
        "profile_parse", steps_for(inputs), lambda ctx: run_parse(ctx, db, ollama, inputs)
    )
    return {"task_id": task_id}


@router.get("/versions")
async def versions(db: DbDep):
    return store.list_versions(db)


@router.get("/active")
async def active(db: DbDep):
    return store.active(db)


@router.get("/versions/{version_id}")
async def version(db: DbDep, version_id: int):
    try:
        current = store.get(db, version_id)
    except store.ProfileError as e:
        raise HTTPException(404, str(e)) from e
    current["diff"] = store.diff(store.previous_saved(db, version_id), current)
    return current


@router.put("/versions/{version_id}")
async def update(db: DbDep, version_id: int, profile: ProfileData):
    try:
        updated = store.update_draft(db, version_id, profile)
    except store.ProfileError as e:
        raise HTTPException(409, str(e)) from e
    updated["diff"] = store.diff(store.previous_saved(db, version_id), updated)
    return updated


@router.post("/versions/{version_id}/reparse")
async def reparse(db: DbDep, ollama: OllamaDep, tasks: TasksDep, version_id: int):
    try:
        if store.get(db, version_id)["status"] != "draft":
            raise HTTPException(409, "Only a draft can be re-read.")
    except store.ProfileError as e:
        raise HTTPException(404, str(e)) from e
    steps = ["Extracting skills and roles with the local model", "Building draft profile"]
    task_id = tasks.start(
        "profile_parse", steps, lambda ctx: run_reparse(ctx, db, ollama, version_id)
    )
    return {"task_id": task_id}


@router.post("/versions/{version_id}/save")
async def save(db: DbDep, ollama: OllamaDep, tasks: TasksDep, version_id: int):
    try:
        saved = store.save_draft(db, version_id)
    except store.ProfileError as e:
        raise HTTPException(409, str(e)) from e
    saved["rescore_task_id"] = start_rescore(db, ollama, tasks)
    return saved


@router.post("/versions/{version_id}/activate")
async def activate(db: DbDep, ollama: OllamaDep, tasks: TasksDep, version_id: int):
    try:
        current = store.activate(db, version_id)
    except store.ProfileError as e:
        raise HTTPException(409, str(e)) from e
    current["rescore_task_id"] = start_rescore(db, ollama, tasks)
    return current
