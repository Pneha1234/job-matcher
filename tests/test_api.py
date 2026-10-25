"""Jobs list filters, tracker, sources, settings and insights through the HTTP API."""

import httpx

from app.settings_store import load, save
from tests.conftest import wait_task
from tests.helpers import add_job, save_profile


def ids(client, **params):
    return [j["id"] for j in client.get("/jobs", params=params).json()["items"]]


def test_filters(client, db):
    s = load(db)
    s.home_country = "NP"
    save(db, s)
    ams = add_job(
        db, 1, description="Python. Salary €70,000 - €90,000 per year.", job_type_raw="Full-time"
    )
    ny = add_job(db, 2, locations=["New York"], job_type_raw="Contract")
    remote_ww = add_job(db, 3, locations=["Remote (Worldwide)"])
    remote_us = add_job(db, 4, locations=["Remote (US only)"])
    unclear = add_job(db, 5, locations=["Somewhere"])
    assert set(ids(client)) == {ams, ny, remote_ww, remote_us, unclear}
    assert ids(client, countries=["NL"], location_unclear=False) == [ams]
    assert set(ids(client, countries=["NL"])) == {ams, unclear}
    assert ids(client, regions=["North America"], location_unclear=False) == [ny]
    assert ids(client, remote_eligible=True, location_unclear=False) == [remote_ww]
    assert ids(client, types=["contract"]) == [ny]
    assert ids(client, salary_only=True) == [ams]
    assert ids(client, salary_min=80000) == [ams]
    assert ids(client, q="Developer 2") == [ny]
    assert ids(client, sort="salary")[0] == ams


def test_actions_hide_save_apply_with_undo(client, db):
    job = add_job(db, 1)
    r = client.put(f"/jobs/{job}/application", json={"status": "saved"}).json()
    assert r["previous_status"] == "archived"
    assert client.get("/jobs").json()["items"][0]["application"]["status"] == "saved"
    client.put(f"/jobs/{job}/application", json={"status": "applied"})
    assert ids(client, hide_applied=True) == []
    # Undo goes back to saved; history keeps every step.
    client.put(f"/jobs/{job}/application", json={"status": "saved"})
    app_id = client.get("/applications").json()[0]["id"]
    steps = [e["to_status"] for e in client.get(f"/applications/{app_id}/events").json()]
    assert steps == ["saved", "applied", "saved"]
    # Un-saving archives; the row is kept.
    client.put(f"/jobs/{job}/application", json={"status": "archived"})
    assert client.get("/applications").json() == []
    assert db.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    client.put(f"/jobs/{job}/flags", json={"hidden": True, "reason": "Not my stack"})
    assert ids(client) == [] and ids(client, show_hidden=True) == [job]
    client.put(f"/jobs/{job}/flags", json={"hidden": False})
    assert ids(client) == [job]


def test_expired_hidden_by_default_with_reason(client, db):
    job = add_job(db, 1)
    with db:
        db.execute(
            "UPDATE jobs SET status = 'expired', expired_reason = 'Removed from Lever' "
            "WHERE id = ?",
            (job,),
        )
    assert ids(client) == []
    card = client.get("/jobs", params={"show_expired": True}).json()["items"][0]
    assert card["status"] == "expired" and card["expired_reason"] == "Removed from Lever"


