import pytest

from app.db import init_db
from app.normalize import classify, fx
from app.normalize.geo import load_geo
from app.normalize.ingest import Normaliser, canonical_key, upsert
from app.normalize.salary import parse_salary
from app.settings_store import AppSettings
from app.sources.base import RawJob


@pytest.mark.parametrize(
    "text, hint, expected",
    [
        ("€75k–95k", None, (75000, 95000, "EUR", "year")),
        ("$190k–230k", None, (190000, 230000, "USD", "year")),
        ("12 LPA", None, (1_200_000, 1_200_000, "INR", "year")),
        ("8-12 LPA", None, (800_000, 1_200_000, "INR", "year")),
        ("₹8–12 lakhs", None, (800_000, 1_200_000, "INR", "year")),
        ("NPR 80,000/month", None, (80000, 80000, "NPR", "month")),
        ("Rs. 50,000 per month", "NPR", (50000, 50000, "NPR", "month")),
        ("€85/hr", None, (85, 85, "EUR", "hour")),
        ("£40,000 - £50,000 per annum", None, (40000, 50000, "GBP", "year")),
        ("€ 4.500 - 5.500 brutto monatlich", None, (4500, 5500, "EUR", "month")),
        ("$211.4K - $290.6K", None, (211400, 290600, "USD", "year")),
        ("SEK 45 000 - 55 000 per month", None, (45000, 55000, "SEK", "month")),
        # The period can't be told: amounts kept, annual stays unknown.
        ("NPR 80,000", None, (80000, 80000, "NPR", None)),
    ],
)
def test_salary_parsing(text, hint, expected):
    s = parse_salary(text, hint)
    assert (s.min, s.max, s.currency, s.period) == expected


@pytest.mark.parametrize(
    "text", ["Negotiable", "Competitive", "As per company norms", "competitive + equity", ""]
)
def test_undisclosed_salary_is_none_never_zero(text):
    assert parse_salary(text) is None


def test_fx_conversion_and_npr_peg():
    rates = fx.parse_ecb(
        '<x><Cube><Cube time="2026-10-24"><Cube currency="USD" rate="1.10"/>'
        '<Cube currency="INR" rate="90.0"/></Cube></Cube></x>'
    )
    assert rates["NPR"] == pytest.approx(144.0)
    assert fx.convert(110, "USD", "EUR", rates) == pytest.approx(100)
    assert fx.convert(144, "NPR", "INR", rates) == pytest.approx(90)
    assert fx.convert(100, "XYZ", "EUR", rates) is None


def where(s, hint=None):
    r = load_geo().resolve(s, hint)
    return [(x.city, x.country_code, x.resolved) for x in r.locations], r


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Amsterdam", [("Amsterdam", "NL", True)]),
        ("Bangalore", [("Bengaluru", "IN", True)]),
        ("Gurgaon", [("Gurugram", "IN", True)]),
        ("München", [("Munich", "DE", True)]),
        ("Kathmandu Valley", [("Kathmandu", "NP", True)]),
        ("London", [("London", "GB", True)]),  # 20x bigger than London, Ontario
        ("London, ON", [("London", "CA", True)]),
        ("Cambridge", [(None, None, False)]),  # two similar-sized cities: never guessed
        ("Cambridge, MA", [("Cambridge", "US", True)]),
        ("Ireland", [(None, "IE", True)]),  # a country, not the US town that aliases it
        ("Washington, D.C.", [("Washington", "US", True)]),
        ("Amsterdam, North Holland, Netherlands", [("Amsterdam", "NL", True)]),
        ("Toronto, Canada; Paris, France", [("Toronto", "CA", True), ("Paris", "FR", True)]),
    ],
)
def test_locations(text, expected):
    assert where(text)[0] == expected


def test_ambiguous_city_resolved_by_country_hint():
    assert where("Lalitpur")[0] == [(None, None, False)]
    assert where("Lalitpur", "NP")[0] == [("Pātan", "NP", True)]


