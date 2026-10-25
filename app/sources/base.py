"""The source plugin interface and the polite HTTP client every source uses.

Each source implements ``fetch(ctx) -> FetchResult`` (a list of ``RawJob`` plus which
scopes it listed completely, so lifecycle can tell "removed" from "not fetched").
"""

import asyncio
import hashlib
import json
import random
import sqlite3
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings

USER_AGENT = "JobMatcher/0.1 (personal job search, runs locally; polite, cached)"
BLOCK_MARKERS = ("captcha", "are you a robot", "unusual traffic", "cf-chl", "access denied")


class RawJob(BaseModel):
    source: str
    source_job_id: str
    url: str
    title: str
    company: str
    description: str = ""  # plain text
    locations: list[str] = []
    remote: bool | None = None
    remote_scope: list[str] = []  # "USA", "Europe", "Worldwide"...
    job_type_raw: str | None = None
    salary_text: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    posted_at: datetime | None = None
    valid_through: datetime | None = None
    country_hint: str | None = None  # ISO-2 when the source is country-specific
    language_hint: str | None = None  # e.g. "ne" for Nepali boards
    scope: str | None = None  # which complete listing this came from (a company board slug)
    company_board: tuple[str, str] | None = None  # (platform, slug) for self-growth
    extra: dict[str, Any] = Field(default_factory=dict)


@dataclass
class FetchResult:
    jobs: list[RawJob] = field(default_factory=list)
    # Scopes listed completely this run. Jobs in these scopes that were not seen count a miss.
    complete_scopes: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    requests: int = 0
    # source_job_ids confirmed listed without fetching their pages again (sitemaps).
    still_listed: set[str] = field(default_factory=set)


class SourceBlocked(Exception):
    """The site answered with a block or CAPTCHA. The source is paused, never forced."""


class BudgetExhausted(Exception):
    """Today's request budget is used up; the source waits until tomorrow."""


class NotFound(Exception):
    pass


class PoliteClient:
    """Random 3–8 s gaps between live requests, a disk cache, and a daily request budget."""

    def __init__(
        self,
        source: str,
        conn: sqlite3.Connection,
        budget: int,
        delay: tuple[float, float] = (3.0, 8.0),
        cache_ttl_s: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.source = source
        self.conn = conn
        self.budget = budget
        self.delay = delay
        self.cache_ttl_s = get_settings().http_cache_ttl_s if cache_ttl_s is None else cache_ttl_s
        self.requests = 0
        self._last = 0.0
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
            timeout=40,
            follow_redirects=True,
            transport=transport,
        )
        self.cache_dir = Path(get_settings().db_path).parent / "cache" / source

    async def aclose(self) -> None:
        await self._client.aclose()

    def used_today(self) -> int:
        row = self.conn.execute(
            "SELECT used FROM source_budget WHERE source = ? AND day = ?",
            (self.source, date.today().isoformat()),
        ).fetchone()
        return row["used"] if row else 0

    def _spend(self) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO source_budget (source, day, used) VALUES (?, ?, 1) "
                "ON CONFLICT (source, day) DO UPDATE SET used = used + 1",
                (self.source, date.today().isoformat()),
            )

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / hashlib.sha256(key.encode()).hexdigest()[:32]

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
        form: dict | None = None,
        headers: dict | None = None,
        cache_ttl_s: float | None = None,
    ) -> httpx.Response:
        ttl = self.cache_ttl_s if cache_ttl_s is None else cache_ttl_s
        key = json.dumps([method, url, params, json_body], sort_keys=True, default=str)
        path = self._cache_path(key)
        if ttl > 0 and path.exists() and time.time() - path.stat().st_mtime < ttl:
            cached = json.loads(path.read_text())
            return httpx.Response(
                cached["status"],
                content=cached["body"].encode(),
                headers={"x-cache": "hit", "content-type": cached.get("type", "")},
                request=httpx.Request(method, cached.get("url", url)),
            )
        if self.used_today() >= self.budget:
            raise BudgetExhausted(f"{self.source}: daily budget of {self.budget} requests used")
        wait = self._last + random.uniform(*self.delay) - time.monotonic()
        if self._last and wait > 0:
            await asyncio.sleep(wait)
        self._spend()
        self.requests += 1
        try:
            r = await self._client.request(
                method, url, params=params, json=json_body, data=form, headers=headers
            )
        finally:
            self._last = time.monotonic()
        body_head = r.text[:4000].lower() if r.status_code != 200 else ""
        if r.status_code == 429 or (
            r.status_code in (403, 503) and any(m in body_head for m in BLOCK_MARKERS)
        ):
            raise SourceBlocked(f"{self.source}: HTTP {r.status_code} from {r.url.host}")
        if r.status_code == 403:
            raise SourceBlocked(f"{self.source}: HTTP 403 from {r.url.host}")
        if r.status_code in (404, 410):
            raise NotFound(str(r.url))
        r.raise_for_status()
        if ttl > 0:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "status": r.status_code,
                        "body": r.text,
                        "type": r.headers.get("content-type", ""),
                        "url": str(r.url),
                    }
                )
            )
        return r

    async def allowed(self, url: str) -> bool:
        """robots.txt check for HTML crawling, one robots fetch per host per day."""
        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                text = await self.get_text(f"{host}/robots.txt", cache_ttl_s=24 * 3600)
                parser.parse(text.splitlines())
            except NotFound:
                parser.parse([])  # no robots.txt: everything is allowed
            self._robots[host] = parser
        return self._robots[host].can_fetch(USER_AGENT, url)

    async def get_json(self, url: str, **kw) -> Any:
        return (await self.request("GET", url, **kw)).json()

    async def get_text(self, url: str, **kw) -> str:
        return (await self.request("GET", url, **kw)).text


@dataclass
class FetchContext:
    conn: sqlite3.Connection
    http: PoliteClient
    searches: list[dict]  # saved searches: {"query", "location"}
    target_countries: list[str]
    companies: list[dict]  # rows from the companies table for this platform
    limit: int | None = None  # cap on items per run (gentle sources)
    api_key: str | None = None  # for sources with a free sign-up key


SourceKind = Literal["feed", "ats", "scrape", "crawl"]


class Source(ABC):
    name: ClassVar[str]
    label: ClassVar[str]
    via: ClassVar[str]
    kind: ClassVar[SourceKind]
    group: ClassVar[str]  # schedule group: jobspy, ats, feeds, gentle
    daily_budget: ClassVar[int] = 200
    platform: ClassVar[str | None] = None  # company platform this source crawls
    needs_searches: ClassVar[bool] = False
    # Sources that need a free sign-up key: where to get it and the format to paste.
    key_help: ClassVar[str | None] = None

    @abstractmethod
    async def fetch(self, ctx: FetchContext) -> FetchResult: ...
