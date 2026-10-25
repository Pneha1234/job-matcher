"""Near-duplicate merging by embedding similarity, on top of the canonical-key dedup.

Only near-identical postings merge, and only when the titles agree on every word: the
same company with the title words reordered or repunctuated ("Security Engineer (IAM)" /
"IAM Security Engineer"), or the same title under a company-name variant ("Acme" / "Acme
Technologies"). Region, language, segment and level variants stay separate jobs. The
later job is linked to the earlier one with ``duplicate_of``; its sources and locations
move over; nothing is deleted.
"""

import re
import sqlite3

from app.normalize.ingest import company_key, title_key

# Cosine distance. bge-m3 puts a reworded copy of a posting at about 0.99 similarity, but
# also rates unrelated roles at one company up to 0.97, hence the title rules below.
MAX_DISTANCE = 0.03


FILLER = {"and", "the", "of", "for", "team", "m", "f", "d", "w", "x"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]+", text.lower())) - FILLER


def same_role(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    """Same title words in any order at the same company, or the same title at a company
    whose name extends the other's. Any extra word (a region, a language, a segment, a
    level) means a different job: "Account Executive, Chile" never merges with ", Colombia".
    """
    ca, cb = company_key(a["company_name"]), company_key(b["company_name"])
    if ca == cb:
        return _words(a["title"]) == _words(b["title"])
    related = bool(ca and cb) and (ca.startswith(cb) or cb.startswith(ca))
    return related and title_key(a["title"]) == title_key(b["title"])


def merge(conn: sqlite3.Connection, keep: int, drop: int) -> None:
    with conn:
        conn.execute("UPDATE job_sources SET job_id = ? WHERE job_id = ?", (keep, drop))
        known = {
            r[0] for r in conn.execute("SELECT raw FROM job_locations WHERE job_id = ?", (keep,))
        }
        for loc in conn.execute("SELECT id, raw FROM job_locations WHERE job_id = ?", (drop,)):
            if loc["raw"] not in known:
                conn.execute("UPDATE job_locations SET job_id = ? WHERE id = ?", (keep, loc["id"]))
        conn.execute(
            "UPDATE jobs SET first_seen_at = MIN(first_seen_at, (SELECT first_seen_at FROM jobs "
            "WHERE id = ?)), last_seen_at = MAX(last_seen_at, (SELECT last_seen_at FROM jobs "
            "WHERE id = ?)) WHERE id = ?",
            (drop, drop, keep),
        )
        conn.execute("UPDATE jobs SET duplicate_of = ? WHERE id = ?", (keep, drop))


def merge_near_duplicates(conn: sqlite3.Connection, job_ids: list[int]) -> int:
    """Check freshly embedded jobs against their nearest neighbours; returns merges made."""
    merged = 0
    for job_id in job_ids:
        job = conn.execute(
            "SELECT j.*, e.embedding FROM jobs j JOIN job_embeddings e ON e.job_id = j.id "
            "WHERE j.id = ? AND j.duplicate_of IS NULL",
            (job_id,),
        ).fetchone()
        if not job:
            continue
        near = conn.execute(
            "SELECT job_id, distance FROM job_embeddings WHERE embedding MATCH ? AND k = 8 "
            "ORDER BY distance",
            (job["embedding"],),
        ).fetchall()
        for n in near:
            if n["job_id"] == job_id or n["distance"] > MAX_DISTANCE:
                continue
            other = conn.execute(
                "SELECT * FROM jobs WHERE id = ? AND duplicate_of IS NULL", (n["job_id"],)
            ).fetchone()
            if not other or not same_role(job, other):
                continue
            # The earlier job stays; a job with your application or flags is never merged away.
            keep, drop = sorted((job, other), key=lambda r: (r["first_seen_at"], r["id"]))
            if conn.execute(
                "SELECT 1 FROM applications WHERE job_id = ? UNION "
                "SELECT 1 FROM user_job_flags WHERE job_id = ?",
                (drop["id"], drop["id"]),
            ).fetchone():
                continue
            merge(conn, keep["id"], drop["id"])
            merged += 1
            break
    return merged
