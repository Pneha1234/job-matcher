import sqlite3

import pytest
import sqlite_vec

from app.db import EMBEDDING_DIM, MIGRATIONS, db_status, init_db, migrate

TABLES = {
    "profile_versions",
    "jobs",
    "job_locations",
    "job_sources",
    "match_scores",
    "applications",
    "application_events",
    "user_job_flags",
    "companies",
    "scrape_runs",
    "saved_searches",
    "settings",
    "job_embeddings",
    "profile_embeddings",
}


def test_schema_created(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names >= TABLES
    status = db_status(conn)
    assert status["ok"] and status["schema_version"] == len(MIGRATIONS)
    assert status["sqlite_vec_version"].startswith("v")


def test_migrate_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    assert migrate(conn) == len(MIGRATIONS)


def test_vector_search(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    near = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    far = [0.0, 1.0] + [0.0] * (EMBEDDING_DIM - 2)
    with conn:
        for job_id, vec in ((1, near), (2, far)):
            conn.execute(
                "INSERT INTO job_embeddings (job_id, embedding) VALUES (?, ?)",
                (job_id, sqlite_vec.serialize_float32(vec)),
            )
    rows = conn.execute(
        "SELECT job_id, distance FROM job_embeddings WHERE embedding MATCH ? AND k = 2 "
        "ORDER BY distance",
        (sqlite_vec.serialize_float32(near),),
    ).fetchall()
    assert [r["job_id"] for r in rows] == [1, 2]
    assert rows[0]["distance"] == pytest.approx(0.0, abs=1e-6)


def test_scored_row_needs_a_percentage(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    with conn:
        conn.execute("INSERT INTO profile_versions (id) VALUES (1)")
        conn.execute(
            "INSERT INTO jobs (id, canonical_key, title, company_name) VALUES (1, 'k', 't', 'c')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO match_scores (job_id, profile_version_id, status) "
            "VALUES (1, 1, 'scored')"
        )
    conn.execute(
        "INSERT INTO match_scores (job_id, profile_version_id, status, error) "
        "VALUES (1, 1, 'unscored', 'timeout')"
    )


def test_only_one_active_profile(tmp_path):
    conn = init_db(tmp_path / "jm.db")
    conn.execute("INSERT INTO profile_versions (is_active) VALUES (1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO profile_versions (is_active) VALUES (1)")
