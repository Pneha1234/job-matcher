"""Public job APIs and feeds (no key, or a free key). Attribution is kept in each job's
source link, as RemoteOK and Arbeitnow ask."""

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from app.normalize.classify import html_to_text
from app.sources.ats import _dt
from app.sources.base import FetchContext, FetchResult, RawJob, Source


class FeedSource(Source):
    kind = "feed"
    group = "feeds"
    daily_budget = 60


class Remotive(FeedSource):
    name = "remotive"
    label = "Remotive"
    via = "Public API"

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        data = await ctx.http.get_json("https://remotive.com/api/remote-jobs")
        jobs = [
            RawJob(
                source=self.name,
                source_job_id=str(j["id"]),
                url=j["url"],
                title=j["title"],
                company=j["company_name"],
                description=html_to_text(j.get("description")),
                remote=True,
                remote_scope=[j.get("candidate_required_location") or ""],
                job_type_raw=j.get("job_type"),
                salary_text=j.get("salary") or None,
                salary_currency="USD" if j.get("salary") and "$" not in j["salary"] else None,
                posted_at=_dt(j.get("publication_date")),
                scope=self.name,
            )
            for j in data.get("jobs", [])
        ]
        return FetchResult(jobs=jobs, complete_scopes={self.name}, requests=ctx.http.requests)


class RemoteOK(FeedSource):
    name = "remoteok"
    label = "RemoteOK"
    via = "Public API"

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        data = await ctx.http.get_json("https://remoteok.com/api")
        jobs = []
        for j in data[1:]:  # the first element is the legal notice
            if not j.get("position"):
                continue
            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=str(j["id"]),
                    url=j["url"],
                    title=j["position"],
                    company=j.get("company") or "Unknown",
                    description=html_to_text(j.get("description")),
                    remote=True,
                    remote_scope=[j.get("location") or ""],
                    salary_min=j.get("salary_min") or None,
                    salary_max=j.get("salary_max") or None,
                    salary_currency="USD" if j.get("salary_min") else None,
                    salary_period="year" if j.get("salary_min") else None,
                    posted_at=_dt(j.get("date")),
                    scope=self.name,
                    extra={"tags": j.get("tags") or []},
                )
            )
        return FetchResult(jobs=jobs, complete_scopes={self.name}, requests=ctx.http.requests)


class Arbeitnow(FeedSource):
    name = "arbeitnow"
    label = "Arbeitnow"
    via = "Public API"
    PAGES = 5

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        jobs = []
        for page in range(1, self.PAGES + 1):
            data = await ctx.http.get_json(
                "https://www.arbeitnow.com/api/job-board-api", params={"page": page}
            )
            for j in data.get("data", []):
                jobs.append(
                    RawJob(
                        source=self.name,
                        source_job_id=j["slug"],
                        url=j["url"],
                        title=j["title"],
                        company=j["company_name"],
                        description=html_to_text(j.get("description")),
                        locations=[j.get("location") or ""] if j.get("location") else [],
                        remote=bool(j.get("remote")) or None,
                        job_type_raw=" ".join(j.get("job_types") or []) or None,
                        posted_at=_dt(j.get("created_at")),
                        country_hint="DE" if not j.get("remote") else None,
                    )
                )
            if not (data.get("links") or {}).get("next"):
                break
        # Paginated and capped, so never a complete listing.
        return FetchResult(jobs=jobs, requests=ctx.http.requests)


class Himalayas(FeedSource):
    name = "himalayas"
    label = "Himalayas"
    via = "Public API"
    PAGES = 10

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        jobs = []
        for page in range(self.PAGES):
            data = await ctx.http.get_json(
                "https://himalayas.app/jobs/api", params={"limit": 20, "offset": page * 20}
            )
            batch = data.get("jobs", [])
            for j in batch:
                jobs.append(
                    RawJob(
                        source=self.name,
                        source_job_id=j["guid"],
                        url=j["applicationLink"],
                        title=j["title"],
                        company=j["companyName"],
                        description=html_to_text(j.get("description")),
                        remote=True,
                        remote_scope=j.get("locationRestrictions") or ["Worldwide"],
                        job_type_raw=j.get("employmentType"),
                        salary_min=j.get("minSalary"),
                        salary_max=j.get("maxSalary"),
                        salary_currency=j.get("currency"),
                        salary_period={"annual": "year", "monthly": "month", "hourly": "hour"}.get(
                            j.get("salaryPeriod") or ""
                        ),
                        posted_at=_dt(j.get("pubDate")),
                        valid_through=_dt(j.get("expiryDate")),
                    )
                )
            if len(batch) < 20:
                break
        return FetchResult(jobs=jobs, requests=ctx.http.requests)


class Jobicy(FeedSource):
    name = "jobicy"
    label = "Jobicy"
    via = "Public API"

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        data = await ctx.http.get_json(
            "https://jobicy.com/api/v2/remote-jobs", params={"count": 100}
        )
        jobs = [
            RawJob(
                source=self.name,
                source_job_id=str(j["id"]),
                url=j["url"],
                title=html_to_text(j["jobTitle"]),
                company=j["companyName"],
                description=html_to_text(j.get("jobDescription")),
                remote=True,
                remote_scope=[s.strip() for s in (j.get("jobGeo") or "").split(",") if s.strip()],
                job_type_raw=" ".join(j.get("jobType") or []) or None,
                salary_min=j.get("salaryMin"),
                salary_max=j.get("salaryMax"),
                salary_currency=j.get("salaryCurrency"),
                salary_period=j.get("salaryPeriod"),
                posted_at=_dt(j.get("pubDate")),
            )
            for j in data.get("jobs", [])
        ]
        return FetchResult(jobs=jobs, requests=ctx.http.requests)


