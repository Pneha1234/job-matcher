"""The Jobs page query: filters, sort, paging, and the shape of a job card."""

import sqlite3
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.normalize.geo import load_geo, utc_offset_minutes
from app.normalize.regions import CITY_GROUPS, REGIONS
from app.settings_store import AppSettings
from app.util import iso, loads

APPLIED = ("applied", "interviewing", "offer", "rejected", "withdrawn")


class JobFilters(BaseModel):
    min_match: int = Field(0, ge=0, le=100)
    include_unscored: bool = True
    q: str = ""
    types: list[str] = []
    countries: list[str] = []
    regions: list[str] = []
    cities: list[str] = []  # city-group names such as "Kathmandu Valley"
    remote_eligible: bool = False  # include remote jobs open to the user's home country
    near_lat: float | None = Field(None, ge=-90, le=90)  # "near a city" radius search
    near_lon: float | None = Field(None, ge=-180, le=180)
    radius_km: int = Field(50, ge=1, le=2000)
    tz_overlap: int = Field(0, ge=0, le=8)  # hours of 9-to-5 overlap with your time zone
    location_unclear: bool = True
    salary_only: bool = False
    salary_min: int | None = None
    posted_days: int | None = None
    new_today: bool = False
    hide_applied: bool = False
    show_expired: bool = False
    show_hidden: bool = False
    visa: bool = False
    relocation: bool = False
    status: list[str] = []  # application statuses, e.g. ["saved"]
    sort: str = "match"
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


SCORE_JOIN = """
LEFT JOIN match_scores ms ON ms.id = (
    SELECT m.id FROM match_scores m WHERE m.job_id = j.id
    ORDER BY (m.profile_version_id = :active) DESC, m.scored_at DESC LIMIT 1)
LEFT JOIN profile_versions pv ON pv.id = ms.profile_version_id
LEFT JOIN applications a ON a.job_id = j.id
LEFT JOIN user_job_flags f ON f.job_id = j.id
"""


def _today_start() -> str:
    now = datetime.now(UTC)
    return iso(now.replace(hour=0, minute=0, second=0, microsecond=0))  # type: ignore[return-value]


def home_offset(settings: AppSettings) -> int | None:
    """UTC offset of where you live: your city if set, else your country's largest city."""
    geo = load_geo()
    if geo is None or not settings.home_country:
        return None
    candidates = []
    if settings.home_city:
        candidates = [c for c in geo.search(settings.home_city, 20)
                      if c.country == settings.home_country]  # fmt: skip
    if not candidates:
        candidates = sorted(
            (c for c in geo.by_id.values() if c.country == settings.home_country),
            key=lambda c: c.population,
            reverse=True,
        )
    return utc_offset_minutes(candidates[0].timezone) if candidates else None