def test_board_follow_up_and_csv(client, db):
    job = add_job(db, 1)
    client.put(f"/jobs/{job}/application", json={"status": "applied"})
    with db:
        db.execute("UPDATE applications SET applied_at = '2026-01-01T00:00:00.000Z'")
    card = client.get("/applications").json()[0]
    assert card["follow_up"] and card["days_since_applied"] > 14
    r = client.patch(
        f"/applications/{card['id']}", json={"status": "interviewing", "notes": "Round 2 Fri"}
    )
    assert r.json()["status"] == "interviewing" and r.json()["notes"] == "Round 2 Fri"
    csv = client.get("/applications/export.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert "Company 1,Python Developer 1,interviewing" in csv.text


def test_job_detail(client, db):
    job = add_job(db, 1, locations=["Amsterdam", "Remote (EU)"])
    save_profile(db)
    wait_task(client, client.post("/scoring/run").json()["task_id"])
    d = client.get(f"/jobs/{job}").json()
    assert d["match"]["sub_scores"]["required"] == 62
    assert d["match"]["explanation"] and d["sources"][0]["source"] == "greenhouse"
    assert {loc["city"] for loc in d["locations"]} >= {"Amsterdam"}
    assert client.get("/jobs/999").status_code == 404


def test_cover_letter_and_manual_import(client, db, fake_ollama, monkeypatch):
    save_profile(db)
    job = add_job(db, 1)
    t = wait_task(client, client.post(f"/jobs/{job}/cover-letter").json()["task_id"])
    assert t["result"]["letter"].startswith("Dear hiring team")
    text = "We are hiring a Python developer in Amsterdam. " * 5
    t = wait_task(client, client.post("/jobs/import", json={"text": text}).json()["task_id"])
    assert t["status"] == "done", t
    assert t["result"]["title"] == "Python Developer" and t["result"]["created"]
    imported = client.get(f"/jobs/{t['result']['job_id']}").json()
    assert imported["sources"][0]["source"] == "manual" and imported["match"]["status"] == "scored"
    assert client.post("/jobs/import", json={}).status_code == 422
    t = wait_task(client, client.post("/jobs/import", json={"text": "too short"}).json()["task_id"])
    assert t["status"] == "error" and "full posting" in t["error"]


def test_sources_page_and_company_list(client, db, monkeypatch):
    names = {s["name"] for s in client.get("/sources").json()["sources"]}
    assert {"greenhouse", "jobspy_linkedin", "merojob", "remotive", "hn_whos_hiring"} <= names
    assert client.post("/sources/remotive/pause").json()["paused"]
    row = next(s for s in client.get("/sources").json()["sources"] if s["name"] == "remotive")
    assert row["health"] == "paused"
    client.post("/sources/remotive/resume")
    c = client.post("/companies", json={"url": "https://boards.greenhouse.io/acme"}).json()
    assert (c["platform"], c["slug"]) == ("greenhouse", "acme")
    c2 = client.post("/companies", json={"url": "acme.example/careers", "name": "Acme"}).json()
    assert c2["platform"] == "jsonld" and c2["careers_url"] == "https://acme.example/careers"
    assert (
        client.patch(f"/companies/{c['id']}", json={"status": "paused"}).json()["status"]
        == "paused"
    )
    # Seeded crawl list exists on first start.
    assert len(client.get("/companies", params={"platform": "greenhouse"}).json()) > 30


def test_run_source_from_the_ui(client, db, monkeypatch):
    payload = {"jobs": [{"id": 1, "url": "https://remotive.com/1", "title": "Python Developer",
                         "company_name": "Co", "description": "Python", "job_type": "full_time",
                         "candidate_required_location": "Worldwide"}]}  # fmt: skip
    real = httpx.AsyncClient.__init__

    def init(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        real(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    t = wait_task(client, client.post("/sources/remotive/run").json()["task_id"])
    assert t["result"]["found"] == 1
    row = next(s for s in client.get("/sources").json()["sources"] if s["name"] == "remotive")
    assert row["health"] == "ok" and row["history"] == [1]
    assert client.get("/summary").json()["jobs_active"] == 1


def test_saved_searches(client):
    r = client.post("/searches", json={"text": "Django developer · Utrecht"}).json()
    assert (r["query"], r["location"]) == ("Django developer", "Utrecht")
    dup = client.post("/searches", json={"text": "django developer · utrecht"})
    assert dup.status_code == 422
    client.post(f"/searches/{r['id']}/archive")
    assert client.get("/searches").json() == []
    client.post(f"/searches/{r['id']}/restore")
    assert len(client.get("/searches").json()) == 1


def test_settings_validation(client):
    s = client.get("/settings").json()["settings"]
    s["home_country"] = "Nepal"
    assert client.put("/settings", json=s).status_code == 422
    s["home_country"] = "np"
    assert client.put("/settings", json=s).json()["settings"]["home_country"] == "NP"


def test_insights(client, db):
    job = add_job(db, 1)
    save_profile(db)
    wait_task(client, client.post("/scoring/run").json()["task_id"])
    client.put(f"/jobs/{job}/application", json={"status": "applied"})
    data = client.get("/insights").json()
    assert data["stats"]["applied_30d"] == 1
    assert data["missing_skills"][0]["skill"] == "Kubernetes"
    assert len(data["per_day"]) == 14


def test_api_keys_are_set_from_settings_and_shown_on_sources(client):
    row = next(s for s in client.get("/sources").json()["sources"] if s["name"] == "jooble")
    assert row["health"] == "needs_key" and row["key_help"]
    assert client.put("/settings/keys", json={"source": "jooble", "value": "k"}).json()["has_key"]
    row = next(s for s in client.get("/sources").json()["sources"] if s["name"] == "jooble")
    assert row["has_key"] and row["health"] == "never"
    assert (
        client.put("/settings/keys", json={"source": "remotive", "value": "k"}).status_code == 404
    )
    assert not client.put("/settings/keys", json={"source": "jooble", "value": ""}).json()[
        "has_key"
    ]


def test_notifications_and_digest(client, db):
    job = add_job(db, 1)
    save_profile(db)
    wait_task(client, client.post("/scoring/run").json()["task_id"])
    pct = client.get("/jobs").json()["items"][0]["match"]["pct"]
    s = client.get("/settings").json()["settings"]
    s["notify_threshold"] = int(pct)
    client.put("/settings", json=s)
    found = client.get("/notifications", params={"since": "2000-01-01T00:00:00Z"}).json()
    assert [n["id"] for n in found] == [job]
    assert client.get("/notifications", params={"since": "2999-01-01T00:00:00Z"}).json() == []
    digest = client.get("/digest").json()
    assert digest["new_jobs"] == 1 and digest["top_matches"][0]["id"] == job
    md = client.get("/digest.md").text
    assert md.startswith("# Job Matcher digest for today") and "Python Developer 1" in md
    # Applying takes a job out of "new matches"; turning notifications off silences them.
    client.put(f"/jobs/{job}/application", json={"status": "applied"})
    assert client.get("/digest").json()["top_matches"] == []
    s["notify"] = False
    client.put("/settings", json=s)
    assert client.get("/notifications", params={"since": "2000-01-01T00:00:00Z"}).json() == []
