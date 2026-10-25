import asyncio

from app.db import init_db
from app.normalize.dedup import merge_near_duplicates, same_role
from app.settings_store import AppSettings
from tests.fakes import FakeOllama
from tests.helpers import add_job

# Long enough that a reworded title moves the (bag-of-words) test embedding only slightly,
# as it does with bge-m3.
DESCRIPTION = (
    "We build payment services in Python and Django on PostgreSQL. You own features end to "
    "end, from design to production, and work closely with product and data. "
) * 4


def embed(conn) -> list[int]:
    from app.matching.service import embed_missing

    return asyncio.run(embed_missing(conn, FakeOllama().client))


def test_reworded_title_at_the_same_company_merges(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    first = add_job(conn, 1, title="Backend Engineer, Payments", company="Acme",
                    description=DESCRIPTION)  # fmt: skip
    second = add_job(conn, 2, title="Backend Engineer - Payments Team", company="Acme",
                     description=DESCRIPTION, source="lever", locations=["Rotterdam"])  # fmt: skip
    assert first != second  # different canonical keys
    assert merge_near_duplicates(conn, embed(conn)) == 1
    dup = conn.execute("SELECT duplicate_of FROM jobs WHERE id = ?", (second,)).fetchone()[0]
    assert dup == first
    sources = conn.execute("SELECT source FROM job_sources WHERE job_id = ?", (first,)).fetchall()
    assert {r[0] for r in sources} == {"greenhouse", "lever"}
    cities = {r[0] for r in conn.execute("SELECT city FROM job_locations WHERE job_id = ?",
                                         (first,))}  # fmt: skip
    assert cities == {"Amsterdam", "Rotterdam"}
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2  # nothing deleted


def test_seniority_levels_stay_separate(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    add_job(conn, 1, title="Senior Backend Engineer", company="Acme", description=DESCRIPTION)
    add_job(conn, 2, title="Staff Backend Engineer", company="Acme", description=DESCRIPTION)
    assert merge_near_duplicates(conn, embed(conn)) == 0


def test_tracked_job_is_never_merged_away(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    add_job(conn, 1, title="Backend Engineer, Payments", company="Acme", description=DESCRIPTION)
    later = add_job(conn, 2, title="Backend Engineer - Payments", company="Acme Technologies",
                    description=DESCRIPTION)  # fmt: skip
    with conn:
        conn.execute("INSERT INTO applications (job_id, status) VALUES (?, 'saved')", (later,))
    assert merge_near_duplicates(conn, embed(conn)) == 0


def test_same_role_rules():
    def row(title, company):
        return {"title": title, "company_name": company}

    assert same_role(row("Data Engineer", "Acme"), row("Data Engineer", "Acme Technologies"))
    assert not same_role(row("Data Engineer", "Acme"), row("Data Engineer", "Globex"))
    assert not same_role(row("Data Engineer", "Acme"), row("Marketing Manager", "Acme"))
    assert same_role(row("Security Engineer (IAM)", "Acme"), row("IAM Security Engineer", "Acme"))
    # Region, language and segment variants are different jobs.
    assert not same_role(
        row("Account Executive, Chile", "A"), row("Account Executive, Colombia", "A")
    )
    assert not same_role(row("Deal Desk Manager", "A"), row("Deal Desk Manager, APAC", "A"))


def test_reposting_a_merged_job_updates_the_original(tmp_path):
    from app.normalize.ingest import Normaliser, upsert
    from app.sources.base import RawJob

    conn = init_db(tmp_path / "jm.db")
    first = add_job(conn, 1, title="Backend Engineer, Payments", company="Acme",
                    description=DESCRIPTION)  # fmt: skip
    add_job(conn, 2, title="Backend Engineer - Payments Team", company="Acme",
            description=DESCRIPTION, source="lever")  # fmt: skip
    merge_near_duplicates(conn, embed(conn))
    raw = RawJob(source="lever", source_job_id="2", url="https://x/2", company="Acme",
                 title="Backend Engineer - Payments Team", description=DESCRIPTION)  # fmt: skip
    with conn:
        job_id, created = upsert(conn, raw, Normaliser(conn, AppSettings()).normalise(raw))
    assert job_id == first and not created
