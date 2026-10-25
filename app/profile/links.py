"""Optional profile evidence from public links: GitHub (public API) and a portfolio page."""

import re
from collections import Counter
from datetime import datetime

import httpx
from pydantic import BaseModel

from app.profile.parse import InputError

GITHUB_RE = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})/?$", re.I)
URL_RE = re.compile(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", re.I)
USER_AGENT = "JobMatcher/0.1 (personal job search, runs locally)"


def github_username(value: str) -> str:
    value = value.strip()
    match = GITHUB_RE.match(value)
    if not match:
        raise InputError("Enter a GitHub profile URL, like github.com/yourname.")
    return match.group(1)


def normalise_url(value: str) -> str:
    value = value.strip()
    if not URL_RE.match(value):
        raise InputError("Enter a valid website address.")
    return value if value.lower().startswith("http") else f"https://{value}"


class GitHubLanguage(BaseModel):
    name: str
    repos: int
    last_pushed_year: int | None = None


class GitHubEvidence(BaseModel):
    username: str
    public_repos: int
    languages: list[GitHubLanguage]
    topics: list[str]

    def as_text(self) -> str:
        langs = ", ".join(f"{x.name} ({x.repos} repos)" for x in self.languages)
        return f"GitHub {self.username}: {self.public_repos} own public repos. Languages: {langs}."


async def fetch_github(username: str, transport: httpx.AsyncBaseTransport | None = None):
    """Unauthenticated public API: 60 requests/hour, this uses at most 3."""
    repos: list[dict] = []
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        timeout=20,
        transport=transport,
    ) as client:
        for page in (1, 2, 3):
            r = await client.get(
                f"/users/{username}/repos",
                params={"per_page": 100, "page": page, "sort": "pushed"},
            )
            if r.status_code == 404:
                raise InputError(f"GitHub user '{username}' was not found.")
            if r.status_code in (403, 429):
                raise InputError("GitHub's free rate limit is used up; try again in an hour.")
            r.raise_for_status()
            batch = r.json()
            repos += batch
            if len(batch) < 100:
                break
    own = [r for r in repos if not r.get("fork")]
    counts: Counter[str] = Counter()
    last: dict[str, int] = {}
    topics: Counter[str] = Counter()
    for repo in own:
        lang = repo.get("language")
        year = _year(repo.get("pushed_at"))
        if lang:
            counts[lang] += 1
            if year and year > last.get(lang, 0):
                last[lang] = year
        topics.update(repo.get("topics") or [])
    return GitHubEvidence(
        username=username,
        public_repos=len(own),
        languages=[
            GitHubLanguage(name=name, repos=n, last_pushed_year=last.get(name))
            for name, n in counts.most_common()
        ],
        topics=[t for t, _ in topics.most_common(30)],
    )


def _year(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).year
    except ValueError:
        return None


async def fetch_portfolio(url: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    import trafilatura

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True, transport=transport
    ) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise InputError(f"Could not read {url}: {e.__class__.__name__}") from e
    text = trafilatura.extract(r.text) or ""
    return text[:8000]
