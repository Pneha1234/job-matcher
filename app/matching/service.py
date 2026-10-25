"""Embedding, Stage A shortlist, Stage B scoring and the background re-score task."""

import logging
import sqlite3

import sqlite_vec

from app.llm import LLMError, OllamaClient
from app.matching import eligibility
from app.matching.score import (
    SYSTEM,
    JobAssessment,
    build_prompt,
    final_pct,
    sub_scores,
)
from app.normalize.dedup import merge_near_duplicates
from app.profile import store
from app.profile.schema import ProfileData
from app.settings_store import AppSettings, Weights
from app.settings_store import load as load_settings
from app.tasks import TaskContext, TaskRunner
from app.util import dumps, loads, now_iso

log = logging.getLogger(__name__)
EMBED_BATCH = 32
KNN_MAX = 4096  # sqlite-vec's cap on k


def job_text(row: sqlite3.Row) -> str:
    return f"{row['title']} at {row['company_name']}.\n{(row['description'] or '')[:1500]}"


async def embed_missing(
    conn: sqlite3.Connection, ollama: OllamaClient, ctx: TaskContext | None = None, step=0
) -> list[int]:
    """Embed active jobs that have no vector yet; returns their ids."""
    rows = conn.execute(
        "SELECT id, title, company_name, description FROM jobs WHERE status = 'active' "
        "AND duplicate_of IS NULL AND id NOT IN (SELECT job_id FROM job_embeddings) "
        "ORDER BY id DESC"
    ).fetchall()
    done = 0
    for i in range(0, len(rows), EMBED_BATCH):
        batch = rows[i : i + EMBED_BATCH]
        vectors = await ollama.embed([job_text(r) for r in batch])
        with conn:
            for row, vec in zip(batch, vectors, strict=True):
                conn.execute(
                    "INSERT INTO job_embeddings (job_id, embedding) VALUES (?, ?)",
                    (row["id"], sqlite_vec.serialize_float32(vec)),
                )
        done += len(batch)
        if ctx:
            ctx.step(step, "running", f"{done:,} / {len(rows):,}")
    return [r["id"] for r in rows]


async def profile_vector(
    conn: sqlite3.Connection, ollama: OllamaClient, version_id: int, profile: ProfileData
) -> bytes:
    row = conn.execute(
        "SELECT embedding FROM profile_embeddings WHERE profile_version_id = ?", (version_id,)
    ).fetchone()
    if row:
        return row["embedding"]
    vec = sqlite_vec.serialize_float32((await ollama.embed([profile.as_text()]))[0])
    with conn:
        conn.execute(
            "INSERT INTO profile_embeddings (profile_version_id, embedding) VALUES (?, ?)",
            (version_id, vec),
        )
    return vec


def job_countries(conn: sqlite3.Connection, job_ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for i in range(0, len(job_ids), 900):
        chunk = job_ids[i : i + 900]
        rows = conn.execute(
            f"SELECT job_id, country_code FROM job_locations WHERE job_id IN "
            f"({','.join('?' * len(chunk))})",
            chunk,
        )
        for r in rows:
            out.setdefault(r["job_id"], []).append(r["country_code"])
    return out


def shortlist(
    conn: sqlite3.Connection, settings: AppSettings, profile_vec: bytes, n: int
) -> list[tuple[int, float]]:
    """Hard filters, then cosine similarity: the jobs worth an LLM call."""
    knn = conn.execute(
        "SELECT job_id, distance FROM job_embeddings WHERE embedding MATCH ? AND k = ? "
        "ORDER BY distance",
        (profile_vec, KNN_MAX),
    ).fetchall()
    sims = {r["job_id"]: 1 - r["distance"] for r in knn}
    if not sims:
        return []
    ids = list(sims)
    rows = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i : i + 900]
        for r in conn.execute(
            f"SELECT j.*, COALESCE(f.hidden, 0) AS hidden FROM jobs j "
            f"LEFT JOIN user_job_flags f ON f.job_id = j.id WHERE j.id IN "
            f"({','.join('?' * len(chunk))})",
            chunk,
        ):
            rows[r["id"]] = r
    countries = job_countries(conn, ids)
    picked = []
    for job_id in ids:
        job = rows.get(job_id)
        if not job or job["status"] != "active" or job["hidden"] or job["duplicate_of"]:
            continue
        if settings.job_types and job["job_type"] and job["job_type"] not in settings.job_types:
            continue
        if (
            settings.min_salary
            and job["salary_annual_max"] is not None
            and job["salary_annual_max"] < settings.min_salary
        ):
            continue
        status, _ = eligibility.location_status(job, countries.get(job_id, []), settings)
        if status == "not_eligible":
            continue
        picked.append((job_id, sims[job_id]))
        if len(picked) >= n:
            break
    return picked


def location_facts(settings: AppSettings, profile: ProfileData) -> list[str]:
    facts = []
    if settings.home_country:
        facts.append(f"Lives in {settings.home_country}" + (
            f" ({settings.home_city})" if settings.home_city else ""))  # fmt: skip
    if settings.target_countries:
        facts.append(f"Wants work in: {', '.join(settings.target_countries)}")
    facts.append("Open to relocation" if settings.open_to_relocation else "Not relocating")
    if settings.needs_visa:
        facts.append("Needs visa sponsorship outside their home country")
    langs = ", ".join(f"{x.language} ({x.level})" for x in profile.languages)
    facts.append(f"Speaks: {langs or 'not stated'}")
    return facts


