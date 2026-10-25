"""schema.org JobPosting crawling: Nepali boards via their sitemaps, and company career
pages. Small sites are crawled gently: a capped number of new pages per run, and the
sitemap itself (one request) confirms which known postings are still listed."""

import gzip
import html
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

from app.normalize.classify import html_to_text
from app.sources.ats import _dt
from app.sources.base import FetchContext, FetchResult, NotFound, RawJob, Source

LD_RE = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
DESCRIPTION_RE = re.compile(r'("description"\s*:\s*")(.*?)("\s*,\s*\n\s*"[@\w]+"\s*:)', re.S)


def _loads_lenient(text: str):
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass
    # Some boards paste raw HTML into "description" without escaping its quotes.
    text = DESCRIPTION_RE.sub(
        lambda m: m.group(1) + re.sub(r'(?<!\\)"', r"\"", m.group(2)) + m.group(3), text
    )
    # Some emit a string value missing its closing quote at the end of a line.
    lines = text.splitlines()
    in_string = False  # inside a string value that spans lines (raw newlines in HTML)
    for i, line in enumerate(lines):
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        odd = (line.count('"') - line.count('\\"')) % 2
        if odd and not in_string and nxt[:1] in ('"', "}", "]"):
            lines[i] = line + '"' + ("," if nxt.startswith('"') else "")
        elif odd:
            in_string = not in_string
    try:
        return json.loads("\n".join(lines), strict=False)
    except json.JSONDecodeError:
        return None


def job_postings(html: str) -> list[dict]:
    found: list[dict] = []

    def walk(node):
        if isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            kind = node.get("@type")
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                found.append(node)
            for key in ("@graph", "itemListElement", "item"):
                if key in node:
                    walk(node[key])

    for block in LD_RE.findall(html):
        data = _loads_lenient(block.strip())
        if data is not None:
            walk(data)
    return found


def _text(value) -> str:
    if isinstance(value, dict):
        return value.get("name") or value.get("value") or ""
    if isinstance(value, list):
        return ", ".join(_text(v) for v in value if v)
    return str(value or "")


def _places(posting: dict) -> list[str]:
    places = posting.get("jobLocation") or []
    if isinstance(places, dict):
        places = [places]
    out = []
    for p in places:
        addr = p.get("address") if isinstance(p, dict) else None
        if isinstance(addr, dict):
            out.append(
                ", ".join(
                    _text(addr.get(k))
                    for k in ("addressLocality", "addressRegion", "addressCountry")
                    if addr.get(k)
                )
            )
        elif isinstance(addr, str):
            out.append(addr)
    return [x for x in out if x]


def raw_from_posting(posting: dict, url: str, source: str, **kw) -> RawJob | None:
    title = html.unescape(_text(posting.get("title"))).strip()
    org = html.unescape(_text(posting.get("hiringOrganization"))).strip()
    if not title or not org:
        return None
    salary = posting.get("baseSalary") or {}
    value = salary.get("value") if isinstance(salary, dict) else None
    lo = hi = unit = None
    if isinstance(value, dict):
        lo, hi = value.get("minValue") or value.get("value"), value.get("maxValue")
        unit = value.get("unitText")
    remote = str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE" or None
    scope = [_text(x) for x in _as_list(posting.get("applicantLocationRequirements"))]
    ident = posting.get("identifier")
    source_id = _text(ident) if ident else url
    return RawJob(
        source=source,
        source_job_id=source_id or url,
        url=posting.get("url") or url,
        title=title,
        company=org,
        description=html_to_text(_text(posting.get("description"))),
        locations=_places(posting),
        remote=remote,
        remote_scope=[s for s in scope if s],
        job_type_raw=_text(posting.get("employmentType")) or None,
        salary_min=_float(lo),
        salary_max=_float(hi),
        salary_currency=salary.get("currency") if isinstance(salary, dict) else None,
        salary_period=(unit or "").lower() or None,
        posted_at=_dt(posting.get("datePosted")),
        valid_through=_dt(posting.get("validThrough")),
        **kw,
    )


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _float(value) -> float | None:
    try:
        return float(str(value).replace(",", "")) if value not in (None, "") else None
    except ValueError:
        return None