class WeWorkRemotely(FeedSource):
    name = "weworkremotely"
    label = "We Work Remotely"
    via = "RSS"

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        text = await ctx.http.get_text("https://weworkremotely.com/remote-jobs.rss")
        root = ET.fromstring(text)
        jobs = []
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            company, _, role = title.partition(":")
            link = item.findtext("link") or ""
            region = item.findtext("region") or ""
            pub = item.findtext("pubDate")
            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=item.findtext("guid") or link,
                    url=link,
                    title=(role or title).strip(),
                    company=company.strip() if role else "Unknown",
                    description=html_to_text(item.findtext("description")),
                    remote=True,
                    remote_scope=[region] if region else [],
                    job_type_raw=item.findtext("type"),
                    posted_at=parsedate_to_datetime(pub) if pub else None,
                    scope=self.name,
                )
            )
        return FetchResult(jobs=jobs, complete_scopes={self.name}, requests=ctx.http.requests)


class HackerNews(FeedSource):
    """The monthly "Ask HN: Who is hiring?" thread via the Algolia HN API.

    Top-level comments conventionally start "Company | Role | Location | ...". Comments
    that don't follow it are skipped rather than guessed at.
    """

    name = "hn_whos_hiring"
    label = "Hacker News Who's Hiring"
    via = "Algolia HN API"
    daily_budget = 10

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        search = await ctx.http.get_json(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "story,author_whoishiring", "query": "who is hiring"},
        )
        story = next(
            (h for h in search.get("hits", []) if "who is hiring" in h.get("title", "").lower()),
            None,
        )
        if not story:
            return FetchResult(errors=["No Who's Hiring thread found"])
        thread = await ctx.http.get_json(
            f"https://hn.algolia.com/api/v1/items/{story['objectID']}", cache_ttl_s=6 * 3600
        )
        jobs = []
        posted = _dt(story.get("created_at"))
        for c in thread.get("children", []):
            text = html_to_text(c.get("text"))
            job = parse_hn_comment(text)
            if not job:
                continue
            company, role, locations, remote = job
            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=str(c["id"]),
                    url=f"https://news.ycombinator.com/item?id={c['id']}",
                    title=role,
                    company=company,
                    description=text,
                    locations=locations,
                    remote=remote or None,
                    posted_at=_dt(c.get("created_at")) or posted,
                    scope=str(story["objectID"]),
                )
            )
        return FetchResult(
            jobs=jobs, complete_scopes={str(story["objectID"])}, requests=ctx.http.requests
        )


ROLE_WORDS = re.compile(
    r"engineer|developer|designer|scientist|manager|analyst|lead|architect|devops|sre|"
    r"programmer|researcher|director|head of|product|marketing|sales|recruiter|founding",
    re.I,
)


def parse_hn_comment(text: str):
    first = text.split("\n", 1)[0]
    parts = [p.strip() for p in first.split("|") if p.strip()]
    if len(parts) < 3:
        return None
    company = re.sub(r"\s*\(.*?\)\s*$", "", parts[0]).strip()
    role = next((p for p in parts[1:] if ROLE_WORDS.search(p)), None)
    if not company or not role or len(company) > 60:
        return None
    remote = any(re.search(r"\bremote\b", p, re.I) for p in parts)
    locations = [
        p
        for p in parts[1:]
        if p is not role
        and not re.search(r"\$|€|£|full[- ]?time|part[- ]?time|contract|visa|https?://", p, re.I)
        and len(p) < 80
    ][:3]
    return company, role[:120], locations, remote


class JobTechSweden(FeedSource):
    """Arbetsförmedlingen's open JobSearch API; queried with the user's saved searches."""

    name = "jobtech_se"
    label = "JobTech (Sweden)"
    via = "Open API"
    needs_searches = True

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        jobs = []
        for search in ctx.searches:
            data = await ctx.http.get_json(
                "https://jobsearch.api.jobtechdev.se/search",
                params={"q": search["query"], "limit": 100},
            )
            for h in data.get("hits", []):
                addr = h.get("workplace_address") or {}
                loc = ", ".join(filter(None, [addr.get("municipality") or addr.get("city"),
                                              "Sweden"]))  # fmt: skip
                jobs.append(
                    RawJob(
                        source=self.name,
                        source_job_id=str(h["id"]),
                        url=h.get("webpage_url") or "",
                        title=h["headline"],
                        company=(h.get("employer") or {}).get("name") or "Unknown",
                        description=(h.get("description") or {}).get("text") or "",
                        locations=[loc],
                        job_type_raw=(h.get("working_hours_type") or {}).get("label"),
                        salary_text=h.get("salary_description"),
                        posted_at=_dt(h.get("publication_date")),
                        valid_through=_dt(h.get("application_deadline")),
                        country_hint="SE",
                        language_hint=None,
                    )
                )
        return FetchResult(jobs=jobs, requests=ctx.http.requests)


FEED_SOURCES: list[type[FeedSource]] = [
    Remotive, RemoteOK, Arbeitnow, Himalayas, Jobicy, WeWorkRemotely, HackerNews, JobTechSweden,
]  # fmt: skip
