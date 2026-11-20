"""First-run crawl list: company boards checked to answer on their public endpoints
(2026-10-25). Discovery and self-growth add more; the Sources page can add or pause any."""

import sqlite3

from app.settings_store import get_value, set_value

SEED_COMPANIES = {
    "greenhouse": [
        "adyen", "affirm", "airbnb", "asana", "automatticcareers", "brex", "canonical", "chime",
        "cloudflare", "coinbase", "contentful", "databricks", "datadog", "deliveroo", "discord",
        "dropbox", "duolingo", "elastic", "figma", "gitlab", "gocardless", "grafanalabs",
        "gusto", "instacart", "intercom", "lyft", "mongodb", "monzo", "n26", "okta",
        "pinterest", "reddit", "robinhood", "samsara", "stripe", "twilio", "wise",
    ],
    "lever": ["palantir", "spotify", "outreach", "zoox"],
    "ashby": ["ramp", "notion", "linear", "openai", "supabase", "posthog", "cursor", "replit"],
    "workable": ["cloudfactory"],  # CloudFactory: Kathmandu-founded
    "recruitee": ["bunq"],
    "personio": ["personio"],
    "teamtailor": ["career.teamtailor.com"],
}  # fmt: skip

NAMES = {"automatticcareers": "Automattic", "grafanalabs": "Grafana Labs", "n26": "N26",
         "openai": "OpenAI", "posthog": "PostHog", "gitlab": "GitLab", "mongodb": "MongoDB",
         "cloudfactory": "CloudFactory", "career.teamtailor.com": "Teamtailor"}  # fmt: skip


REGIONAL_SEEDS = {
    "FI": {
        "greenhouse": ["wolt", "oura", "relex", "solita", "smartlyio", "yousician", "housemarque"],
        "ashby": ["supercell", "reaktor", "sievo"],
        "lever": ["iqm"],
        "workable": ["nitor"],
        "teamtailor": ["siili.teamtailor.com", "upcloud.teamtailor.com", "wunderdog.teamtailor.com",
                       "vincitoyj.teamtailor.com", "holvi.teamtailor.com"],
    },
}  # fmt: skip

REGIONAL_NAMES = {"relex": "RELEX Solutions", "smartlyio": "Smartly.io", "iqm": "IQM",
                  "siili.teamtailor.com": "Siili Solutions", "upcloud.teamtailor.com": "UpCloud",
                  "wunderdog.teamtailor.com": "Wunderdog", "vincitoyj.teamtailor.com": "Vincit",
                  "holvi.teamtailor.com": "Holvi"}  # fmt: skip


def seed_regions(conn: sqlite3.Connection, countries: list[str | None]) -> int:
    """Add each region's company boards once, the first time that country is the user's home
    or a target, so existing databases pick them up too."""
    done = set(get_value(conn, "seeded_regions", []) or [])
    todo = [c for c in dict.fromkeys(c.upper() for c in countries if c) if c in REGIONAL_SEEDS]
    todo = [c for c in todo if c not in done]
    if not todo:
        return 0
    added = 0
    with conn:
        for country in todo:
            for platform, slugs in REGIONAL_SEEDS[country].items():
                for s in slugs:
                    name = REGIONAL_NAMES.get(s, s.split(".")[0].replace("-", " ").title())
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO companies (name, platform, slug) VALUES (?, ?, ?)",
                        (name, platform, s),
                    )
                    added += cur.rowcount
    set_value(conn, "seeded_regions", sorted(done | set(todo)))
    return added


def seed(conn: sqlite3.Connection) -> int:
    if get_value(conn, "seeded"):
        return 0
    added = 0
    with conn:
        for platform, slugs in SEED_COMPANIES.items():
            for s in slugs:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO companies (name, platform, slug) VALUES (?, ?, ?)",
                    (NAMES.get(s, s.replace("-", " ").title()), platform, s),
                )
                added += cur.rowcount
    set_value(conn, "seeded", True)
    return added
