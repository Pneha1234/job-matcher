"""Company job boards with public endpoints. One board = one complete listing (scope), so
a job missing from its board on two runs in a row expires."""

import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from app.normalize.classify import html_to_text
from app.sources.base import FetchContext, FetchResult, NotFound, RawJob, Source

# Boards crawled per run; the least recently crawled go first, so a long list rotates.
BOARDS_PER_RUN = 120


def _dt(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=UTC)
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" UTC", "+00:00"))
    except ValueError:
        # "2026-10-27 11:59 p.m." and similar: the date part is still reliable.
        if not re.match(r"\d{4}-\d{2}-\d{2}", text):
            return None
        dt = datetime.fromisoformat(text[:10])
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class BoardSource(Source):
    """Shared loop: each company row is fetched, parsed, and marked crawled or dead."""

    kind = "ats"
    group = "ats"
    daily_budget = 600

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        result = FetchResult()
        boards = sorted(ctx.companies, key=lambda c: c["last_crawled_at"] or "")
        for company in boards[: ctx.limit or BOARDS_PER_RUN]:
            slug = company["slug"]
            try:
                jobs = await self.board(ctx, slug, company["name"])
            except NotFound:
                _mark_company(ctx, company["id"], "dead")
                result.errors.append(f"{slug}: board not found")
                continue
            except (ValueError, KeyError, ET.ParseError) as e:
                result.errors.append(f"{slug}: unexpected response ({e.__class__.__name__})")
                continue
            for job in jobs:
                job.scope = slug
                job.company_board = (self.platform, slug)
            result.jobs += jobs
            result.complete_scopes.add(slug)
            _mark_company(ctx, company["id"], "active")
        result.requests = ctx.http.requests
        return result

    async def board(self, ctx: FetchContext, slug: str, company: str) -> list[RawJob]:
        raise NotImplementedError


def _mark_company(ctx: FetchContext, company_id: int, status: str) -> None:
    from app.util import now_iso

    with ctx.conn:
        ctx.conn.execute(
            "UPDATE companies SET status = ?, last_crawled_at = ? WHERE id = ?",
            (status, now_iso(), company_id),
        )


class Greenhouse(BoardSource):
    name = "greenhouse"
    label = "Greenhouse"
    via = "Public API"
    platform = "greenhouse"

    async def board(self, ctx, slug, company):
        data = await ctx.http.get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"}
        )
        out = []
        for j in data.get("jobs", []):
            locs = [j.get("location", {}).get("name") or ""]
            locs += [o.get("location") or o.get("name") for o in j.get("offices", [])]
            emp = next(
                (
                    m.get("value")
                    for m in j.get("metadata") or []
                    if "type" in (m.get("name") or "").lower() and isinstance(m.get("value"), str)
                ),
                None,
            )
            out.append(
                RawJob(
                    source=self.name,
                    source_job_id=str(j["id"]),
                    url=j["absolute_url"],
                    title=j["title"],
                    company=j.get("company_name") or company,
                    description=html_to_text(j.get("content")),
                    locations=[x for x in dict.fromkeys(locs) if x],
                    job_type_raw=emp,
                    posted_at=_dt(j.get("first_published") or j.get("updated_at")),
                    valid_through=_dt(j.get("application_deadline")),
                )
            )
        return out


class Lever(BoardSource):
    name = "lever"
    label = "Lever"
    via = "Public API"
    platform = "lever"

    async def board(self, ctx, slug, company):
        data = await ctx.http.get_json(
            f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}
        )
        out = []
        for j in data:
            cat = j.get("categories") or {}
            lists = "\n".join(
                f"{x.get('text', '')}\n{html_to_text(x.get('content'))}" for x in j.get("lists", [])
            )
            desc = "\n\n".join(
                filter(None, [j.get("descriptionPlain"), lists, j.get("additionalPlain")])
            )
            sal = j.get("salaryRange") or {}
            out.append(
                RawJob(
                    source=self.name,
                    source_job_id=j["id"],
                    url=j["hostedUrl"],
                    title=j["text"],
                    company=company,
                    description=desc,
                    locations=cat.get("allLocations") or [cat.get("location") or ""],
                    remote=(j.get("workplaceType") == "remote") or None,
                    job_type_raw=cat.get("commitment"),
                    salary_min=sal.get("min"),
                    salary_max=sal.get("max"),
                    salary_currency=sal.get("currency"),
                    salary_period={"per-year-salary": "year", "per-month-salary": "month",
                                   "per-hour-wage": "hour"}.get(sal.get("interval")),  # fmt: skip
                    posted_at=_dt(j.get("createdAt")),
                    country_hint=j.get("country"),
                )
            )
        return out


