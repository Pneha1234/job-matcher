"""schema.org JobPosting crawling (JSON-LD or microdata): Nepali and Indian boards via
their sitemaps or listing pages, and company career pages. Boards are crawled gently: a
capped number of new posting pages per run, and the sitemap itself confirms which known
postings are still listed. Only pages robots.txt allows are fetched."""

import gzip
import html
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser

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
    return found or microdata_postings(html)


def _microdata_item(node) -> dict:
    """Collect the itemprops whose nearest itemscope is ``node``."""
    item: dict = {}
    for prop in node.css("[itemprop]"):
        owner = prop.parent
        while owner is not None and "itemscope" not in owner.attributes:
            owner = owner.parent
        if owner is None or owner.mem_id != node.mem_id:
            continue
        key = prop.attributes.get("itemprop") or ""
        if "itemscope" in prop.attributes:
            value = _microdata_item(prop)
        elif prop.attributes.get("content") is not None:
            value = prop.attributes["content"]
        elif prop.tag in ("a", "link"):
            value = prop.attributes.get("href") or prop.text(strip=True)
        else:
            value = prop.html if key == "description" else prop.text(strip=True)
        current = item.get(key)
        # A posting's own description is the longest one inside it.
        if current is None or (key == "description" and len(str(value)) > len(str(current))):
            item[key] = value
    return item


def microdata_postings(html: str) -> list[dict]:
    if "schema.org/JobPosting" not in html:
        return []
    tree = LexborHTMLParser(html)
    return [
        _microdata_item(node)
        for node in tree.css("[itemscope]")
        if (node.attributes.get("itemtype") or "").endswith("/JobPosting")
    ]


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
    title = re.sub(r"\s+", " ", html.unescape(_text(posting.get("title")))).strip()
    org = re.sub(r"\s+", " ", html.unescape(_text(posting.get("hiringOrganization")))).strip()
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
        valid_through=_deadline(posting.get("validThrough")),
        **kw,
    )


def _deadline(value):
    """A deadline without a time of day ("2026-10-27") lasts until the end of that day."""
    dt = _dt(value)
    if dt and dt.hour == dt.minute == dt.second == 0 and not re.search(r"T\d", str(value)):
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


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


def search_terms(searches: list[dict]) -> list[list[str]]:
    """Words of each saved search, matched against posting URL slugs on big boards."""
    terms = []
    for search in searches:
        words = [w for w in re.findall(r"[a-z0-9+#]+", (search.get("query") or "").lower())]
        words = [w for w in words if len(w) >= 3]
        if words:
            terms.append(words)
    return terms


def matches_search(url: str, terms: list[list[str]]) -> bool:
    slug = urlparse(url).path.lower()
    return any(all(word in slug for word in words) for words in terms)


class BoardCrawler(Source):
    """Shared page-fetching for boards whose posting pages carry JobPosting markup."""

    kind = "crawl"
    group = "gentle"
    daily_budget = 150
    country = "NP"
    PAGES_PER_RUN = 40
    # Big boards: only fetch postings whose URL matches a saved search.
    filter_by_searches = False

    def known_urls(self, ctx: FetchContext) -> set[str]:
        return {
            r["url"]
            for r in ctx.conn.execute(
                "SELECT url FROM job_sources WHERE source = ? AND status = 'listed'", (self.name,)
            )
        }

    def pick(self, ctx: FetchContext, pages: list[str], known: set[str]) -> list[str]:
        fresh = [p for p in pages if p not in known]
        if self.filter_by_searches:
            terms = search_terms(ctx.searches)
            fresh = [p for p in fresh if matches_search(p, terms)] if terms else []
        return fresh[: ctx.limit or self.PAGES_PER_RUN]

    async def read_pages(self, ctx: FetchContext, urls: list[str], result: FetchResult) -> None:
        for url in urls:
            if not await ctx.http.allowed(url):
                result.errors.append(f"robots.txt disallows {url}")
                continue
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


