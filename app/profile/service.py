"""The parse pipeline behind the setup wizard, run as a background task."""

import hashlib
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings
from app.llm import LLMError, OllamaClient
from app.profile import extract, store
from app.profile.links import GitHubEvidence, fetch_github, fetch_portfolio
from app.profile.parse import LinkedInExport
from app.settings_store import load as load_settings
from app.tasks import TaskContext
from app.util import dumps


class ParseInputs(BaseModel):
    resume_filename: str
    resume_text: str
    github_username: str | None = None
    portfolio_url: str | None = None
    linkedin: LinkedInExport | None = None


def store_upload(filename: str, data: bytes) -> str:
    """Keep the original file next to the database; uploads are never deleted."""
    folder = Path(get_settings().db_path).parent / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()[:16]
    path = folder / f"{digest}{Path(filename).suffix.lower()}"
    if not path.exists():
        path.write_bytes(data)
    return str(path)


def steps_for(inputs: ParseInputs) -> list[str]:
    steps = ["Reading resume text"]
    if inputs.linkedin:
        steps.append("Merging LinkedIn export")
    if inputs.github_username:
        steps.append("Checking GitHub repos for evidence")
    if inputs.portfolio_url:
        steps.append("Reading portfolio page")
    steps += ["Extracting skills and roles with the local model", "Building draft profile"]
    return steps


async def run_parse(
    ctx: TaskContext, conn: sqlite3.Connection, ollama: OllamaClient, inputs: ParseInputs
) -> dict:
    i = 0
    ctx.step(i, "done", f"{len(inputs.resume_text):,} characters")
    raw: dict = {
        "resume_filename": inputs.resume_filename,
        "resume_text": inputs.resume_text,
        "portfolio_url": inputs.portfolio_url,
        "linkedin": inputs.linkedin.model_dump() if inputs.linkedin else None,
    }
    if inputs.linkedin:
        i += 1
        ctx.step(
            i,
            "done",
            f"{len(inputs.linkedin.positions)} positions, {len(inputs.linkedin.skills)} skills",
        )
    github: GitHubEvidence | None = None
    if inputs.github_username:
        i += 1
        ctx.step(i)
        try:
            github = await fetch_github(inputs.github_username)
            raw["github"] = github.model_dump()
            ctx.step(i, "done", f"{github.public_repos} repos, {len(github.languages)} languages")
        except Exception as e:  # evidence is optional; say why and carry on
            ctx.step(i, "error", str(e) or type(e).__name__)
    portfolio: str | None = None
    if inputs.portfolio_url:
        i += 1
        ctx.step(i)
        try:
            portfolio = await fetch_portfolio(inputs.portfolio_url)
            raw["portfolio_text"] = portfolio
            ctx.step(i, "done" if portfolio else "error", None if portfolio else "No text found")
        except Exception as e:
            ctx.step(i, "error", str(e) or type(e).__name__)

    i += 1
    extracted, llm_error = await _extract(ctx, i, ollama, conn, raw)
    raw["llm_error"] = llm_error
    i += 1
    ctx.step(i)
    profile = extract.merge(extracted, inputs.resume_text, inputs.linkedin, github, portfolio)
    version_id = store.create_draft(conn, raw, profile)
    ctx.step(i, "done", f"{len(profile.skills)} skills")
    return {"profile_version_id": version_id, "llm_error": llm_error}


async def _extract(ctx: TaskContext, i: int, ollama: OllamaClient, conn, raw: dict):
    model = load_settings(conn).model_name()
    ctx.step(i, "running", f"Running on {model} locally. Nothing leaves this computer.")
    linkedin = LinkedInExport.model_validate(raw["linkedin"]) if raw.get("linkedin") else None
    github = GitHubEvidence.model_validate(raw["github"]) if raw.get("github") else None
    prompt = extract.build_prompt(raw["resume_text"], linkedin, github, raw.get("portfolio_text"))
    try:
        extracted = await extract.extract_with_llm(ollama, prompt, model=model)
    except LLMError as e:
        ctx.step(i, "error", str(e)[:300])
        return None, str(e)[:500]
    ctx.step(i, "done", f"{len(extracted.skills)} skills found")
    return extracted, None


async def run_reparse(
    ctx: TaskContext, conn: sqlite3.Connection, ollama: OllamaClient, version_id: int
) -> dict:
    """Retry the LLM step for a draft whose extraction failed, using its stored inputs."""
    version = store.get(conn, version_id, with_raw=True)
    raw = version["raw_inputs"]
    extracted, llm_error = await _extract(ctx, 0, ollama, conn, raw)
    ctx.step(1)
    linkedin = LinkedInExport.model_validate(raw["linkedin"]) if raw.get("linkedin") else None
    github = GitHubEvidence.model_validate(raw["github"]) if raw.get("github") else None
    profile = extract.merge(
        extracted, raw["resume_text"], linkedin, github, raw.get("portfolio_text")
    )
    raw["llm_error"] = llm_error
    with conn:
        conn.execute(
            "UPDATE profile_versions SET profile_json = ?, raw_inputs = ? WHERE id = ?",
            (profile.model_dump_json(), dumps(raw), version_id),
        )
    ctx.step(1, "done", f"{len(profile.skills)} skills")
    return {"profile_version_id": version_id, "llm_error": llm_error}
