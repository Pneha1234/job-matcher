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
