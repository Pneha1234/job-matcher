"""Job boards through JobSpy (open source, no key): logged-out guest pages only.

Each saved search is one request group; searches are spaced 3–8 s apart and capped by the
daily budget. A block (403/429/CAPTCHA) pauses the source instead of retrying.
"""

import asyncio
import math
import random
from typing import ClassVar

from app.normalize.geo import load_geo
from app.sources.base import FetchContext, FetchResult, RawJob, Source, SourceBlocked
from app.util import ascii_fold

RESULTS_PER_SEARCH = 50
HOURS_OLD = 72


def indeed_country(code: str | None):
    """ISO-2 -> JobSpy's Country, or None when Indeed doesn't cover it (e.g. Nepal)."""
    from jobspy.model import Country

    if not code:
        return None
    special = {"US": "USA", "GB": "UK", "AE": "UNITEDARABEMIRATES", "KR": "SOUTHKOREA",
               "CZ": "CZECHREPUBLIC", "NZ": "NEWZEALAND", "ZA": "SOUTHAFRICA",
               "SA": "SAUDIARABIA", "HK": "HONGKONG", "CR": "COSTARICA"}  # fmt: skip
    geo = load_geo()
    name = special.get(code) or (
        ascii_fold(geo.country_name(code) or "").removeprefix("the ").replace(" ", "").upper()
        if geo
        else ""
    )
    return Country.__members__.get(name)


def _scrape(**kwargs):
    from jobspy import scrape_jobs

    return scrape_jobs(**kwargs)


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


class JobSpySource(Source):
    kind = "scrape"
    group = "jobspy"
    daily_budget = 40  # searches per day
    needs_searches = True
    site: ClassVar[str]
    uses_country: ClassVar[bool] = False

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        result = FetchResult()
        geo = load_geo()
        for i, search in enumerate(ctx.searches):
            if ctx.http.used_today() >= ctx.http.budget:
                result.errors.append("Daily search budget reached")
                break
            if i:
                await asyncio.sleep(random.uniform(*ctx.http.delay))
            location = search.get("location") or None
            country = None
            if location and geo:
                res = geo.resolve(location)
                country = next((x.country_code for x in res.locations if x.country_code), None)
            country = country or (ctx.target_countries[0] if ctx.target_countries else None)
            kwargs = dict(
                site_name=[self.site],
                search_term=search["query"],
                location=location,
                results_wanted=RESULTS_PER_SEARCH,
                hours_old=HOURS_OLD,
                description_format="markdown",
                verbose=0,
            )
            if self.uses_country:
                ic = indeed_country(country)
                if ic is None:
                    result.errors.append(
                        f"'{search['query']}': {self.label} doesn't cover {country}"
                    )
                    continue
                kwargs["country_indeed"] = ic
            ctx.http._spend()
            ctx.http.requests += 1
            df = await asyncio.to_thread(_scrape, **kwargs)
            errors = (getattr(df, "attrs", {}) or {}).get("errors", {})
            for site, err in errors.items():
                text = str(err)
                if any(m in text.lower() for m in ("403", "429", "captcha", "blocked", "rate")):
                    raise SourceBlocked(f"{self.label}: {text[:200]}")
                result.errors.append(f"{site}: {text[:200]}")
            for row in df.to_dict("records"):
                job = self.to_raw(row, country)
                if job:
                    result.jobs.append(job)
        result.requests = ctx.http.requests
        return result

    def to_raw(self, row: dict, country: str | None) -> RawJob | None:
        row = {k: _clean(v) for k, v in row.items()}
        if not row.get("title") or not row.get("job_url"):
            return None
        loc = row.get("location") or {}
        if isinstance(loc, dict):
            country_text = loc.get("country")
            if country_text is not None and not isinstance(country_text, str):
                country_text = getattr(country_text, "value", str(country_text)).split(",")[0]
            loc_text = ", ".join(x for x in (loc.get("city"), loc.get("state"), country_text) if x)
        else:
            loc_text = str(loc)
        types = row.get("job_type") or []
        type_text = " ".join(getattr(t, "value", [str(t)])[0] for t in types) if types else None
        interval = row.get("interval")
        return RawJob(
            source=self.name,
            source_job_id=str(row.get("id") or row["job_url"]),
            url=row.get("job_url_direct") or row["job_url"],
            title=row["title"],
            company=row.get("company") or "Unknown",
            description=row.get("description") or "",
            locations=[loc_text] if loc_text else [],
            remote=row.get("is_remote") or None,
            job_type_raw=type_text,
            salary_min=row.get("min_amount"),
            salary_max=row.get("max_amount"),
            salary_currency=row.get("currency"),
            salary_period=getattr(interval, "value", interval),
            posted_at=row.get("date_posted"),
            country_hint=country,
            extra={"listing_url": row["job_url"]},
        )


class LinkedInGuest(JobSpySource):
    name = "jobspy_linkedin"
    label = "LinkedIn (guest)"
    via = "JobSpy"
    site = "linkedin"
    daily_budget = 20


class Indeed(JobSpySource):
    name = "jobspy_indeed"
    label = "Indeed"
    via = "JobSpy"
    site = "indeed"
    uses_country = True


class Glassdoor(JobSpySource):
    name = "jobspy_glassdoor"
    label = "Glassdoor"
    via = "JobSpy"
    site = "glassdoor"
    uses_country = True
    daily_budget = 20


class GoogleJobs(JobSpySource):
    name = "jobspy_google"
    label = "Google Jobs"
    via = "JobSpy"
    site = "google"


class Naukri(JobSpySource):
    name = "jobspy_naukri"
    label = "Naukri"
    via = "JobSpy"
    site = "naukri"
    daily_budget = 20


JOBSPY_SOURCES = [LinkedInGuest, Indeed, Glassdoor, GoogleJobs, Naukri]
