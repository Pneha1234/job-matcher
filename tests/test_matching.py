import pytest

from app.matching import eligibility
from app.matching.score import JobAssessment, final_pct, sub_scores
from app.profile.schema import ProfileData
from app.settings_store import AppSettings, Weights, load, save
from tests.conftest import wait_task
from tests.fakes import ASSESSMENT, PROFILE
from tests.helpers import add_job, save_profile


def test_percentage_is_computed_in_code_from_validated_classes():
    a = JobAssessment.model_validate(ASSESSMENT)
    subs = sub_scores(a, "eligible", [])
    # required: 2 matched + 1 partial of 4 -> 62.5 -> 62 (rounded half to even)
    assert subs == {"required": 62, "nice": 100, "seniority": 100, "domain": 65, "location": 100}
    assert final_pct(subs, Weights()) == pytest.approx(
        (62 * 50 + 100 * 15 + 100 * 15 + 65 * 10 + 100 * 10) / 100
    )


def test_code_facts_override_the_model():
    a = JobAssessment.model_validate(ASSESSMENT)
    assert sub_scores(a, "not_eligible", [])["location"] == 0
    assert sub_scores(a, "eligible", ["Dutch"])["location"] == 40


def test_unclear_parts_drop_out_and_no_required_skills_means_no_score():
    a = JobAssessment.model_validate({**ASSESSMENT, "domain_fit": "unclear"})
    subs = sub_scores(a, "eligible", [])
    assert subs["domain"] is None
    w = Weights()
    expected = (62 * 50 + 100 * 15 + 100 * 15 + 100 * 10) / 90
    assert final_pct(subs, w) == pytest.approx(expected, abs=0.05)
    # An empty required list is an invalid answer (retried, then unscored), and a missing
    # required sub-score never yields a percentage.
    with pytest.raises(ValueError):
        JobAssessment.model_validate({**ASSESSMENT, "required_skills": []})
    assert final_pct({**subs, "required": None}, w) is None
    assert final_pct(subs, Weights(required=0, nice=0, seniority=0, domain=0, location=0)) is None


def job(remote=None, visa=None, langs="[]"):
    import json

    return {"remote_eligibility": json.dumps(remote or {}), "visa_sponsorship": visa,
            "language_reqs": langs}  # fmt: skip


def test_location_eligibility():
    s = AppSettings(home_country="NP", target_countries=["NL"])
    assert eligibility.location_status(job(), ["NL"], s)[0] == "eligible"
    assert eligibility.location_status(job(), ["US"], s)[0] == "not_eligible"
    us_only = job({"remote": True, "countries": ["US"]})
    status, reason = eligibility.location_status(us_only, [], s)
    assert status == "not_eligible" and "US" in reason
    assert (
        eligibility.location_status(job({"remote": True, "worldwide": True}), [], s)[0]
        == "eligible"
    )
    asia = job({"remote": True, "regions": ["South Asia"]})
    assert eligibility.location_status(asia, [], s)[0] == "eligible"
    assert eligibility.location_status(job({"remote": True}), [], s)[0] == "unknown"
    reloc = AppSettings(home_country="NP", target_countries=["NL"], open_to_relocation=True)
    assert eligibility.location_status(job(), ["DE"], reloc)[0] == "relocation"
    visa = AppSettings(home_country="NP", target_countries=["NL"], needs_visa=True)
    assert eligibility.location_status(job(visa="no"), ["NL"], visa)[0] == "not_eligible"
    assert eligibility.location_status(job(), ["NL"], AppSettings())[0] == "unknown"


def test_language_gaps():
    p = ProfileData.model_validate(PROFILE)
    assert eligibility.language_gaps(job(langs='["nl", "en"]'), p) == ["Dutch"]


