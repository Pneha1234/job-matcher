import asyncio
import json

import httpx
import pytest

from app.db import init_db
from app.sources import crawl
from app.sources.base import BudgetExhausted, PoliteClient, SourceBlocked
from app.sources.feeds import parse_hn_comment
from app.sources.runner import board_from_url, run_source, source_state

GREENHOUSE = {
    "jobs": [
        {
            "id": 11,
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/11",
            "title": "Backend Engineer (m/f/d)",
            "company_name": "Acme",
            "location": {"name": "Amsterdam"},
            "offices": [{"location": "Rotterdam"}],
            "content": "&lt;p&gt;Python. We can sponsor visas.&lt;/p&gt;",
            "first_published": "2026-10-20T10:00:00-04:00",
            "metadata": [],
        },
        {
            "id": 12,
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/12",
            "title": "Data Engineer",
            "company_name": "Acme",
            "location": {"name": "Remote, France"},
            "offices": [],
            "content": "SQL",
            "first_published": "2026-10-21T10:00:00Z",
        },
    ]
}


def handler_for(routes: dict):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        for prefix, reply in routes.items():
            if str(request.url).startswith(prefix):
                return reply() if callable(reply) else reply
        return httpx.Response(404, text="not found")

    handler.calls = calls
    return handler


def run(conn, name, routes):
    handler = handler_for(routes)
    result = asyncio.run(run_source(conn, name, transport=httpx.MockTransport(handler)))
    return result, handler.calls


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "jm.db")
    with c:
        c.execute(
            "INSERT INTO companies (name, platform, slug) VALUES ('Acme', 'greenhouse', 'acme')"
        )
    return c


def test_greenhouse_run_stores_jobs_and_logs_the_run(conn):
    gh = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    result, _ = run(conn, "greenhouse", {gh: httpx.Response(200, json=GREENHOUSE)})
    assert result["status"] == "ok" and result["found"] == 2 and result["new"] == 2
    job = conn.execute("SELECT * FROM jobs WHERE title = 'Backend Engineer'").fetchone()
    assert job["visa_sponsorship"] == "yes" and job["company_id"] is not None
    remote = json.loads(
        conn.execute(
            "SELECT remote_eligibility FROM jobs WHERE title = 'Data Engineer'"
        ).fetchone()[0]
    )
    assert remote["remote"] and remote["countries"] == ["FR"]
    run_row = conn.execute("SELECT * FROM scrape_runs").fetchone()
    assert run_row["status"] == "ok" and run_row["found"] == 2 and run_row["budget_used"] == 1


def test_board_missing_twice_expires_with_reason_and_comes_back(conn):
    gh = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    run(conn, "greenhouse", {gh: httpx.Response(200, json=GREENHOUSE)})
    only_one = {"jobs": GREENHOUSE["jobs"][:1]}
    run(conn, "greenhouse", {gh: httpx.Response(200, json=only_one)})
    status = conn.execute("SELECT status FROM jobs WHERE title = 'Data Engineer'").fetchone()[0]
    assert status == "active"  # one miss is not enough
    result, _ = run(conn, "greenhouse", {gh: httpx.Response(200, json=only_one)})
    job = conn.execute("SELECT * FROM jobs WHERE title = 'Data Engineer'").fetchone()
    assert result["expired"] == 1
    assert job["status"] == "expired" and job["expired_reason"].startswith(
        "Removed from Greenhouse"
    )
    # Never deleted, and a re-listing brings it back.
    run(conn, "greenhouse", {gh: httpx.Response(200, json=GREENHOUSE)})
    assert conn.execute("SELECT status FROM jobs WHERE title = 'Data Engineer'").fetchone()[0] == (
        "active"
    )


def test_board_that_fails_does_not_count_misses(conn):
    gh = "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    run(conn, "greenhouse", {gh: httpx.Response(200, json=GREENHOUSE)})
    for _ in range(3):
        run(conn, "greenhouse", {gh: httpx.Response(500, text="boom")})
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'active'").fetchone()[0] == 2


