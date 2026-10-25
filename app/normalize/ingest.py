"""RawJob -> normalised row, deduplicated on a canonical key, upserted with its sources
and locations. A re-post under a new id keeps the original first_seen_at."""

import re
import sqlite3
from dataclasses import dataclass

from app.normalize import classify, fx
from app.normalize.geo import Geo, Resolution, load_geo, utc_offset_minutes
from app.normalize.salary import Salary, from_parts, parse_salary
from app.settings_store import AppSettings
from app.sources.base import RawJob
from app.util import ascii_fold, dumps, iso, now_iso, slug

MAX_DESCRIPTION = 20_000
COMPANY_SUFFIX = re.compile(
    r"\b(inc|llc|l\.l\.c|ltd|limited|gmbh|ag|b\.?v|n\.?v|plc|pvt|private|corp|corporation|co|"
    r"s\.?a|sas|srl|s\.?l|ab|a/s|as|oy|k\.?k|pte|pty|se|group|holdings?)\b\.?",
    re.I,
)
TITLE_NOISE = re.compile(
    r"\((?:[mwfdxh]\s*/\s*[mwfdxh](?:\s*/\s*[mwfdxh])?|all genders?|gn|w\*m\*d)\)|"
    r"\b[mwfdh]\s*/\s*[mwfdh]\s*/\s*[mwfdhx]\b|[-–|]\s*(remote|hybrid|onsite)\s*$",
    re.I,
)
COUNTRY_CURRENCY = {"NP": "NPR", "IN": "INR", "GB": "GBP", "SE": "SEK", "NO": "NOK", "CH": "CHF"}
SALARY_SENTENCE = re.compile(
    r"[^.\n]{0,120}(salary|compensation|pay range|base pay|ctc|remuneration|gehalt)"
    r"[^.\n]{0,160}?[€$£₹]\s?\d[^.\n]{0,80}",
    re.I,
)


def company_key(name: str) -> str:
    return slug(COMPANY_SUFFIX.sub(" ", ascii_fold(name)))


def title_key(title: str) -> str:
    return slug(TITLE_NOISE.sub(" ", title))


def canonical_key(company: str, title: str) -> str:
    """Same company + same normalised title = one job, wherever and however often posted."""
    return f"{company_key(company)}|{title_key(title)}"


def clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", TITLE_NOISE.sub(" ", title)).strip(" -–|")


@dataclass
class Normalised:
    fields: dict
    resolution: Resolution
    salary: Salary | None


class Normaliser:
    def __init__(self, conn: sqlite3.Connection, settings: AppSettings, geo: Geo | None = None):
        self.conn = conn
        self.settings = settings
        self.geo = geo if geo is not None else load_geo()
        self.rates = fx.rates(conn)
        self._offices: dict[str, set[str]] = {}

    def offices(self, company: str) -> set[str]:
        key = company_key(company)
        if key not in self._offices:
            rows = self.conn.execute(
                "SELECT DISTINCT l.country_code FROM job_locations l "
                "JOIN jobs j ON j.id = l.job_id "
                "WHERE j.company_name = ? AND l.country_code IS NOT NULL",
                (company,),
            ).fetchall()
            self._offices[key] = {r[0] for r in rows}
        return self._offices[key]

    def resolve(self, raw: RawJob) -> Resolution:
        res = Resolution()
        if self.geo is None:
            from app.normalize.geo import Location

            res.locations = [Location(raw=s) for s in raw.locations]
            res.remote = bool(raw.remote)
            return res
        offices = self.offices(raw.company)
        for text in raw.locations:
            r = self.geo.resolve(text, raw.country_hint, offices)
            res.locations += r.locations
            res.remote |= r.remote
            res.worldwide |= r.worldwide
            res.remote_countries |= r.remote_countries
            res.remote_regions |= r.remote_regions
        for text in raw.remote_scope:
            r = self.geo.resolve(f"Remote ({text})")
            res.worldwide |= r.worldwide
            res.remote_countries |= r.remote_countries
            res.remote_regions |= r.remote_regions
        if raw.remote:
            res.remote = True
        return res

    def salary(self, raw: RawJob, country: str | None) -> tuple[Salary | None, str | None]:
        hint = raw.salary_currency or COUNTRY_CURRENCY.get(country or "")
        if raw.salary_min is not None or raw.salary_max is not None:
            sal = from_parts(raw.salary_min, raw.salary_max, hint, raw.salary_period)
            return sal, raw.salary_text or _describe(sal)
        if raw.salary_text:
            return parse_salary(raw.salary_text, hint), raw.salary_text
        if m := SALARY_SENTENCE.search(raw.description[:12000]):
            text = m.group(0).strip()
            sal = parse_salary(text, hint)
            if sal and sal.currency:
                return sal, text
        return None, None

    def normalise(self, raw: RawJob) -> Normalised:
        res = self.resolve(raw)
        desc = raw.description[:MAX_DESCRIPTION]
        head = desc[:4000]
        first_country = next((loc.country_code for loc in res.locations if loc.country_code), None)
        sal, sal_text = self.salary(raw, raw.country_hint or first_country)
        annual_min = annual_max = None
        if sal:
            lo, hi = sal.annual()
            annual_min = fx.convert(lo, sal.currency, self.settings.currency, self.rates)
            annual_max = fx.convert(hi, sal.currency, self.settings.currency, self.rates)
        remote = {
            "remote": res.remote,
            "worldwide": res.worldwide,
            "countries": sorted(res.remote_countries),
            "regions": sorted(res.remote_regions),
        }
        extra = dict(raw.extra)
        extra.update(classify.india_fields(head))
        fields = {
            "title": clean_title(raw.title) or raw.title,
            "company_name": raw.company.strip(),
            "description": desc,
            "job_type": classify.job_type(raw.job_type_raw, raw.title, head[:600]),
            "work_mode": classify.work_mode(res.remote, raw.title, *raw.locations, head),
            "remote_eligibility": dumps(remote),
            "visa_sponsorship": classify.visa(desc),
            "relocation": classify.relocation(desc),
            "language": raw.language_hint
            or classify.posting_language(desc, "ne" if raw.country_hint == "NP" else "hi"),
            "language_reqs": dumps(classify.language_requirements(desc)),
            "salary_text": sal_text,
            "salary_min": sal.min if sal else None,
            "salary_max": sal.max if sal else None,
            "salary_currency": sal.currency if sal else None,
            "salary_period": sal.period if sal else None,
            "salary_annual_min": round(annual_min) if annual_min else None,
            "salary_annual_max": round(annual_max) if annual_max else None,
            "extra": dumps(extra),
            "posted_at": iso(raw.posted_at),
            "valid_through": iso(raw.valid_through),
        }
        return Normalised(fields=fields, resolution=res, salary=sal)