def test_scoring_task_ranks_and_caches(client, db, fake_ollama):
    s = load(db)
    s.home_country, s.target_countries = "NP", ["NL"]
    save(db, s)
    near = add_job(db, 1, title="Senior Python Django Developer")
    add_job(db, 2, title="Python Developer", locations=["New York"])  # outside targets
    save_profile(db)
    task = wait_task(client, client.post("/scoring/run").json()["task_id"])
    assert task["status"] == "done", task
    assert task["result"] == {"profile_version_id": 1, "scored": 1, "unscored": 0}
    row = db.execute("SELECT * FROM match_scores").fetchone()
    assert row["job_id"] == near and row["status"] == "scored" and row["final_pct"] > 0
    # Cached per (job, profile version): a second run makes no LLM call.
    before = len(fake_ollama.calls)
    wait_task(client, client.post("/scoring/run").json()["task_id"])
    assert not [c for c in fake_ollama.calls[before:] if "messages" in c]


def test_invalid_llm_output_becomes_unscored_with_retry(client, db, fake_ollama):
    job_id = add_job(db, 1)
    save_profile(db)
    fake_ollama.queue("JobAssessment", "garbage", '{"explanation": "x"}')
    wait_task(client, client.post("/scoring/run").json()["task_id"])
    card = client.get("/jobs").json()["items"][0]
    assert card["match"]["status"] == "unscored" and card["match"]["pct"] is None
    assert card["match"]["error"]
    task = wait_task(client, client.post(f"/jobs/{job_id}/score").json()["task_id"])
    assert task["result"]["status"] == "scored"
    assert client.get("/jobs").json()["items"][0]["match"]["pct"] is not None


def test_ollama_down_is_unscored_not_guessed(client, db, fake_ollama):
    job_id = add_job(db, 1)
    vid = save_profile(db)
    fake_ollama.down = True
    task = wait_task(client, client.post(f"/jobs/{job_id}/score").json()["task_id"])
    assert task["result"]["status"] == "unscored"
    row = db.execute(
        "SELECT * FROM match_scores WHERE job_id = ? AND profile_version_id = ?", (job_id, vid)
    ).fetchone()
    assert row["final_pct"] is None and "Ollama" in row["error"]


def test_new_profile_version_labels_old_scores(client, db):
    add_job(db, 1)
    save_profile(db)
    wait_task(client, client.post("/scoring/run").json()["task_id"])
    from app.profile import store
    from app.profile.schema import ProfileData

    v2 = store.create_draft(db, {}, ProfileData.model_validate(PROFILE))
    store.save_draft(db, v2)
    card = client.get("/jobs").json()["items"][0]
    assert card["match"]["stale_version"] and card["match"]["version_label"] == "Profile v1"


def test_weights_change_rerank(client, db):
    add_job(db, 1)
    save_profile(db)
    wait_task(client, client.post("/scoring/run").json()["task_id"])
    before = client.get("/jobs").json()["items"][0]["match"]["pct"]
    preview = client.post(
        "/settings/preview",
        json={"weights": {"required": 0, "nice": 0, "seniority": 100, "domain": 0, "location": 0}},
    ).json()
    assert preview[0]["pct"] == 100
    s = client.get("/settings").json()["settings"]
    s["weights"] = {"required": 100, "nice": 0, "seniority": 0, "domain": 0, "location": 0}
    assert client.put("/settings", json=s).json()["reweighted"] == 1
    after = client.get("/jobs").json()["items"][0]["match"]["pct"]
    assert after == 62 and after != before


def test_job_without_description_is_unscored_without_an_llm_call(client, db, fake_ollama):
    job_id = add_job(db, 1, description="")
    save_profile(db)
    task = wait_task(client, client.post(f"/jobs/{job_id}/score").json()["task_id"])
    assert task["result"]["status"] == "unscored"
    assert "no description" in task["result"]["error"]
    assert not [c for c in fake_ollama.calls if "messages" in c]


def test_failed_jobs_are_retried_on_the_next_run(client, db, fake_ollama):
    job_id = add_job(db, 1)
    save_profile(db)
    fake_ollama.queue("JobAssessment", '{"required_skills": []}', '{"required_skills": []}')
    wait_task(client, client.post("/scoring/run").json()["task_id"])
    first = db.execute("SELECT status FROM match_scores WHERE job_id = ?", (job_id,)).fetchone()
    assert first["status"] == "unscored"
    task = wait_task(client, client.post("/scoring/run").json()["task_id"])
    assert task["result"]["scored"] == 1
    again = db.execute("SELECT status FROM match_scores WHERE job_id = ?", (job_id,)).fetchone()
    assert again["status"] == "scored"