def test_dead_board_is_marked_not_deleted(conn):
    result, _ = run(conn, "greenhouse", {})
    company = conn.execute("SELECT status FROM companies WHERE slug = 'acme'").fetchone()
    assert company["status"] == "dead" and result["found"] == 0


def test_block_pauses_the_source_instead_of_retrying(conn):
    blocked = httpx.Response(429, text="Too many requests")
    result, calls = run(conn, "remotive", {"https://remotive.com": blocked})
    assert result["status"] == "paused" and len(calls) == 1
    assert source_state(conn, "remotive")["status"] == "paused"
    again, calls = run(conn, "remotive", {"https://remotive.com": blocked})
    assert again["status"] == "paused" and calls == []  # paused sources make no requests


def test_captcha_page_counts_as_a_block(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    page = httpx.Response(403, text="<html>Please complete the CAPTCHA</html>")
    client = PoliteClient(
        "x", conn, budget=5, delay=(0, 0), transport=httpx.MockTransport(lambda r: page)
    )
    with pytest.raises(SourceBlocked):
        asyncio.run(client.get_text("https://example.com/jobs"))


def test_budget_and_cache(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    hits = []

    def handler(request):
        hits.append(request.url)
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "x", conn, budget=2, delay=(0, 0), cache_ttl_s=60, transport=httpx.MockTransport(handler)
    )

    async def go():
        await client.get_json("https://example.com/a")
        await client.get_json("https://example.com/a")  # cached
        await client.get_json("https://example.com/b")
        with pytest.raises(BudgetExhausted):
            await client.get_json("https://example.com/c")

    asyncio.run(go())
    assert len(hits) == 2 and client.used_today() == 2


def test_budget_exhausted_pauses_until_tomorrow(conn):
    from datetime import date

    with conn:
        conn.execute(
            "INSERT INTO source_budget (source, day, used) VALUES ('remotive', ?, 999)",
            (date.today().isoformat(),),
        )
    result, calls = run(conn, "remotive", {})
    state = source_state(conn, "remotive")
    assert result["status"] == "paused" and calls == []
    assert state["paused_until"] > date.today().isoformat()


def test_zero_jobs_is_flagged(conn):
    result, _ = run(
        conn, "remotive", {"https://remotive.com": httpx.Response(200, json={"jobs": []})}
    )
    assert result["found"] == 0 and "0 jobs" in result["error"]


def test_feeds_parse():
    remoteok = [
        {"legal": "notice"},
        {"id": "9", "position": "Python Dev", "company": "Co", "url": "https://remoteok.com/9",
         "description": "<p>Py</p>", "location": "Worldwide", "salary_min": 50000,
         "salary_max": 70000, "date": "2026-10-24T00:00:00+00:00"},
    ]  # fmt: skip
    wwr = (
        "<rss><channel><item><title>Acme: Senior Django Developer</title>"
        "<link>https://weworkremotely.com/x</link><guid>x</guid><region>Anywhere in the World"
        "</region><description>&lt;p&gt;Django&lt;/p&gt;</description>"
        "<pubDate>Fri, 24 Oct 2026 10:00:00 +0000</pubDate></item></channel></rss>"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        conn = init_db(f"{d}/jm.db")
        r1, _ = run(conn, "remoteok", {"https://remoteok.com": httpx.Response(200, json=remoteok)})
        r2, _ = run(
            conn, "weworkremotely", {"https://weworkremotely.com": httpx.Response(200, text=wwr)}
        )
        assert r1["found"] == 1 and r2["found"] == 1
        job = conn.execute("SELECT * FROM jobs WHERE company_name = 'Acme'").fetchone()
        assert job["title"] == "Senior Django Developer"
        assert json.loads(job["remote_eligibility"])["worldwide"] is True
        ok = conn.execute("SELECT * FROM jobs WHERE company_name = 'Co'").fetchone()
        assert ok["salary_annual_max"] is None or ok["salary_currency"] == "USD"


def test_hn_comment_parsing():
    assert parse_hn_comment(
        "Acme | Senior Backend Engineer | Berlin, Germany | Full-time\nMore"
    ) == (
        "Acme",
        "Senior Backend Engineer",
        ["Berlin, Germany"],
        False,
    )
    assert parse_hn_comment("Just a question about the thread") is None


MEROJOB_PAGE = """<html><script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "Python Developer",
  "description": "<p>Django and REST.</p>",
  "identifier": {"@type": "PropertyValue", "name": "Board", "value": "KJ-1
  },
  "datePosted": "2026-10-14",
  "validThrough": "2099-10-28T00:00:00+05:45",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {"@type": "Organization", "name": "Leapfrog"},
  "jobLocation": {"@type": "Place", "address": {"addressLocality": "Lalitpur",
                   "addressCountry": "NP"}},
  "baseSalary": {"@type": "MonetaryAmount", "currency": "NPR",
                 "value": {"minValue": 80000, "maxValue": 120000, "unitText": "MONTH"}}
}
</script></html>"""


def test_jsonld_parser_repairs_unclosed_strings():
    postings = crawl.job_postings(MEROJOB_PAGE)
    assert postings and postings[0]["title"] == "Python Developer"


def test_jsonld_parser_repairs_raw_html_quotes():
    page = """<script type="application/ld+json">
       {
            "@type": "JobPosting",
            "title": "Sales &amp; Marketing Officer",
            "description": "<p><span style="color:red;">Sell</span></p>

<p>More</p>",
            "hiringOrganization": {"@type": "Organization", "name": "Ashoka"}
       }
    </script>"""
    posting = crawl.job_postings(page)[0]
    job = crawl.raw_from_posting(posting, "https://x/1", "kumarijob")
    assert job.title == "Sales & Marketing Officer" and "Sell" in job.description


def test_merojob_sitemap_crawl(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    index = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://sg.merojob.com/sitemap-job_post-1.xml</loc></sitemap>"
        "<sitemap><loc>https://sg.merojob.com/sitemap-blog-1.xml</loc></sitemap></sitemapindex>"
    )
    jobs = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://merojob.com/python-developer-1</loc></url></urlset>"
    )
    routes = {
        "https://merojob.com/sitemap.xml": httpx.Response(200, text=index),
        "https://sg.merojob.com/sitemap-job_post-1.xml": httpx.Response(200, text=jobs),
        "https://merojob.com/python-developer-1": httpx.Response(200, text=MEROJOB_PAGE),
    }
    result, calls = run(conn, "merojob", routes)
    assert result["found"] == 1
    assert not any("blog" in c for c in calls)
    job = conn.execute("SELECT * FROM jobs").fetchone()
    loc = conn.execute("SELECT city, country_code FROM job_locations").fetchone()
    assert (loc["city"], loc["country_code"]) == ("Pātan", "NP")  # country hint picks Nepal
    assert job["salary_currency"] == "NPR" and job["salary_period"] == "month"
    assert job["job_type"] == "full-time"
    # Next run: the sitemap alone confirms the posting; its page isn't fetched again.
    _, calls = run(conn, "merojob", routes)
    assert "https://merojob.com/python-developer-1" not in calls


def test_board_urls():
    assert board_from_url("https://boards.greenhouse.io/stripe/jobs/1") == ("greenhouse", "stripe")
    assert board_from_url("https://jobs.lever.co/palantir/abc") == ("lever", "palantir")
    assert board_from_url("https://jobs.ashbyhq.com/ramp") == ("ashby", "ramp")
    assert board_from_url("https://acme.wd5.myworkdayjobs.com/en-US/External/job/x") == (
        "workday",
        "acme|wd5|External",
    )
    assert board_from_url("https://example.com/careers") is None


JOBSNEPAL_PAGE = """<html><body>
<div itemscope itemtype="http://schema.org/JobPosting">
  <h1 itemprop="title">Data   Officer</h1>
  <meta itemprop="datePosted" content="2026-10-16"/>
  <meta itemprop="validThrough" content="2099-10-27 11:59 p.m."/>
  <div itemprop="hiringOrganization" itemscope itemtype="http://schema.org/Organization">
    <span itemprop="name">People in  Need</span>
    <span itemprop="description">An NGO.</span>
  </div>
  <span itemprop="employmentType">Contract</span>
  <span itemprop="description"><p>Manage project data in Rasuwa and report to the PM.</p></span>
  <div itemprop="jobLocation" itemscope itemtype="http://schema.org/Place">
    <div itemprop="address" itemscope itemtype="http://schema.org/PostalAddress">
      <span itemprop="addressLocality">Kathmandu</span>
      <meta itemprop="addressCountry" content="NP"/>
    </div>
  </div>
</div></body></html>"""


def test_microdata_posting():
    posting = crawl.job_postings(JOBSNEPAL_PAGE)[0]
    job = crawl.raw_from_posting(posting, "https://www.jobsnepal.com/x", "jobsnepal")
    assert (job.title, job.company, job.locations) == (
        "Data Officer",
        "People in Need",
        ["Kathmandu, NP"],
    )
    assert "Manage project data" in job.description and "An NGO" not in job.description
    assert job.valid_through.year == 2099 and job.valid_through.hour == 23
    assert job.job_type_raw == "Contract"


def sitemap(*urls: str) -> str:
    locs = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'


def test_big_board_fetches_only_postings_matching_saved_searches(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    with conn:
        conn.execute(
            "INSERT INTO saved_searches (name, filters) VALUES "
            '(\'x\', \'{"query": "Python developer", "location": "Pune"}\')'
        )
    index = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://www.freshersworld.com/sitemap-activejobs-1.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    py = "https://www.freshersworld.com/jobs/python-developer-jobs-opening-at-pune-1"
    other = "https://www.freshersworld.com/jobs/accountant-jobs-opening-at-pune-2"
    page = MEROJOB_PAGE.replace("Leapfrog", "Acme")
    routes = {
        "https://www.freshersworld.com/robots.txt": httpx.Response(
            200, text="User-agent: *\nDisallow: /admin/"
        ),
        "https://www.freshersworld.com/sitemap-index.xml": httpx.Response(200, text=index),
        "https://www.freshersworld.com/sitemap-activejobs-1.xml": httpx.Response(
            200, text=sitemap(py, other)
        ),
        py: httpx.Response(200, text=page),
    }
    result, calls = run(conn, "freshersworld", routes)
    assert result["found"] == 1 and other not in calls


def test_robots_disallow_is_respected(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    job = "https://merojob.com/python-developer-1"
    routes = {
        "https://merojob.com/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /"),
        "https://merojob.com/sitemap.xml": httpx.Response(200, text=sitemap(job)),
        job: httpx.Response(200, text=MEROJOB_PAGE),
    }
    result, calls = run(conn, "merojob", routes)
    assert job not in calls and result["found"] == 0 and "robots.txt" in result["error"]


def test_listing_board(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    home = '<a href="/job/Graphic-Designer/48536">x</a><a href="/about">y</a>'
    job = "https://jobejee.com/job/Graphic-Designer/48536"
    routes = {
        "https://jobejee.com/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /"),
        "https://jobejee.com/job/": httpx.Response(200, text=MEROJOB_PAGE),
        "https://jobejee.com/": httpx.Response(200, text=home),
    }
    result, calls = run(conn, "jobejee", routes)
    assert result["found"] == 1 and job in calls
    assert not any(c.endswith("/about") for c in calls)
