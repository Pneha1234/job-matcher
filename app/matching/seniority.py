"""Seniority fit from the job title, worked out in code. The scoring model rated an intern
role a "match" for a senior profile, so a level the title states overrides the model."""

import re

from app.matching.score import SeniorityFit

# One ladder for both tracks: a lead, staff engineer or manager sits one step above senior.
PROFILE_LEVEL = {
    "intern": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4, "staff": 4,
    "principal": 5, "manager": 4, "director": 5,
}  # fmt: skip

TITLE_LEVELS = [
    (0, r"interns?(hip)?|trainee|apprentice(ship)?|freshers?|werkstudent|working student"),
    (1, r"junior|jr\.?|entry[- ]level|graduate|new grad"),
    (2, r"mid[- ]?level|medior|intermediate"),
    (3, r"senior|sr\.?"),
    (4, r"lead|staff"),
    (5, r"principal|distinguished|director|head of|vp|vice president"),
]
# "Member of Technical Staff" is a title in itself, not a staff-level role.
NOT_A_LEVEL = re.compile(r"member of (the )?technical staff", re.I)


def title_levels(title: str, job_type: str | None = None) -> set[int]:
    text = NOT_A_LEVEL.sub(" ", title or "")
    found = {
        level
        for level, words in TITLE_LEVELS
        if re.search(rf"(?<![\w-])(?:{words})(?![\w-])", text, re.I)
    }
    if job_type == "internship":
        found.add(0)
    return found


def level_gap(title: str, job_type: str | None, profile_seniority: str | None) -> int | None:
    """Levels from yours to the title's: negative below you, positive above, None when the
    title states no level. A title naming two levels ("Senior/Lead") counts as the closer."""
    mine = PROFILE_LEVEL.get(profile_seniority or "")
    levels = title_levels(title, job_type)
    if mine is None or not levels:
        return None
    return min((level - mine for level in levels), key=abs)


def seniority_fit(gap: int | None) -> SeniorityFit | None:
    """The fit class for a title's level gap; None leaves the model's answer standing."""
    if gap is None:
        return None
    return "match" if gap == 0 else "one_level_off" if abs(gap) == 1 else "two_or_more_off"
