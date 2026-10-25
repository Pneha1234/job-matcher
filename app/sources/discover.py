"""Company discovery from the Common Crawl URL index (free): every captured URL under an
ATS domain names a company board."""

import json
import sqlite3

from app.sources.base import PoliteClient
from app.sources.runner import board_from_url

PATTERNS = {
    "greenhouse": "boards.greenhouse.io/*",
    "lever": "jobs.lever.co/*",
    "ashby": "jobs.ashbyhq.com/*",
    "workable": "apply.workable.com/*",
}


async def discover(conn: sqlite3.Connection, http: PoliteClient, per_platform: int = 2000) -> dict:
    info = await http.get_json("https://index.commoncrawl.org/collinfo.json", cache_ttl_s=86400)
    api = info[0]["cdx-api"]
    added: dict[str, int] = {}
    for platform, pattern in PATTERNS.items():
        text = await http.get_text(
            api,
            params={"url": pattern, "output": "json", "fl": "url", "limit": per_platform},
            cache_ttl_s=7 * 86400,
        )
        slugs = set()
        for line in text.splitlines():
            try:
                url = json.loads(line)["url"]
            except (json.JSONDecodeError, KeyError):
                continue
            found = board_from_url(url)
            if found and found[0] == platform and found[1] not in ("embed", "v1", "api"):
                slugs.add(found[1])
        n = 0
        with conn:
            for slug in sorted(slugs):
                cur = conn.execute(
                    "INSERT OR IGNORE INTO companies (name, platform, slug) VALUES (?, ?, ?)",
                    (slug.replace("-", " ").title(), platform, slug),
                )
                n += cur.rowcount
        added[platform] = n
    return added
