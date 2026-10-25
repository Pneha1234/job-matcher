"""Profile versions: drafts from parsing, saved versions, one active at a time.

Nothing is deleted. Saving a draft makes it the active version; the previous active
version stays 'saved' (selectable again) and its match scores are kept, labelled with
their version.
"""

import sqlite3

from app.profile.schema import ProfileData
from app.util import dumps, loads, now_iso


class ProfileError(ValueError):
    pass


def create_draft(conn: sqlite3.Connection, raw_inputs: dict, profile: ProfileData) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO profile_versions (raw_inputs, profile_json, status) "
            "VALUES (?, ?, 'draft')",
            (dumps(raw_inputs), profile.model_dump_json()),
        )
    return cur.lastrowid


def _row_to_dict(row: sqlite3.Row, with_raw: bool = False) -> dict:
    out = {
        "id": row["id"],
        "label": row["label"],
        "status": row["status"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "profile": loads(row["profile_json"], {}),
    }
    raw = loads(row["raw_inputs"], {})
    out["inputs"] = {
        "resume_filename": raw.get("resume_filename"),
        "github": raw.get("github", {}).get("username") if raw.get("github") else None,
        "portfolio_url": raw.get("portfolio_url"),
        "linkedin": bool(raw.get("linkedin")),
        "llm_error": raw.get("llm_error"),
    }
    if with_raw:
        out["raw_inputs"] = raw
    return out


def get(conn: sqlite3.Connection, version_id: int, with_raw: bool = False) -> dict:
    row = conn.execute("SELECT * FROM profile_versions WHERE id = ?", (version_id,)).fetchone()
    if not row:
        raise ProfileError("Profile version not found")
    return _row_to_dict(row, with_raw)


def list_versions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM profile_versions WHERE status != 'archived' ORDER BY id DESC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def active(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM profile_versions WHERE is_active = 1").fetchone()
    return _row_to_dict(row) if row else None


def active_profile(conn: sqlite3.Connection) -> tuple[int, ProfileData] | None:
    row = conn.execute(
        "SELECT id, profile_json FROM profile_versions WHERE is_active = 1"
    ).fetchone()
    if not row:
        return None
    return row["id"], ProfileData.model_validate_json(row["profile_json"])


def update_draft(conn: sqlite3.Connection, version_id: int, profile: ProfileData) -> dict:
    current = get(conn, version_id)
    if current["status"] != "draft":
        raise ProfileError("Only a draft can be edited; saved versions are kept as they were.")
    with conn:
        conn.execute(
            "UPDATE profile_versions SET profile_json = ? WHERE id = ?",
            (profile.model_dump_json(), version_id),
        )
    return get(conn, version_id)


def save_draft(conn: sqlite3.Connection, version_id: int) -> dict:
    current = get(conn, version_id)
    if current["status"] != "draft":
        raise ProfileError("That version is already saved.")
    ProfileData.model_validate(current["profile"])
    number = (
        conn.execute("SELECT COUNT(*) FROM profile_versions WHERE status = 'saved'").fetchone()[0]
        + 1
    )
    with conn:
        conn.execute("UPDATE profile_versions SET is_active = 0 WHERE is_active = 1")
        conn.execute(
            "UPDATE profile_versions SET status = 'saved', is_active = 1, label = ?, "
            "created_at = ? WHERE id = ?",
            (f"Profile v{number}", now_iso(), version_id),
        )
    return get(conn, version_id)


def activate(conn: sqlite3.Connection, version_id: int) -> dict:
    current = get(conn, version_id)
    if current["status"] != "saved":
        raise ProfileError("Only a saved version can be made active.")
    with conn:
        conn.execute("UPDATE profile_versions SET is_active = 0 WHERE is_active = 1")
        conn.execute("UPDATE profile_versions SET is_active = 1 WHERE id = ?", (version_id,))
    return get(conn, version_id)


def previous_saved(conn: sqlite3.Connection, version_id: int) -> dict | None:
    """The saved version this one would replace: the active one, or the last saved before it."""
    current = get(conn, version_id)
    if current["status"] == "draft":
        row = conn.execute("SELECT * FROM profile_versions WHERE is_active = 1").fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM profile_versions WHERE status = 'saved' AND id < ? "
            "ORDER BY id DESC LIMIT 1",
            (version_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def diff(old: dict | None, new: dict) -> dict:
    """Skill and headline changes between two profile documents."""
    if old is None:
        return {"against": None, "added": [], "removed": [], "changed": []}
    a = {s["name"].lower(): s for s in old["profile"].get("skills", [])}
    b = {s["name"].lower(): s for s in new["profile"].get("skills", [])}
    changed = []
    for key in a.keys() & b.keys():
        if a[key].get("years") != b[key].get("years"):
            changed.append(
                {"field": b[key]["name"], "from": a[key].get("years"), "to": b[key].get("years")}
            )
    for field in ("current_title", "seniority", "years_experience"):
        if old["profile"].get(field) != new["profile"].get(field):
            changed.append(
                {"field": field, "from": old["profile"].get(field), "to": new["profile"].get(field)}
            )
    return {
        "against": old["label"],
        "added": sorted(b[k]["name"] for k in b.keys() - a.keys()),
        "removed": sorted(a[k]["name"] for k in a.keys() - b.keys()),
        "changed": sorted(changed, key=lambda c: str(c["field"])),
    }