async def score_job(
    conn: sqlite3.Connection,
    ollama: OllamaClient,
    settings: AppSettings,
    version_id: int,
    profile: ProfileData,
    job_id: int,
    similarity: float | None = None,
) -> dict:
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    locs = conn.execute(
        "SELECT raw, country_code FROM job_locations WHERE job_id = ?", (job_id,)
    ).fetchall()
    location, location_reason = eligibility.location_status(
        job, [r["country_code"] for r in locs], settings
    )
    gaps = eligibility.language_gaps(job, profile)
    model = settings.scoring_model_name()
    prompt = build_prompt(
        profile.as_text(), location_facts(settings, profile), dict(job), [r["raw"] for r in locs]
    )
    row: dict = {"status": "unscored", "model": model, "similarity": similarity}
    a: JobAssessment | None = None
    if len((job["description"] or "").strip()) < 80:
        row["error"] = "The source gave no description to compare. Open the posting to judge it."
    else:
        try:
            a = await ollama.generate_json(prompt, JobAssessment, system=SYSTEM, model=model)
        except LLMError as e:
            row["error"] = str(e)[:500]
    if a is not None:
        subs = sub_scores(a, location, gaps)
        pct = final_pct(subs, settings.weights)
        missing = [c.skill for c in a.required_skills if c.status == "missing"] + [
            f"{g} (spoken)" for g in gaps
        ]
        row.update(
            sub_scores=dumps(
                {
                    **subs,
                    "assessment": a.model_dump(),
                    "location_status": location,
                    "location_reason": location_reason,
                }
            ),
            matched_skills=dumps(
                [c.skill for c in a.required_skills + a.nice_to_have_skills
                 if c.status == "matched"]  # fmt: skip
            ),
            missing_skills=dumps(missing),
            explanation=a.explanation,
        )
        if pct is None:
            row["error"] = "The model found no required skills in this posting to compare."
        else:
            row["status"], row["final_pct"] = "scored", pct
    with conn:
        conn.execute(
            "INSERT INTO match_scores (job_id, profile_version_id, status, sub_scores, final_pct, "
            "matched_skills, missing_skills, explanation, error, model, scored_at, similarity) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (job_id, profile_version_id) DO UPDATE SET status = excluded.status, "
            "sub_scores = excluded.sub_scores, final_pct = excluded.final_pct, "
            "matched_skills = excluded.matched_skills, missing_skills = excluded.missing_skills, "
            "explanation = excluded.explanation, error = excluded.error, model = excluded.model, "
            "scored_at = excluded.scored_at, "
            "similarity = COALESCE(excluded.similarity, similarity)",
            (
                job_id,
                version_id,
                row["status"],
                row.get("sub_scores"),
                row.get("final_pct"),
                row.get("matched_skills"),
                row.get("missing_skills"),
                row.get("explanation"),
                row.get("error"),
                model,
                now_iso(),
                similarity,
            ),
        )
    return row


SCORE_STEPS = [
    "Embedding new jobs",
    "Shortlisting with your filters",
    "Scoring with the local model",
]


async def run_scoring(
    ctx: TaskContext, conn: sqlite3.Connection, ollama: OllamaClient, limit: int | None = None
) -> dict:
    active = store.active_profile(conn)
    if not active:
        raise RuntimeError("Save a profile first")
    version_id, profile = active
    ctx.step(0)
    embedded = await embed_missing(conn, ollama, ctx, 0)
    merged = merge_near_duplicates(conn, embedded)
    ctx.step(0, "done", f"{len(embedded):,} new, {merged} near-duplicates merged")
    ctx.step(1)
    # Read after embedding, which can take minutes: preferences saved meanwhile apply.
    settings = load_settings(conn)
    vec = await profile_vector(conn, ollama, version_id, profile)
    picks = shortlist(conn, settings, vec, limit or settings.shortlist_size)
    scored_ids = {
        r[0]
        for r in conn.execute(
            "SELECT job_id FROM match_scores WHERE profile_version_id = ?", (version_id,)
        )
    }
    todo = [(j, s) for j, s in picks if j not in scored_ids]
    ctx.step(1, "done", f"{len(picks)} jobs, {len(todo)} not scored yet")
    ctx.step(2, "running", f"0 / {len(todo)}")
    scored = failed = 0
    for i, (job_id, sim) in enumerate(todo, start=1):
        row = await score_job(conn, ollama, settings, version_id, profile, job_id, sim)
        if row["status"] == "scored":
            scored += 1
        else:
            failed += 1
        ctx.step(2, "running", f"{i} / {len(todo)}")
    ctx.step(2, "done", f"{scored} scored, {failed} unscored")
    return {"profile_version_id": version_id, "scored": scored, "unscored": failed}


def start_rescore(conn: sqlite3.Connection, ollama: OllamaClient, tasks: TaskRunner) -> int | None:
    """Score whatever the active profile hasn't scored yet; reuses a running task."""
    if not store.active_profile(conn):
        return None
    running = tasks.is_running("score")
    if running:
        return running
    return tasks.start("score", SCORE_STEPS, lambda ctx: run_scoring(ctx, conn, ollama))


def reweight(conn: sqlite3.Connection, weights: Weights) -> int:
    """Settings changed the weights: recompute every stored % from its sub-scores."""
    rows = conn.execute(
        "SELECT id, sub_scores FROM match_scores WHERE status = 'scored'"
    ).fetchall()
    with conn:
        for r in rows:
            pct = final_pct(loads(r["sub_scores"], {}), weights)
            if pct is not None:
                conn.execute("UPDATE match_scores SET final_pct = ? WHERE id = ?", (pct, r["id"]))
    return len(rows)