class SitemapBoard(BoardCrawler):
    """A board whose sitemap lists its live postings."""

    sitemap: str
    child_filter: str  # regex picking the jobs sitemaps from a sitemap index
    url_filter: re.Pattern | None = None
    max_children: int | None = None  # big boards: read only this many child sitemaps

    async def _xml(self, ctx: FetchContext, url: str) -> str:
        r = await ctx.http.request("GET", url, cache_ttl_s=6 * 3600)
        body = r.content
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return body.decode("utf-8", errors="replace")

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        children, pages = sitemap_urls(await self._xml(ctx, self.sitemap))
        wanted = [c for c in children if re.search(self.child_filter, c)]
        complete = self.max_children is None or len(wanted) <= self.max_children
        for child in wanted[: self.max_children]:
            _, more = sitemap_urls(await self._xml(ctx, child))
            pages += more
        if self.url_filter:
            pages = [p for p in pages if self.url_filter.search(p)]
        known = self.known_urls(ctx)
        # Only a full listing can show that a posting was removed.
        result = FetchResult(complete_scopes={self.name} if complete else set())
        result.still_listed = {u for u in pages if u in known}
        await self.read_pages(ctx, self.pick(ctx, pages, known), result)
        result.requests = ctx.http.requests
        return result


class ListingBoard(BoardCrawler):
    """A board with no jobs sitemap: posting links are read from its listing pages."""

    listing_pages: list[str]
    link_pattern: re.Pattern

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        pages: list[str] = []
        for listing in self.listing_pages:
            html = await ctx.http.get_text(listing, cache_ttl_s=1800)
            for href in re.findall(r'href="([^"#]+)"', html):
                full = urljoin(listing, href)
                if self.link_pattern.search(full) and full not in pages:
                    pages.append(full)
        known = self.known_urls(ctx)
        result = FetchResult()  # listing pages show only the newest postings
        result.still_listed = {u for u in pages if u in known}
        await self.read_pages(ctx, self.pick(ctx, pages, known), result)
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


class JobsNepal(SitemapBoard):
    name = "jobsnepal"
    label = "JobsNepal"
    via = "Sitemap + microdata"
    sitemap = "https://www.jobsnepal.com/sitemap.xml"
    child_filter = "jobs-sitemap"


class Jobejee(ListingBoard):
    name = "jobejee"
    label = "Jobejee"
    via = "Listing + JobPosting"
    listing_pages = ["https://jobejee.com/"]
    link_pattern = re.compile(r"jobejee\.com/job/[^/]+/\d+$")


class Internshala(SitemapBoard):
    name = "internshala"
    label = "Internshala"
    via = "Sitemap + JobPosting"
    sitemap = "https://internshala.com/sitemap.xml"
    child_filter = r"/sitemap-(internships|jobs)\.xml$"
    country = "IN"
    filter_by_searches = True


class Shine(SitemapBoard):
    name = "shine"
    label = "Shine"
    via = "Sitemap + JobPosting"
    sitemap = "https://www.shine.com/index-all-sitemap.xml"
    child_filter = r"/all_jd_\d*_?sitemap\.xml$"
    max_children = 4  # about 10,000 postings each; the rest expire by validThrough
    country = "IN"
    filter_by_searches = True


class Freshersworld(SitemapBoard):
    name = "freshersworld"
    label = "Freshersworld"
    via = "Sitemap + JobPosting"
    sitemap = "https://www.freshersworld.com/sitemap-index.xml"
    child_filter = r"sitemap-activejobs-\d+\.xml$"
    country = "IN"
    filter_by_searches = True


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
            if not await ctx.http.allowed(url):
                result.errors.append(f"robots.txt disallows {url}")
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
                    if not await ctx.http.allowed(link):
                        continue
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


CRAWL_SOURCES = [
    Merojob, Kumarijob, JobsNepal, Jobejee, Internshala, Shine, Freshersworld, CompanySites,
]  # fmt: skip
