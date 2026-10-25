"""SQLite + sqlite-vec connection and schema migrations.

Migrations are plain SQL, applied in order and tracked with ``PRAGMA user_version``.
Rows are never hard-deleted: jobs, applications and profile versions change status
instead (see docs/PLAN.md).
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

# bge-m3 dense embeddings.
EMBEDDING_DIM = 1024

MIGRATIONS: list[str] = [
    # 1 — initial schema
    f"""
    CREATE TABLE profile_versions (
        id              INTEGER PRIMARY KEY,
        label           TEXT,
        raw_inputs      TEXT NOT NULL DEFAULT '{{}}',   -- JSON: resume text, links, export
        profile_json    TEXT NOT NULL DEFAULT '{{}}',   -- JSON: extracted, user-reviewed profile
        is_active       INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
        status          TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'saved', 'archived')),
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    CREATE UNIQUE INDEX one_active_profile ON profile_versions (is_active) WHERE is_active = 1;

    CREATE TABLE companies (
        id              INTEGER PRIMARY KEY,
        name            TEXT NOT NULL,
        platform        TEXT,                           -- greenhouse, lever, ashby, custom...
        slug            TEXT,
        careers_url     TEXT,
        status          TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'paused', 'dead')),
        last_crawled_at TEXT,
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE (platform, slug)
    );

    CREATE TABLE jobs (
        id                  INTEGER PRIMARY KEY,
        canonical_key       TEXT NOT NULL UNIQUE,
        title               TEXT NOT NULL,
        company_id          INTEGER REFERENCES companies (id),
        company_name        TEXT NOT NULL,
        description         TEXT NOT NULL DEFAULT '',
        job_type            TEXT CHECK (job_type IN
                            ('full-time', 'contract', 'freelance', 'part-time', 'internship')),
        work_mode           TEXT CHECK (work_mode IN ('onsite', 'hybrid', 'remote')),
        remote_eligibility  TEXT,                       -- JSON: countries, regions, timezones
        visa_sponsorship    TEXT CHECK (visa_sponsorship IN ('yes', 'no')),
        relocation          INTEGER CHECK (relocation IN (0, 1)),
        language            TEXT,                       -- posting language (ISO 639-1)
        language_reqs       TEXT,                       -- JSON list
        salary_text         TEXT,                       -- original, always kept
        salary_min          REAL,                       -- null = not disclosed, never 0
        salary_max          REAL,
        salary_currency     TEXT,
        salary_period       TEXT CHECK (salary_period IN ('hour', 'day', 'month', 'year')),
        salary_annual_min   REAL,                       -- in the user's currency
        salary_annual_max   REAL,
        extra               TEXT NOT NULL DEFAULT '{{}}', -- JSON: notice period, experience...
        posted_at           TEXT,
        valid_through       TEXT,
        first_seen_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        last_seen_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        last_checked_at     TEXT,
        status              TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'expired', 'stale')),
        expired_reason      TEXT,
        updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    CREATE INDEX jobs_status ON jobs (status, last_seen_at);

    CREATE TABLE job_locations (
        id              INTEGER PRIMARY KEY,
        job_id          INTEGER NOT NULL REFERENCES jobs (id),
        raw             TEXT NOT NULL,                  -- location string as posted
        city            TEXT,
        region          TEXT,
        country_code    TEXT,                           -- ISO 3166-1 alpha-2
        lat             REAL,
        lon             REAL,
        geonames_id     INTEGER,
        resolved        INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1))
    );
    CREATE INDEX job_locations_job ON job_locations (job_id);
    CREATE INDEX job_locations_country ON job_locations (country_code);

    CREATE TABLE job_sources (
        id              INTEGER PRIMARY KEY,
        job_id          INTEGER NOT NULL REFERENCES jobs (id),
        source          TEXT NOT NULL,
        url             TEXT NOT NULL,
        source_job_id   TEXT,
        first_seen_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        last_seen_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE (source, source_job_id)
    );
    CREATE INDEX job_sources_job ON job_sources (job_id);

    CREATE TABLE match_scores (
        id                  INTEGER PRIMARY KEY,
        job_id              INTEGER NOT NULL REFERENCES jobs (id),
        profile_version_id  INTEGER NOT NULL REFERENCES profile_versions (id),
        status              TEXT NOT NULL CHECK (status IN ('scored', 'unscored')),
        sub_scores          TEXT,                       -- JSON, validated LLM output
        final_pct           REAL CHECK (final_pct BETWEEN 0 AND 100), -- null when unscored
        matched_skills      TEXT,                       -- JSON list
        missing_skills      TEXT,                       -- JSON list
        explanation         TEXT,
        error               TEXT,                       -- why it is unscored
        model               TEXT,
        scored_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        UNIQUE (job_id, profile_version_id),
        CHECK (status = 'unscored' OR final_pct IS NOT NULL)
    );

    CREATE TABLE applications (
        id          INTEGER PRIMARY KEY,
        job_id      INTEGER NOT NULL UNIQUE REFERENCES jobs (id),
        status      TEXT NOT NULL DEFAULT 'saved' CHECK (status IN
                    ('saved', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn')),
        applied_at  TEXT,
        notes       TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE application_events (
        id              INTEGER PRIMARY KEY,
        application_id  INTEGER NOT NULL REFERENCES applications (id),
        from_status     TEXT,
        to_status       TEXT NOT NULL,
        note            TEXT,
        at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    CREATE INDEX application_events_app ON application_events (application_id, at);

    CREATE TABLE user_job_flags (
        job_id                  INTEGER PRIMARY KEY REFERENCES jobs (id),
        hidden                  INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
        not_interested_reason   TEXT,
        updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE scrape_runs (
        id              INTEGER PRIMARY KEY,
        source          TEXT NOT NULL,
        started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        finished_at     TEXT,
        status          TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'ok', 'error', 'paused')),
        found           INTEGER NOT NULL DEFAULT 0,
        new             INTEGER NOT NULL DEFAULT 0,
        errors          INTEGER NOT NULL DEFAULT 0,
        budget_used     INTEGER NOT NULL DEFAULT 0,
        error_text      TEXT
    );
    CREATE INDEX scrape_runs_source ON scrape_runs (source, started_at);

    CREATE TABLE saved_searches (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL,
        filters     TEXT NOT NULL DEFAULT '{{}}',       -- JSON
        position    INTEGER NOT NULL DEFAULT 0,
        is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE settings (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,                      -- JSON
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    -- Embeddings live in sqlite-vec tables keyed by the owning row's id.
    CREATE VIRTUAL TABLE job_embeddings USING vec0 (
        job_id INTEGER PRIMARY KEY,
        embedding float[{EMBEDDING_DIM}] distance_metric=cosine
    );
    CREATE VIRTUAL TABLE profile_embeddings USING vec0 (
        profile_version_id INTEGER PRIMARY KEY,
        embedding float[{EMBEDDING_DIM}] distance_metric=cosine
    );
    """,
    # 2 — background tasks, per-source state and budgets, source miss tracking
    """
    CREATE TABLE tasks (
        id          INTEGER PRIMARY KEY,
        kind        TEXT NOT NULL,                      -- profile_parse, source_run, score...
        status      TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'done', 'error')),
        progress    TEXT NOT NULL DEFAULT '[]',         -- JSON list of {step, state}
        result      TEXT,                               -- JSON
        error       TEXT,
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        finished_at TEXT
    );
    CREATE INDEX tasks_kind ON tasks (kind, created_at);

    CREATE TABLE source_state (
        source          TEXT PRIMARY KEY,
        status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
        paused_reason   TEXT,
        paused_until    TEXT,                           -- null = until the user resumes
        updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );

    CREATE TABLE source_budget (
        source  TEXT NOT NULL,
        day     TEXT NOT NULL,                          -- YYYY-MM-DD, UTC
        used    INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (source, day)
    );

    -- A feed/ATS source that stops listing a job counts misses; 2 in a row expires it.
    ALTER TABLE job_sources ADD COLUMN missed_runs INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE job_sources ADD COLUMN status TEXT NOT NULL DEFAULT 'listed'
        CHECK (status IN ('listed', 'gone'));
    ALTER TABLE job_sources ADD COLUMN scope TEXT;      -- e.g. a company board's slug
    ALTER TABLE match_scores ADD COLUMN similarity REAL;

    -- applications gains 'archived' (un-saved; history stays in application_events).
    -- SQLite cannot alter a CHECK, so the table is rebuilt.
    CREATE TABLE applications_v2 (
        id                  INTEGER PRIMARY KEY,
        job_id              INTEGER NOT NULL UNIQUE REFERENCES jobs (id),
        status              TEXT NOT NULL DEFAULT 'saved' CHECK (status IN ('saved', 'applied',
                            'interviewing', 'offer', 'rejected', 'withdrawn', 'archived')),
        applied_at          TEXT,
        notes               TEXT NOT NULL DEFAULT '',
        status_changed_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
    INSERT INTO applications_v2 (id, job_id, status, applied_at, notes, created_at, updated_at)
        SELECT id, job_id, status, applied_at, notes, created_at, updated_at FROM applications;
    DROP TABLE applications;
    ALTER TABLE applications_v2 RENAME TO applications;
    """,
    # 3 — near-duplicate jobs point at the job they were merged into (never deleted)
    """
    ALTER TABLE jobs ADD COLUMN duplicate_of INTEGER REFERENCES jobs (id);
    CREATE INDEX jobs_duplicate_of ON jobs (duplicate_of);
    """,
    # 4 — time zones for the overlap filter
    """
    ALTER TABLE job_locations ADD COLUMN timezone TEXT;
    ALTER TABLE job_locations ADD COLUMN utc_offset_min INTEGER;
    CREATE INDEX job_locations_latlon ON job_locations (lat, lon);
    """,
]


def connect(path: Path | str) -> sqlite3.Connection:
    """Open a connection with sqlite-vec loaded and sane pragmas."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the resulting schema version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        with conn:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
    return conn.execute("PRAGMA user_version").fetchone()[0]


def init_db(path: Path | str) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn


@contextmanager
def open_db(path: Path | str) -> Iterator[sqlite3.Connection]:
    conn = init_db(path)
    try:
        yield conn
    finally:
        conn.close()


def db_status(conn: sqlite3.Connection) -> dict:
    """Small report for /health."""
    vec_version = conn.execute("SELECT vec_version()").fetchone()[0]
    schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
    return {
        "ok": True,
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_vec_version": vec_version,
        "schema_version": schema_version,
        "schema_latest": len(MIGRATIONS),
    }
