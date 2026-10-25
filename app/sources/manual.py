"""Manual import: paste a job URL or the posting text; the local LLM extracts it when the
page has no schema.org JobPosting markup."""

import hashlib
import sqlite3

import httpx
from pydantic import BaseModel, Field

from app.llm import OllamaClient
from app.normalize.ingest import Normaliser, upsert
from app.settings_store import AppSettings
from app.sources.base import USER_AGENT, RawJob
from app.sources.crawl import job_postings, raw_from_posting


class ImportedJob(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    company: str = Field(min_length=1, max_length=120)
    locations: list[str] = Field(default_factory=list, max_length=10)
    remote: bool | None = None
    remote_scope: str | None = Field(None, max_length=120)
    job_type: str | None = Field(None, max_length=40)
    salary_text: str | None = Field(None, max_length=200)
    apply_before: str | None = Field(None, max_length=40)


SYSTEM = (
    "Extract the job posting's fields. Copy values as written; use null when the text does "
    "not say. remote_scope is where remote work is allowed from, if stated."
)


class ImportError_(ValueError):
    pass


async def fetch_page(url: str, transport=None) -> str:
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True, transport=transport
    ) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ImportError_(f"Could not open that page ({e.__class__.__name__}).") from e
    return r.text


async def import_job(
    conn: sqlite3.Connection,
    ollama: OllamaClient,
    settings: AppSettings,
    url: str | None,
    text: str | None,
    transport=None,
) -> dict:
    import trafilatura

    raw: RawJob | None = None
    if url:
        html = await fetch_page(url, transport)
        postings = job_postings(html)
        if postings:
            raw = raw_from_posting(postings[0], url, "manual")
            if raw:
                raw.source_job_id = url
        if raw is None:
            text = trafilatura.extract(html) or ""
            if len(text) < 100:
                raise ImportError_(
                    "That page has no readable posting text (it may need JavaScript or a login)."
                    " Paste the posting text instead."
                )
    if raw is None:
        body = (text or "").strip()
        if len(body) < 100:
            raise ImportError_("Paste the full posting text (at least a few sentences).")
        found = await ollama.generate_json(
            body[:8000], ImportedJob, system=SYSTEM, model=settings.model_name()
        )
        ident = url or "text:" + hashlib.sha256(body.encode()).hexdigest()[:16]
        raw = RawJob(
            source="manual",
            source_job_id=ident,
            url=url or ident,
            title=found.title,
            company=found.company,
            description=body,
            locations=found.locations,
            remote=found.remote,
            remote_scope=[found.remote_scope] if found.remote_scope else [],
            job_type_raw=found.job_type,
            salary_text=found.salary_text,
        )
    with conn:
        job_id, created = upsert(conn, raw, Normaliser(conn, settings).normalise(raw))
    return {"job_id": job_id, "created": created, "title": raw.title, "company": raw.company}