def sitemap_urls(xml: str) -> tuple[list[str], list[str]]:
    """(child sitemaps, page urls)."""
    root = ET.fromstring(xml)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    children = [e.text.strip() for e in root.iter(f"{ns}sitemap/{ns}loc") if e.text]
    if not children:
        children = [
            loc.text.strip()
            for sm in root.iter(f"{ns}sitemap")
            for loc in sm.iter(f"{ns}loc")
            if loc.text
        ]
    pages = [
        loc.text.strip() for u in root.iter(f"{ns}url") for loc in u.iter(f"{ns}loc") if loc.text
    ]
    return children, pages


class SitemapBoard(Source):
    """A job board whose sitemap lists every live posting and whose posting pages carry
    schema.org JobPosting markup."""

    kind = "crawl"
    group = "gentle"
    daily_budget = 150
    sitemap: str
    child_filter: str  # substring picking the jobs sitemap from a sitemap index
    url_filter: re.Pattern | None = None
    country = "NP"
    PAGES_PER_RUN = 40

    async def _xml(self, ctx: FetchContext, url: str) -> str:
        r = await ctx.http.request("GET", url, cache_ttl_s=1800)
        body = r.content
        if url.endswith(".gz") and body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return body.decode("utf-8", errors="replace")

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        children, pages = sitemap_urls(await self._xml(ctx, self.sitemap))
        for child in [c for c in children if self.child_filter in c]:
            _, more = sitemap_urls(await self._xml(ctx, child))
            pages += more
        if self.url_filter:
            pages = [p for p in pages if self.url_filter.search(p)]
        listed = set(pages)
        known = {
            r["url"]
            for r in ctx.conn.execute(
                "SELECT url FROM job_sources WHERE source = ? AND status = 'listed'", (self.name,)
            )
        }
        result = FetchResult(complete_scopes={self.name})
        result.still_listed = {u for u in listed if u in known}
        for url in [p for p in pages if p not in known][: ctx.limit or self.PAGES_PER_RUN]:
            try:
                html = await ctx.http.get_text(url, cache_ttl_s=24 * 3600)
            except NotFound:
                continue
            postings = job_postings(html)
            if not postings:
                result.errors.append(f"No JobPosting markup on {url}")
                continue
            job = raw_from_posting(
                postings[0], url, self.name, country_hint=self.country, scope=self.name
            )
            if job:
                job.source_job_id = url
                job.url = url
                result.jobs.append(job)
        result.requests = ctx.http.requests
        return result


class Merojob(SitemapBoard):
    name = "merojob"
    label = "Merojob"
    via = "Sitemap + JobPosting"
    sitemap = "https://merojob.com/sitemap.xml"
    child_filter = "job_post"


class Kumarijob(SitemapBoard):
    name = "kumarijob"
    label = "Kumarijob"
    via = "Sitemap + JobPosting"
    sitemap = "https://www.kumarijob.com/sitemap.xml"
    child_filter = "sitemap-jobs"


JOB_LINK = re.compile(r"/(jobs?|careers?|positions?|vacanc|openings?|vacatures?|stellen)", re.I)


class CompanySites(Source):
    """Career pages added by hand (platform 'jsonld'): JobPosting markup on the page itself,
    or on job pages it links to on the same site."""

    name = "company_sites"
    label = "Company sites (JobPosting)"
    via = "JSON-LD crawler"
    kind = "crawl"
    group = "gentle"
    platform = "jsonld"
    daily_budget = 200
    LINKS_PER_SITE = 15

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        result = FetchResult()
        for company in ctx.companies:
            url = company["careers_url"]
            if not url:
                continue
            try:
                html = await ctx.http.get_text(url, cache_ttl_s=6 * 3600)
            except NotFound:
                result.errors.append(f"{url}: not found")
                continue
            postings = [(p, url) for p in job_postings(html)]
            if not postings:
                host = urlparse(url).netloc
                links = []
                for href in re.findall(r'href="([^"#]+)"', html):
                    full = urljoin(url, href)
                    if urlparse(full).netloc == host and JOB_LINK.search(full) and full != url:
                        links.append(full)
                for link in list(dict.fromkeys(links))[: self.LINKS_PER_SITE]:
                    try:
                        page = await ctx.http.get_text(link, cache_ttl_s=24 * 3600)
                    except NotFound:
                        continue
                    postings += [(p, link) for p in job_postings(page)]
            for posting, page_url in postings:
                job = raw_from_posting(posting, page_url, self.name, scope=str(company["id"]))
                if job:
                    job.company = job.company or company["name"]
                    result.jobs.append(job)
            result.complete_scopes.add(str(company["id"]))
        result.requests = ctx.http.requests
        return result


CRAWL_SOURCES = [Merojob, Kumarijob, CompanySites]
