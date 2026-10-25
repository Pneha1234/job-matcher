"""Shared builders for API tests."""

from app.normalize.ingest import Normaliser, upsert
from app.profile import store
from app.profile.schema import ProfileData
from app.settings_store import load
from app.sources.base import RawJob
from tests.fakes import PROFILE


def add_job(db, n: int, **kw) -> int:
    base = dict(
        source="greenhouse",
        source_job_id=str(n),
        url=f"https://example.com/{n}",
        title=f"Python Developer {n}",
        company=f"Company {n}",
        description=(
            "We build backend services in Python with Django and PostgreSQL. You will design "
            "APIs, own features end to end and run them in production."
        ),
        locations=["Amsterdam"],
    )
    base.update(kw)
    raw = RawJob(**base)
    with db:
        job_id, _ = upsert(db, raw, Normaliser(db, load(db)).normalise(raw))
    return job_id


def save_profile(db) -> int:
    vid = store.create_draft(db, {}, ProfileData.model_validate(PROFILE))
    store.save_draft(db, vid)
    return vid
