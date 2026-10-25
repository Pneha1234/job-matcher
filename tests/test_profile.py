import io
import json
import zipfile

import docx
import httpx
import pymupdf
import pytest

from app.profile import store
from app.profile.extract import merge
from app.profile.links import GitHubEvidence, GitHubLanguage, fetch_github, github_username
from app.profile.parse import InputError, linkedin_export, resume_text
from app.profile.schema import ExtractedProfile, ProfileData
from tests.conftest import wait_task

RESUME = (
    "Jane Doe — Senior Backend Engineer\n"
    "8 years building Python and Django services with PostgreSQL and Celery at fintech "
    "companies in Kathmandu and Amsterdam. Languages: English (fluent), Nepali (native)."
)


def make_docx(text: str = RESUME) -> bytes:
    d = docx.Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_pdf(text: str = RESUME) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text)
    return doc.tobytes()


def make_linkedin_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "Profile.csv", "First Name,Last Name,Headline,Summary\nJane,Doe,Backend,Builds APIs\n"
        )
        zf.writestr(
            "Positions.csv",
            "Company Name,Title,Description,Location,Started On,Finished On\n"
            "Acme,Backend Engineer,Django APIs,Amsterdam,Jan 2020,\n",
        )
        zf.writestr("Skills.csv", "Name\nPython\nAWS\n")
        zf.writestr("Languages.csv", "Name,Proficiency\nEnglish,Full professional proficiency\n")
    return buf.getvalue()


def test_resume_text_from_docx_and_pdf():
    assert "Django" in resume_text("cv.docx", make_docx())
    assert "Django" in resume_text("cv.pdf", make_pdf())


@pytest.mark.parametrize(
    "name, data, message",
    [
        ("cv.txt", b"hello", "isn't supported"),
        ("cv.pdf", b"x" * (10 * 1024 * 1024 + 1), "over 10 MB"),
        ("cv.pdf", b"not a pdf", "could not be opened"),
        ("cv.docx", make_docx("Hi"), "No readable text"),
    ],
)
def test_resume_rejections(name, data, message):
    with pytest.raises(InputError, match=message):
        resume_text(name, data)


def test_linkedin_export():
    export = linkedin_export(make_linkedin_zip())
    assert export.positions[0].company == "Acme"
    assert export.skills == ["Python", "AWS"]
    with pytest.raises(InputError):
        linkedin_export(b"not a zip")


def test_github_username_validation():
    assert github_username("github.com/janedoe") == "janedoe"
    assert github_username("https://github.com/jane-doe/") == "jane-doe"
    with pytest.raises(InputError):
        github_username("gitlab.com/jane")


def test_github_evidence_skips_forks():
    repos = [
        {"language": "Python", "fork": False, "pushed_at": "2026-05-01T00:00:00Z",
         "topics": ["django"]},
        {"language": "Python", "fork": False, "pushed_at": "2024-05-01T00:00:00Z"},
        {"language": "Go", "fork": True, "pushed_at": "2026-05-01T00:00:00Z"},
    ]  # fmt: skip
    t = httpx.MockTransport(lambda r: httpx.Response(200, json=repos))
    import asyncio

    ev = asyncio.run(fetch_github("jane", transport=t))
    assert ev.public_repos == 2
    assert [(x.name, x.repos, x.last_pushed_year) for x in ev.languages] == [("Python", 2, 2026)]


def test_merge_attaches_provenance_and_never_invents():
    extracted = ExtractedProfile(
        skills=[{"name": "Python", "years": 8}, {"name": "Kubernetes"}], seniority="senior"
    )
    gh = GitHubEvidence(
        username="jane",
        public_repos=3,
        languages=[
            GitHubLanguage(name="Python", repos=3),
            GitHubLanguage(name="TypeScript", repos=1),
            GitHubLanguage(name="HTML", repos=2),
        ],
        topics=[],
    )
    li = linkedin_export(make_linkedin_zip())
    p = merge(extracted, RESUME, li, gh, None)
    by = {s.name: s.sources for s in p.skills}
    assert by["Python"] == ["Resume", "LinkedIn export", "GitHub (3 repos)"]
    assert by["Kubernetes"] == ["Model inferred"]  # not in any input: flagged for review
    assert by["TypeScript"] == ["GitHub (1 repos)"]
    assert by["AWS"] == ["LinkedIn export"]
    assert "HTML" not in by
    # Fill-by-hand path: no LLM output, only deterministic evidence.
    manual = merge(None, RESUME, li, gh, None)
    assert manual.seniority is None and {s.name for s in manual.skills} == {
        "Python",
        "TypeScript",
        "AWS",
    }
    assert [x.level for x in manual.languages] == ["fluent"]


