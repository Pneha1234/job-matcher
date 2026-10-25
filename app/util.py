"""Small helpers shared across modules."""

import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None) -> str | None:
    """ISO-8601 in UTC with a trailing Z, matching the SQLite column defaults."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso() -> str:
    return iso(utcnow())  # type: ignore[return-value]


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def days_ago(days: float) -> str:
    return iso(utcnow() - timedelta(days=days))  # type: ignore[return-value]


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def ascii_fold(text: str) -> str:
    """'München' -> 'munchen'; lowercased, accents stripped, whitespace collapsed."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", folded).strip().lower()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", ascii_fold(text)).strip("-")