def where_clause(flt: JobFilters, settings: AppSettings) -> tuple[str, dict]:
    clauses: list[str] = []
    args: dict = {}
    statuses = ["'active'"] + (["'expired'", "'stale'"] if flt.show_expired else [])
    clauses.append(f"j.status IN ({', '.join(statuses)})")
    clauses.append("j.duplicate_of IS NULL")
    if not flt.show_hidden:
        clauses.append("COALESCE(f.hidden, 0) = 0")
    if flt.min_match:
        cond = "ms.final_pct >= :min_match"
        if flt.include_unscored:
            cond = f"({cond} OR ms.id IS NULL OR ms.status = 'unscored')"
        clauses.append(cond)
        args["min_match"] = flt.min_match
    elif not flt.include_unscored:
        clauses.append("ms.status = 'scored'")
    if flt.q.strip():
        clauses.append(
            "(j.title LIKE :q OR j.company_name LIKE :q OR ms.matched_skills LIKE :q "
            "OR ms.missing_skills LIKE :q)"
        )
        args["q"] = f"%{flt.q.strip()}%"
    if flt.types:
        marks = ", ".join(f":t{i}" for i in range(len(flt.types)))
        clauses.append(f"j.job_type IN ({marks})")
        args.update({f"t{i}": t for i, t in enumerate(flt.types)})
    place_conds = []
    countries = set(flt.countries)
    for region in flt.regions:
        countries |= REGIONS.get(region, set())
    if countries:
        marks = ", ".join(f":c{i}" for i in range(len(countries)))
        args.update({f"c{i}": c for i, c in enumerate(sorted(countries))})
        place_conds.append(
            f"EXISTS (SELECT 1 FROM job_locations l WHERE l.job_id = j.id "
            f"AND l.country_code IN ({marks}))"
        )
    cities = set()
    for group in flt.cities:
        cities |= CITY_GROUPS.get(group, {group})
    if cities:
        marks = ", ".join(f":city{i}" for i in range(len(cities)))
        args.update({f"city{i}": c for i, c in enumerate(sorted(cities))})
        place_conds.append(
            f"EXISTS (SELECT 1 FROM job_locations l WHERE l.job_id = j.id "
            f"AND l.city IN ({marks}))"
        )
    if flt.remote_eligible and settings.home_country:
        home = settings.home_country
        regions = [r for r, cs in REGIONS.items() if home in cs]
        region_marks = ", ".join(f":rr{i}" for i in range(len(regions))) or "''"
        args.update({f"rr{i}": r for i, r in enumerate(regions)})
        args["home"] = home
        place_conds.append(
            "(json_extract(j.remote_eligibility, '$.remote') = 1 AND ("
            "json_extract(j.remote_eligibility, '$.worldwide') = 1 "
            "OR EXISTS (SELECT 1 FROM json_each(j.remote_eligibility, '$.countries') "
            "WHERE value = :home) "
            f"OR EXISTS (SELECT 1 FROM json_each(j.remote_eligibility, '$.regions') "
            f"WHERE value IN ({region_marks}))))"
        )
    if flt.near_lat is not None and flt.near_lon is not None:
        args.update(nlat=flt.near_lat, nlon=flt.near_lon, rkm=flt.radius_km)
        place_conds.append(
            "EXISTS (SELECT 1 FROM job_locations l WHERE l.job_id = j.id AND l.lat IS NOT NULL "
            "AND 6371 * acos(min(1, cos(radians(:nlat)) * cos(radians(l.lat)) * "
            "cos(radians(l.lon) - radians(:nlon)) + sin(radians(:nlat)) * sin(radians(l.lat))))"
            " <= :rkm)"
        )
    if place_conds and flt.location_unclear:
        place_conds.append(
            "NOT EXISTS (SELECT 1 FROM job_locations l WHERE l.job_id = j.id "
            "AND l.country_code IS NOT NULL) AND COALESCE(json_extract(j.remote_eligibility, "
            "'$.remote'), 0) = 0"
        )
    if place_conds:
        clauses.append("(" + " OR ".join(place_conds) + ")")
    home = home_offset(settings) if flt.tz_overlap else None
    if home is not None:
        # Overlap of two 9-to-5 days, in minutes, from the difference in UTC offsets.
        args.update(home_off=home, tz_need=flt.tz_overlap * 60)
        tz_cond = (
            "EXISTS (SELECT 1 FROM job_locations l WHERE l.job_id = j.id AND "
            "l.utc_offset_min IS NOT NULL AND 480 - abs(l.utc_offset_min - :home_off) >= :tz_need)"
        )
        if flt.location_unclear:
            tz_cond = (
                f"({tz_cond} OR NOT EXISTS (SELECT 1 FROM job_locations l WHERE l.job_id = j.id "
                "AND l.utc_offset_min IS NOT NULL))"
            )
        clauses.append(tz_cond)
    if flt.salary_only:
        clauses.append("j.salary_text IS NOT NULL")
    if flt.salary_min:
        clauses.append("j.salary_annual_max >= :salary_min")
        args["salary_min"] = flt.salary_min
    if flt.posted_days:
        clauses.append("COALESCE(j.posted_at, j.first_seen_at) >= :posted_after")
        args["posted_after"] = iso(datetime.now(UTC) - timedelta(days=flt.posted_days))
    if flt.new_today:
        clauses.append("j.first_seen_at >= :today")
        args["today"] = _today_start()
    if flt.hide_applied:
        clauses.append(f"COALESCE(a.status, '') NOT IN ({', '.join(repr(s) for s in APPLIED)})")
    if flt.status:
        marks = ", ".join(f":as{i}" for i in range(len(flt.status)))
        clauses.append(f"a.status IN ({marks})")
        args.update({f"as{i}": s for i, s in enumerate(flt.status)})
    if flt.visa:
        clauses.append("j.visa_sponsorship = 'yes'")
    if flt.relocation:
        clauses.append("j.relocation = 1")
    return " AND ".join(clauses), args


ORDER = {
    "match": "ms.final_pct IS NULL, ms.final_pct DESC, ms.similarity DESC, j.first_seen_at DESC",
    "new": "COALESCE(j.posted_at, j.first_seen_at) DESC",
    "salary": "j.salary_annual_max IS NULL, j.salary_annual_max DESC",
}


