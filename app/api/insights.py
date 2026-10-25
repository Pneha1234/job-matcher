"""Insights: headline stats, missing skills, funnel, matches per day, salary by place,
best sources. Everything is computed from your own data."""

import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from app.api.deps import DbDep
from app.profile import store
from app.settings_store import load
from app.util import days_ago, loads

router = APIRouter(tags=["insights"])
TOP = 200


@router.get("/insights")
async def insights(db: DbDep):
    active = store.active(db)
    settings = load(db)
    vid = active["id"] if active else -1
    scored = db.execute(
        "SELECT j.id, j.first_seen_at, ms.final_pct, ms.missing_skills FROM match_scores ms "
        "JOIN jobs j ON j.id = ms.job_id WHERE ms.profile_version_id = ? "
        "AND ms.status = 'scored' AND j.status = 'active' AND j.duplicate_of IS NULL "
        "ORDER BY ms.final_pct DESC",
        (vid,),
    ).fetchall()
    top = scored[:TOP]
    gaps: Counter[str] = Counter()
    names: dict[str, str] = {}  # "typescript" -> "TypeScript", the first spelling seen
    for r in top:
        skills = {s.strip(): s.strip().lower() for s in loads(r["missing_skills"], []) or []}
        for shown, key in skills.items():
            names.setdefault(key, shown)
        gaps.update(set(skills.values()))
    # Of applications that got past "saved", how many reached an interview or offer.
    applied_ever = db.execute(
        "SELECT COUNT(DISTINCT application_id) FROM application_events WHERE to_status IN "
        "('applied', 'interviewing', 'offer', 'rejected')"
    ).fetchone()[0]
    responded = db.execute(
        "SELECT COUNT(DISTINCT application_id) FROM application_events "
        "WHERE to_status IN ('interviewing', 'offer')"
    ).fetchone()[0]

    def reached(status: str) -> int:
        return db.execute(
            "SELECT COUNT(DISTINCT application_id) FROM application_events "
            "WHERE to_status = ? AND at >= ?",
            (status, days_ago(30)),
        ).fetchone()[0]

    since = days_ago(30)
    found_80 = sum(1 for r in scored if r["final_pct"] >= 80 and r["first_seen_at"] >= since)
    today = datetime.now(UTC).date()
    per_day = Counter(r["first_seen_at"][:10] for r in scored if r["final_pct"] >= 80)
    days = [(today - timedelta(days=13 - i)).isoformat() for i in range(14)]

    salary_rows = db.execute(
        "SELECT COALESCE(l.city, l.country_code) AS place, j.salary_annual_min AS lo, "
        "j.salary_annual_max AS hi FROM jobs j JOIN job_locations l ON l.job_id = j.id "
        "WHERE j.status = 'active' AND j.duplicate_of IS NULL AND j.salary_annual_max IS NOT NULL "
        "AND "
        "COALESCE(l.city, l.country_code) IS NOT NULL"
    ).fetchall()
    by_place: dict[str, list] = {}
    for r in salary_rows:
        by_place.setdefault(r["place"], []).append((r["lo"] or r["hi"], r["hi"]))
    salary = [
        {
            "place": place,
            "jobs": len(vals),
            "low": round(statistics.median(v[0] for v in vals)),
            "high": round(statistics.median(v[1] for v in vals)),
        }
        for place, vals in sorted(by_place.items(), key=lambda kv: -len(kv[1]))[:6]
    ]
    best = db.execute(
        "SELECT s.source, COUNT(DISTINCT s.job_id) AS n FROM job_sources s "
        "JOIN match_scores ms ON ms.job_id = s.job_id AND ms.profile_version_id = ? "
        "JOIN jobs j ON j.id = s.job_id WHERE ms.final_pct >= 80 AND j.status = 'active' "
        "GROUP BY s.source ORDER BY n DESC LIMIT 6",
        (vid,),
    ).fetchall()
    return {
        "has_profile": bool(active),
        "currency": settings.currency,
        "stats": {
            "active_matches": sum(1 for r in scored if r["final_pct"] >= 60),
            "matches_80": sum(1 for r in scored if r["final_pct"] >= 80),
            "applied_30d": reached("applied"),
            "response_rate": round(100 * responded / applied_ever) if applied_ever else None,
        },
        "missing_skills": (
            [
                {"skill": names[s], "share": round(100 * n / len(top))}
                for s, n in gaps.most_common(8)
            ]
            if top
            else []
        ),
        "top_count": len(top),
        "funnel": [
            {"label": "Found (80%+)", "value": found_80},
            {"label": "Saved", "value": reached("saved")},
            {"label": "Applied", "value": reached("applied")},
            {"label": "Interviewing", "value": reached("interviewing")},
            {"label": "Offer", "value": reached("offer")},
        ],
        "per_day": [{"day": d, "count": per_day.get(d, 0)} for d in days],
        "salary_by_place": salary,
        "best_sources": [{"source": r["source"], "jobs": r["n"]} for r in best],
    }