def test_versions_are_kept_and_one_is_active(tmp_path):
    from app.db import init_db

    conn = init_db(tmp_path / "jm.db")
    v1 = store.create_draft(conn, {}, ProfileData(skills=[{"name": "Python", "years": 7}]))
    store.save_draft(conn, v1)
    v2 = store.create_draft(conn, {}, ProfileData(skills=[{"name": "Python", "years": 8},
                                                        {"name": "FastAPI"}]))  # fmt: skip
    d = store.diff(store.previous_saved(conn, v2), store.get(conn, v2))
    assert d["against"] == "Profile v1" and d["added"] == ["FastAPI"]
    assert d["changed"][0] == {"field": "Python", "from": 7, "to": 8}
    store.save_draft(conn, v2)
    versions = store.list_versions(conn)
    assert [(v["label"], v["is_active"]) for v in versions] == [
        ("Profile v2", True),
        ("Profile v1", False),
    ]
    with pytest.raises(store.ProfileError):
        store.update_draft(conn, v1, ProfileData())  # saved versions are immutable
    store.activate(conn, v1)
    assert store.active(conn)["label"] == "Profile v1"


def test_duplicate_skills_rejected():
    with pytest.raises(ValueError, match="listed twice"):
        ProfileData(skills=[{"name": "Python"}, {"name": "python"}])


def test_wizard_flow_end_to_end(client, fake_ollama):
    r = client.post(
        "/profile/parse",
        files={"resume": ("cv.docx", make_docx()), "linkedin": ("export.zip", make_linkedin_zip())},
        data={"github": "", "portfolio": ""},
    )
    assert r.status_code == 200
    task = wait_task(client, r.json()["task_id"])
    assert task["status"] == "done", task
    assert [p["state"] for p in task["progress"]] == ["done"] * 4
    vid = task["result"]["profile_version_id"]
    draft = client.get(f"/profile/versions/{vid}").json()
    assert draft["status"] == "draft" and draft["profile"]["seniority"] == "senior"
    assert draft["diff"]["against"] is None
    profile = draft["profile"]
    profile["skills"].append({"name": "Kubernetes", "years": 1, "sources": ["Added by you"]})
    assert client.put(f"/profile/versions/{vid}", json=profile).status_code == 200
    saved = client.post(f"/profile/versions/{vid}/save").json()
    assert saved["label"] == "Profile v1" and saved["is_active"]
    assert saved["rescore_task_id"]
    assert client.get("/profile/active").json()["id"] == vid
    # The resume went to the local model only.
    assert all(c.get("model") == "qwen2.5:14b" for c in fake_ollama.calls if "messages" in c)


def test_wizard_validation_errors(client):
    r = client.post(
        "/profile/parse",
        files={"resume": ("cv.txt", b"hello")},
        data={"github": "not a url", "portfolio": "nope"},
    )
    assert r.status_code == 422
    fields = r.json()["detail"]["fields"]
    assert set(fields) == {"resume", "github", "portfolio"}
    r = client.post("/profile/parse", data={"github": ""})
    assert r.json()["detail"]["fields"]["resume"] == "Add your resume first."


def test_llm_failure_keeps_inputs_and_allows_retry(client, fake_ollama):
    fake_ollama.queue("ExtractedProfile", "not json", '{"skills": "nope"}')
    r = client.post("/profile/parse", files={"resume": ("cv.pdf", make_pdf())})
    task = wait_task(client, r.json()["task_id"])
    assert task["status"] == "done" and task["result"]["llm_error"]
    vid = task["result"]["profile_version_id"]
    draft = client.get(f"/profile/versions/{vid}").json()
    assert draft["inputs"]["llm_error"] and draft["profile"]["seniority"] is None
    retry = wait_task(client, client.post(f"/profile/versions/{vid}/reparse").json()["task_id"])
    assert retry["result"]["llm_error"] is None
    assert client.get(f"/profile/versions/{vid}").json()["profile"]["seniority"] == "senior"


def test_parse_prompt_contains_resume(client, fake_ollama):
    r = client.post("/profile/parse", files={"resume": ("cv.docx", make_docx())})
    wait_task(client, r.json()["task_id"])
    chat = [c for c in fake_ollama.calls if "messages" in c][0]
    assert "Django" in chat["messages"][-1]["content"]
    assert json.dumps(chat["format"])  # schema-constrained output