def list_jobs(conn: sqlite3.Connection, flt: JobFilters, settings: AppSettings, active: int | None):
    where, args = where_clause(flt, settings)
    args["active"] = active or -1
    total = conn.execute(
        f"SELECT COUNT(*) FROM jobs j {SCORE_JOIN} WHERE {where}", args
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT j.*, ms.final_pct, ms.status AS score_status, ms.error AS score_error, "
        f"ms.matched_skills, ms.missing_skills, ms.profile_version_id AS score_version, "
        f"pv.label AS score_label, a.id AS app_id, a.status AS app_status, a.applied_at, "
        f"COALESCE(f.hidden, 0) AS hidden FROM jobs j {SCORE_JOIN} WHERE {where} "
        f"ORDER BY {ORDER.get(flt.sort, ORDER['match'])} LIMIT :limit OFFSET :offset",
        {**args, "limit": flt.limit, "offset": flt.offset},
    ).fetchall()
    ids = [r["id"] for r in rows]
    locs = _by_job(conn, "SELECT job_id, raw, city, country_code FROM job_locations", ids)
    srcs = _by_job(
        conn, "SELECT job_id, source, url FROM job_sources WHERE status = 'listed'", ids, "AND"
    )
    return {"total": total, "items": [card(r, locs.get(r["id"], []), srcs.get(r["id"], []), active)
                                      for r in rows]}  # fmt: skip


def _by_job(conn, sql: str, ids: list[int], joiner: str = "WHERE") -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    if not ids:
        return out
    marks = ",".join("?" * len(ids))
    for r in conn.execute(f"{sql} {joiner} job_id IN ({marks})", ids):
        out.setdefault(r["job_id"], []).append(dict(r))
    return out


def location_label(locations: list[dict], remote: dict) -> str:
    places = []
    for loc in locations:
        label = loc.get("city") or loc.get("country_code") or None
        if label and label not in places:
            places.append(label)
    text = ", ".join(places[:2]) + (f" +{len(places) - 2}" if len(places) > 2 else "")
    if remote.get("remote"):
        scope = (
            "worldwide"
            if remote.get("worldwide")
            else ", ".join((remote.get("countries") or []) + (remote.get("regions") or [])[:3])
        )
        r = f"Remote ({scope})" if scope else "Remote (scope unclear)"
        return f"{r} · {text}" if text else r
    return text or "Location unclear"


def card(r: sqlite3.Row, locations: list[dict], sources: list[dict], active: int | None) -> dict:
    remote = loads(r["remote_eligibility"], {}) or {}
    return {
        "id": r["id"],
        "title": r["title"],
        "company": r["company_name"],
        "location": location_label(locations, remote),
        "countries": sorted({x["country_code"] for x in locations if x["country_code"]}),
        "work_mode": r["work_mode"],
        "job_type": r["job_type"],
        "salary_text": r["salary_text"],
        "salary_annual_min": r["salary_annual_min"],
        "salary_annual_max": r["salary_annual_max"],
        "posted_at": r["posted_at"] or r["first_seen_at"],
        "first_seen_at": r["first_seen_at"],
        "last_seen_at": r["last_seen_at"],
        "status": r["status"],
        "expired_reason": r["expired_reason"],
        "visa_sponsorship": r["visa_sponsorship"],
        "relocation": bool(r["relocation"]),
        "sources": [s["source"] for s in sources],
        "match": {
            "pct": r["final_pct"],
            "status": r["score_status"] or "pending",
            "error": r["score_error"],
            "stale_version": bool(r["score_version"] and r["score_version"] != active),
            "version_label": r["score_label"],
            "matched": loads(r["matched_skills"], []) or [],
            "missing": loads(r["missing_skills"], []) or [],
        },
        "application": (
            {"id": r["app_id"], "status": r["app_status"], "applied_at": r["applied_at"]}
            if r["app_id"] and r["app_status"] != "archived"
            else None
        ),
        "hidden": bool(r["hidden"]),
    }


def job_map(conn: sqlite3.Connection, flt: JobFilters, settings: AppSettings, active: int | None):
    """Matching jobs grouped by city for the map: one point per place, best matches first."""
    where, args = where_clause(flt, settings)
    args["active"] = active or -1
    rows = conn.execute(
        f"SELECT l.city, l.country_code, l.lat, l.lon, j.id, j.title, j.company_name, "
        f"ms.final_pct FROM jobs j {SCORE_JOIN} JOIN job_locations l ON l.job_id = j.id "
        f"WHERE {where} AND l.lat IS NOT NULL AND l.city IS NOT NULL "
        f"ORDER BY ms.final_pct IS NULL, ms.final_pct DESC LIMIT 20000",
        args,
    ).fetchall()
    points: dict[tuple, dict] = {}
    for r in rows:
        key = (r["city"], r["country_code"])
        point = points.setdefault(
            key,
            {"city": r["city"], "country": r["country_code"], "lat": r["lat"],
             "lon": r["lon"], "count": 0, "best": None, "jobs": []},  # fmt: skip
        )
        point["count"] += 1
        if r["final_pct"] is not None and (point["best"] is None or r["final_pct"] > point["best"]):
            point["best"] = r["final_pct"]
        if len(point["jobs"]) < 5:
            point["jobs"].append(
                {"id": r["id"], "title": r["title"], "company": r["company_name"],
                 "pct": r["final_pct"]}  # fmt: skip
            )
    return sorted(points.values(), key=lambda p: -p["count"])