def test_remote_scopes():
    _, r = where("Remote (US only)")
    assert r.remote and r.remote_countries == {"US"} and not r.worldwide
    _, r = where("Remote - Europe")
    assert r.remote_regions == {"Europe"}
    _, r = where("Worldwide")
    assert r.worldwide
    locs, r = where("New York, NY / Remote (US)")
    assert locs == [("New York City", "US", True)] and r.remote_countries == {"US"}


def test_classifiers():
    assert classify.visa("We are unable to sponsor visas.") == "no"
    assert classify.visa("Visa sponsorship is available") == "yes"
    assert classify.visa("without sponsorship for an export license") is None
    assert classify.job_type("FullTime") == "full-time"
    assert classify.job_type(None, "Django Contractor (6 months)") == "contract"
    assert classify.language_requirements("Dutch (spoken) is required.") == ["nl"]
    assert classify.language_requirements("German is a plus.") == []
    assert classify.india_fields(
        "Notice period: 30 days. Immediate joiners. 3-5 years experience"
    ) == {
        "notice_period_days": 30,
        "immediate_joiner": True,
        "experience_min": 3,
        "experience_max": 5,
    }
    assert classify.html_to_text(
        "&lt;p&gt;Hi&lt;/p&gt;&lt;ul&gt;&lt;li&gt;a&lt;/li&gt;&lt;/ul&gt;"
    ) == ("Hi\n• a")


def test_canonical_key_ignores_gender_markers_and_company_suffix():
    assert canonical_key("Acme GmbH", "Backend Developer (m/w/d)") == canonical_key(
        "ACME", "Backend developer"
    )


def raw(**kw) -> RawJob:
    base = dict(
        source="greenhouse",
        source_job_id="1",
        url="https://example.com/1",
        title="Senior Backend Engineer",
        company="Acme",
        description="Python and Django. Salary: €70,000 - €90,000 per year.",
        locations=["Amsterdam"],
    )
    base.update(kw)
    return RawJob(**base)


def test_same_job_on_two_boards_and_two_cities_is_one_job(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    n = Normaliser(conn, AppSettings())
    with conn:
        a, created_a = upsert(conn, raw(), n.normalise(raw()))
        r2 = raw(source="lever", source_job_id="x", locations=["Rotterdam"], url="https://l/x")
        b, created_b = upsert(conn, r2, n.normalise(r2))
    assert a == b and created_a and not created_b
    assert (
        conn.execute("SELECT COUNT(*) FROM job_sources WHERE job_id = ?", (a,)).fetchone()[0] == 2
    )
    cities = {r[0] for r in conn.execute("SELECT city FROM job_locations WHERE job_id = ?", (a,))}
    assert cities == {"Amsterdam", "Rotterdam"}
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (a,)).fetchone()
    assert job["salary_currency"] == "EUR" and job["salary_annual_max"] == 90000


def test_repost_keeps_first_seen_and_reactivates(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    n = Normaliser(conn, AppSettings())
    with conn:
        job_id, _ = upsert(conn, raw(), n.normalise(raw()))
        conn.execute(
            "UPDATE jobs SET first_seen_at = '2026-01-01T00:00:00.000Z', status = 'expired', "
            "expired_reason = 'Removed' WHERE id = ?",
            (job_id,),
        )
        again = raw(source_job_id="2", url="https://example.com/2")
        same_id, created = upsert(conn, again, n.normalise(again))
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert same_id == job_id and not created
    assert job["first_seen_at"].startswith("2026-01-01")
    assert job["status"] == "active" and job["expired_reason"] is None


def test_missing_salary_is_null(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    r = raw(description="Great team.", salary_text="Negotiable")
    f = Normaliser(conn, AppSettings()).normalise(r).fields
    assert f["salary_min"] is None and f["salary_annual_max"] is None
    assert f["salary_text"] == "Negotiable"
