"""Location and language fit worked out in code, so the LLM can't wave it through."""

import sqlite3

from app.normalize.regions import countries_for
from app.profile.schema import ProfileData
from app.settings_store import AppSettings
from app.util import loads

SPEAKS = {"native", "fluent", "professional"}
LANG_NAMES = {
    "en": "english", "de": "german", "nl": "dutch", "fr": "french", "es": "spanish",
    "it": "italian", "pt": "portuguese", "sv": "swedish", "no": "norwegian", "da": "danish",
    "fi": "finnish", "pl": "polish", "ja": "japanese", "zh": "chinese", "hi": "hindi",
    "ne": "nepali", "ar": "arabic", "ko": "korean", "ru": "russian", "cs": "czech",
    "tr": "turkish", "he": "hebrew", "el": "greek",
}  # fmt: skip


def remote_countries(remote: dict) -> set[str]:
    out = set(remote.get("countries") or [])
    for region in remote.get("regions") or []:
        out |= countries_for(region)
    return out


def location_status(
    job: sqlite3.Row | dict, countries: list[str], settings: AppSettings
) -> tuple[str, str | None]:
    """('eligible' | 'relocation' | 'not_eligible' | 'unknown', reason)."""
    home = settings.home_country
    wanted = set(settings.target_countries) | ({home} if home else set())
    if not wanted:
        return "unknown", None
    remote = loads(job["remote_eligibility"], {}) or {}
    places = {c for c in countries if c}
    if places & wanted:
        if settings.needs_visa and home not in places & wanted and job["visa_sponsorship"] == "no":
            return "not_eligible", "The posting says it can't sponsor a visa"
        return "eligible", None
    if remote.get("remote"):
        if remote.get("worldwide"):
            return "eligible", None
        allowed = remote_countries(remote)
        if allowed:
            if home and home in allowed:
                return "eligible", None
            shown = ", ".join(sorted(remote.get("countries") or remote.get("regions") or []))
            return "not_eligible", f"Remote is limited to {shown}"
        if not places:
            return "unknown", "Remote, but the posting doesn't say from where"
    if places and settings.open_to_relocation:
        return "relocation", "Needs relocation"
    if places:
        return "not_eligible", "Outside your target countries"
    return "unknown", "Location unclear"


def language_gaps(job: sqlite3.Row | dict, profile: ProfileData) -> list[str]:
    spoken = {x.language.strip().lower() for x in profile.languages if x.level in SPEAKS}
    gaps = []
    for code in loads(job["language_reqs"], []) or []:
        name = LANG_NAMES.get(code, code)
        if name not in spoken and code not in spoken:
            gaps.append(name.capitalize())
    return gaps
