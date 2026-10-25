import asyncio

import httpx

from app.db import init_db
from app.lifecycle.expiry import check_urls, expire_deadlines, mark_stale
from app.sources.base import PoliteClient


def add_job(conn, key, **cols):
    base = {"canonical_key": key, "title": key, "company_name": "Acme"}
    base.update(cols)
    names = ", ".join(base)
    marks = ", ".join("?" * len(base))
    with conn:
        job_id = conn.execute(
            f"INSERT INTO jobs ({names}) VALUES ({marks})", list(base.values())
        ).lastrowid
    return job_id


def test_deadline_and_stale(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    past = add_job(conn, "a", valid_through="2020-01-01T00:00:00.000Z")
    future = add_job(conn, "b", valid_through="2099-01-01T00:00:00.000Z")
    old = add_job(conn, "c", last_seen_at="2020-01-01T00:00:00.000Z")
    assert expire_deadlines(conn) == 1
    assert mark_stale(conn) == 1
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM jobs")}
    assert rows[past]["status"] == "expired"
    assert rows[past]["expired_reason"] == "Application deadline passed on 2020-01-01"
    assert rows[future]["status"] == "active"
    assert rows[old]["status"] == "stale"
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3  # nothing deleted


def test_url_check_expires_404_and_closed_postings(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    old = "2020-01-01T00:00:00.000Z"
    ids = {}
    for key in ("gone", "closed", "fine", "redir"):
        url = "https://x.test/jobs/9" if key == "redir" else f"https://x.test/{key}"
        ids[key] = add_job(conn, key, first_seen_at=old)
        with conn:
            conn.execute(
                "INSERT INTO job_sources (job_id, source, url, source_job_id) VALUES (?, ?, ?, ?)",
                (ids[key], "jobspy_linkedin", url, key),
            )

    def handler(request):
        path = request.url.path
        if path == "/gone":
            return httpx.Response(404)
        if path == "/closed":
            return httpx.Response(200, text="This job is no longer accepting applications")
        if path == "/jobs/9":
            return httpx.Response(302, headers={"location": "https://x.test/careers"})
        return httpx.Response(200, text="Apply now")

    http = PoliteClient(
        "url_check", conn, budget=10, delay=(0, 0), transport=httpx.MockTransport(handler)
    )
    result = asyncio.run(check_urls(conn, http, {"jobspy_linkedin"}))
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM jobs")}
    assert result == {"checked": 4, "expired": 3}
    assert rows[ids["gone"]]["expired_reason"].startswith("Listing returned 404")
    assert rows[ids["closed"]]["status"] == "expired"
    assert rows[ids["redir"]]["expired_reason"].startswith("Listing redirects")
    assert rows[ids["fine"]]["status"] == "active" and rows[ids["fine"]]["last_checked_at"]