class Ashby(BoardSource):
    name = "ashby"
    label = "Ashby"
    via = "Public API"
    platform = "ashby"

    async def board(self, ctx, slug, company):
        data = await ctx.http.get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            params={"includeCompensation": "true"},
        )
        out = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            comp = j.get("compensation") or {}
            locs = [j.get("location") or ""] + [
                x.get("location") for x in j.get("secondaryLocations") or []
            ]
            out.append(
                RawJob(
                    source=self.name,
                    source_job_id=j["id"],
                    url=j["jobUrl"],
                    title=j["title"].strip(),
                    company=company,
                    description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                    locations=[x for x in locs if x],
                    remote=j.get("isRemote") or (j.get("workplaceType") == "Remote") or None,
                    job_type_raw=j.get("employmentType"),
                    salary_text=comp.get("scrapeableCompensationSalarySummary"),
                    posted_at=_dt(j.get("publishedAt")),
                )
            )
        return out


class Workable(BoardSource):
    name = "workable"
    label = "Workable"
    via = "Public API"
    platform = "workable"

    async def board(self, ctx, slug, company):
        data = await ctx.http.get_json(
            f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
            params={"details": "true"},
        )
        out = []
        for j in data.get("jobs", []):
            locs = [
                ", ".join(filter(None, [x.get("city"), x.get("region"), x.get("country")]))
                for x in j.get("locations") or []
            ] or [", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))]
            out.append(
                RawJob(
                    source=self.name,
                    source_job_id=j["shortcode"],
                    url=j["url"],
                    title=j["title"],
                    company=data.get("name") or company,
                    description=html_to_text(j.get("description")),
                    locations=[x for x in locs if x],
                    remote=str(j.get("telecommuting")).lower() == "true" or None,
                    job_type_raw=j.get("employment_type"),
                    posted_at=_dt(j.get("published_on")),
                )
            )
        return out


class Recruitee(BoardSource):
    name = "recruitee"
    label = "Recruitee"
    via = "Public API"
    platform = "recruitee"

    async def board(self, ctx, slug, company):
        data = await ctx.http.get_json(f"https://{slug}.recruitee.com/api/offers/")
        out = []
        for j in data.get("offers", []):
            sal = j.get("salary") or {}
            out.append(
                RawJob(
                    source=self.name,
                    source_job_id=str(j["id"]),
                    url=j.get("careers_url") or f"https://{slug}.recruitee.com/o/{j['slug']}",
                    title=j["title"],
                    company=j.get("company_name") or company,
                    description=html_to_text(
                        (j.get("description") or "") + (j.get("requirements") or "")
                    ),
                    locations=[j.get("location") or ""],
                    remote=bool(j.get("remote")) or None,
                    job_type_raw=j.get("employment_type_code"),
                    salary_min=_num(sal.get("min")),
                    salary_max=_num(sal.get("max")),
                    salary_currency=sal.get("currency"),
                    salary_period=sal.get("period"),
                    posted_at=_dt(j.get("published_at")),
                    valid_through=_dt(j.get("close_at")),
                    country_hint=j.get("country_code"),
                )
            )
        return out


def _num(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class Personio(BoardSource):
    name = "personio"
    label = "Personio"
    via = "XML feed"
    platform = "personio"

    async def board(self, ctx, slug, company):
        text = await ctx.http.get_text(f"https://{slug}.jobs.personio.de/xml")
        if "<workzag-jobs" not in text:
            raise NotFound(slug)
        root = ET.fromstring(text)
        out = []
        for p in root.iter("position"):
            pid = p.findtext("id")
            offices = [p.findtext("office") or ""] + [
                o.text or "" for o in p.findall("additionalOffices/office")
            ]
            desc = "\n\n".join(
                f"{d.findtext('name') or ''}\n{html_to_text(d.findtext('value'))}"
                for d in p.findall("jobDescriptions/jobDescription")
            )
            out.append(
                RawJob(
                    source=self.name,
                    source_job_id=pid,
                    url=f"https://{slug}.jobs.personio.de/job/{pid}",
                    title=p.findtext("name") or "",
                    company=p.findtext("subcompany") or company,
                    description=desc,
                    locations=[x for x in offices if x],
                    job_type_raw=p.findtext("schedule") or p.findtext("employmentType"),
                    posted_at=_dt(p.findtext("createdAt")),
                )
            )
        return out


class SmartRecruiters(BoardSource):
    name = "smartrecruiters"
    label = "SmartRecruiters"
    via = "Public API"
    platform = "smartrecruiters"
    DETAILS_PER_BOARD = 25  # descriptions need one request each; only new postings get one

    async def board(self, ctx, slug, company):
        postings, offset = [], 0
        while True:
            data = await ctx.http.get_json(
                f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                params={"limit": 100, "offset": offset},
            )
            postings += data.get("content", [])
            offset += 100
            if offset >= data.get("totalFound", 0) or offset >= 500:
                break
        if not postings and offset == 100:
            return []
        known = {
            r[0]
            for r in ctx.conn.execute(
                "SELECT source_job_id FROM job_sources WHERE source = ?", (self.name,)
            )
        }
        out, details = [], 0
        for j in postings:
            loc = j.get("location") or {}
            desc = ""
            if j["id"] not in known and details < self.DETAILS_PER_BOARD:
                details += 1
                d = await ctx.http.get_json(
                    f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j['id']}"
                )
                sections = (d.get("jobAd") or {}).get("sections") or {}
                desc = "\n\n".join(
                    html_to_text(s.get("text")) for s in sections.values() if isinstance(s, dict)
                )
            out.append(
                RawJob(
                    source=self.name,
                    source_job_id=j["id"],
                    url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                    title=j["name"],
                    company=(j.get("company") or {}).get("name") or company,
                    description=desc,
                    locations=[
                        ", ".join(filter(None, [loc.get("city"), loc.get("region"),
                                                (loc.get("country") or "").upper()]))  # fmt: skip
                    ],
                    remote=loc.get("remote") or None,
                    job_type_raw=(j.get("typeOfEmployment") or {}).get("label"),
                    posted_at=_dt(j.get("releasedDate")),
                    country_hint=(loc.get("country") or "").upper() or None,
                )
            )
        return out


class Workday(BoardSource):
    """Workday career sites expose a JSON search endpoint. Slug format: tenant|wd5|site.
    Boards can hold thousands of jobs, so this searches the user's saved queries only."""

    name = "workday"
    label = "Workday career sites"
    via = "JSON endpoint"
    platform = "workday"
    DETAILS_PER_BOARD = 20

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        result = await super().fetch(ctx)
        result.complete_scopes.clear()  # search results are never a complete listing
        return result

    async def board(self, ctx, slug, company):
        tenant, dc, site = slug.split("|")
        base = f"https://{tenant}.{dc}.myworkdayjobs.com"
        api = f"{base}/wday/cxs/{tenant}/{site}"
        queries = [s["query"] for s in ctx.searches] or [""]
        seen: dict[str, dict] = {}
        for q in queries:
            data = (
                await ctx.http.request(
                    "POST",
                    f"{api}/jobs",
                    json_body={"limit": 20, "offset": 0, "searchText": q, "appliedFacets": {}},
                )
            ).json()
            for p in data.get("jobPostings", []):
                seen.setdefault(p["externalPath"], p)
        known = {
            r[0]
            for r in ctx.conn.execute(
                "SELECT source_job_id FROM job_sources WHERE source = ?", (self.name,)
            )
        }
        out, details = [], 0
        for path, p in seen.items():
            job_id = f"{tenant}:{path}"
            desc, posted = "", None
            if job_id not in known and details < self.DETAILS_PER_BOARD:
                details += 1
                d = await ctx.http.get_json(f"{api}{path}")
                info = d.get("jobPostingInfo") or {}
                desc = html_to_text(info.get("jobDescription"))
                posted = _dt(info.get("startDate"))
            out.append(
                RawJob(
                    source=self.name,
                    source_job_id=job_id,
                    url=f"{base}/{site}{path}",
                    title=p["title"],
                    company=company,
                    description=desc,
                    locations=[p.get("locationsText") or ""],
                    posted_at=posted,
                )
            )
        return out


ATS_SOURCES: list[type[BoardSource]] = [
    Greenhouse, Lever, Ashby, Workable, Recruitee, Personio, SmartRecruiters, Workday,
]  # fmt: skip

# Board URL patterns for "add a company" and self-growth from scraped links.
BOARD_PATTERNS = [
    (r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)",
     "greenhouse"),
    (r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)", "greenhouse"),
    (r"jobs\.(?:eu\.)?lever\.co/([\w-]+)", "lever"),
    (r"jobs\.ashbyhq\.com/([\w.-]+)", "ashby"),
    (r"apply\.workable\.com/([\w-]+)", "workable"),
    (r"([\w-]+)\.recruitee\.com", "recruitee"),
    (r"([\w-]+)\.jobs\.personio\.(?:de|com)", "personio"),
    (r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", "smartrecruiters"),
]  # fmt: skip