def _describe(sal: Salary | None) -> str | None:
    if not sal:
        return None
    lo = f"{sal.min:,.0f}" if sal.min else ""
    hi = f"{sal.max:,.0f}" if sal.max and sal.max != sal.min else ""
    amount = "–".join(x for x in (lo, hi) if x)
    period = f" per {sal.period}" if sal.period else ""
    return f"{sal.currency or ''} {amount}{period}".strip()


# Fields an update may fill in when the stored job lacks them.
FILLABLE = (
    "job_type", "work_mode", "visa_sponsorship", "relocation", "language", "salary_text",
    "salary_min", "salary_max", "salary_currency", "salary_period", "salary_annual_min",
    "salary_annual_max", "posted_at", "valid_through",
)  # fmt: skip


def upsert(conn: sqlite3.Connection, raw: RawJob, norm: Normalised) -> tuple[int, bool]:
    """Returns (job_id, created). Call inside a transaction."""
    now = now_iso()
    key = canonical_key(raw.company, raw.title)
    f = norm.fields
    company_id = None
    if raw.company_board:
        row = conn.execute(
            "SELECT id FROM companies WHERE platform = ? AND slug = ?", raw.company_board
        ).fetchone()
        company_id = row["id"] if row else None

    existing = conn.execute(
        "SELECT COALESCE(d.id, j.id) AS id, COALESCE(d.description, j.description) AS description "
        "FROM jobs j LEFT JOIN jobs d ON d.id = j.duplicate_of WHERE j.canonical_key = ?",
        (key,),
    ).fetchone()
    if existing:
        job_id, created = existing["id"], False
        sets = ["last_seen_at = ?", "updated_at = ?"]
        args: list = [now, now]
        # A job seen again is active again; why it had expired is no longer true.
        sets.append("status = 'active'")
        sets.append("expired_reason = NULL")
        if len(f["description"]) > len(existing["description"] or ""):
            sets.append("description = ?")
            args.append(f["description"])
        for col in FILLABLE:
            if f[col] is not None:
                sets.append(f"{col} = COALESCE({col}, ?)")
                args.append(f[col])
        if company_id:
            sets.append("company_id = COALESCE(company_id, ?)")
            args.append(company_id)
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", (*args, job_id))
    else:
        cols = ["canonical_key", "company_id", *f.keys(), "first_seen_at", "last_seen_at"]
        vals = [key, company_id, *f.values(), now, now]
        cur = conn.execute(
            f"INSERT INTO jobs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals
        )
        job_id, created = cur.lastrowid, True

    conn.execute(
        "INSERT INTO job_sources (job_id, source, url, source_job_id, scope, first_seen_at, "
        "last_seen_at, missed_runs, status) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'listed') "
        "ON CONFLICT (source, source_job_id) DO UPDATE SET job_id = excluded.job_id, "
        "url = excluded.url, scope = excluded.scope, last_seen_at = excluded.last_seen_at, "
        "missed_runs = 0, status = 'listed'",
        (job_id, raw.source, raw.url, raw.source_job_id, raw.scope, now, now),
    )
    known = {
        r["raw"] for r in conn.execute("SELECT raw FROM job_locations WHERE job_id = ?", (job_id,))
    }
    for loc in norm.resolution.locations:
        if loc.raw in known:
            continue
        known.add(loc.raw)
        conn.execute(
            "INSERT INTO job_locations (job_id, raw, city, region, country_code, lat, lon, "
            "geonames_id, resolved, timezone, utc_offset_min) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                loc.raw,
                loc.city,
                loc.region,
                loc.country_code,
                loc.lat,
                loc.lon,
                loc.geonames_id,
                int(loc.resolved),
                loc.timezone,
                utc_offset_minutes(loc.timezone),
            ),
        )
    return job_id, created


def backfill_timezones(conn: sqlite3.Connection, geo: Geo | None = None) -> int:
    """Give locations stored before time zones were tracked their zone and offset."""
    geo = geo if geo is not None else load_geo()
    if geo is None:
        return 0
    rows = conn.execute(
        "SELECT id, geonames_id FROM job_locations WHERE geonames_id IS NOT NULL "
        "AND timezone IS NULL"
    ).fetchall()
    with conn:
        for r in rows:
            city = geo.by_id.get(r["geonames_id"])
            if city and city.timezone:
                conn.execute(
                    "UPDATE job_locations SET timezone = ?, utc_offset_min = ? WHERE id = ?",
                    (city.timezone, utc_offset_minutes(city.timezone), r["id"]),
                )
    return len(rows)
