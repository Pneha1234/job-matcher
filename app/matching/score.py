"""Stage B: the local LLM assesses one job against the profile as validated JSON; the
match % is computed here from that assessment and the user's weights.

The model never produces the percentage. It classifies (matched / partial / missing,
match / one level off ...); code maps classes to numbers. A sub-score the posting gives
no basis for is None and drops out of the weighted average.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.settings_store import Weights

SUB_KEYS = ("required", "nice", "seniority", "domain", "location")


class SkillCheck(BaseModel):
    skill: str = Field(min_length=1, max_length=40)
    status: Literal["matched", "partial", "missing"]


class JobAssessment(BaseModel):
    # Caps keep the answer short: on a laptop the model writes about 10-20 tokens a second,
    # so answer length is the scoring time.
    # At least one: smaller models otherwise return an empty list and the job can't be
    # scored (qwen2.5:7b did this for a third of postings).
    required_skills: list[SkillCheck] = Field(min_length=1, max_length=10)
    nice_to_have_skills: list[SkillCheck] = Field(default_factory=list, max_length=6)
    seniority_fit: Literal["match", "one_level_off", "two_or_more_off", "unclear"]
    domain_fit: Literal["same", "related", "different", "unclear"]
    location_language_fit: Literal["fits", "minor_issue", "blocker", "unclear"]
    explanation: str = Field(min_length=10, max_length=320)


SYSTEM = (
    "You compare one job posting with a candidate profile and classify the fit. Be strict "
    "and literal, and brief. required_skills: the most important skills, tools and "
    "qualifications the posting requires (at least 1, at most 8; short names of one to four "
    "words, in English), each marked matched (the profile "
    "clearly has it), partial (related or less experience) or missing. "
    "nice_to_have_skills: ones it calls a plus or preferred (at most 5). seniority_fit "
    "compares the level the posting asks for with the candidate's. domain_fit compares "
    "industries. location_language_fit considers where the job can be done and "
    "spoken-language requirements, given the candidate's location facts. explanation: at "
    "most two short, plain sentences on the main reasons, naming the biggest gap. Use "
    "'unclear' when the posting gives no basis. Reply with JSON only."
)

SENIORITY = {"match": 100, "one_level_off": 60, "two_or_more_off": 20, "unclear": None}
DOMAIN = {"same": 100, "related": 65, "different": 25, "unclear": None}
LOCATION = {"fits": 100, "minor_issue": 55, "blocker": 0, "unclear": None}


def _skills_score(checks: list[SkillCheck]) -> float | None:
    if not checks:
        return None
    points = sum(1.0 if c.status == "matched" else 0.5 if c.status == "partial" else 0.0
                 for c in checks)  # fmt: skip
    return round(100 * points / len(checks))


def sub_scores(
    a: JobAssessment, location: str, language_gaps: list[str]
) -> dict[str, float | None]:
    loc = LOCATION[a.location_language_fit]
    # Code-side facts override the model where they are certain.
    if location == "not_eligible":
        loc = 0
    elif location == "eligible" and loc is None:
        loc = 100
    elif location == "relocation":
        loc = min(loc if loc is not None else 60, 60)
    if language_gaps:
        loc = min(loc if loc is not None else 40, 40)
    return {
        "required": _skills_score(a.required_skills),
        "nice": _skills_score(a.nice_to_have_skills),
        "seniority": SENIORITY[a.seniority_fit],
        "domain": DOMAIN[a.domain_fit],
        "location": loc,
    }


def final_pct(subs: dict[str, float | None], weights: Weights) -> float | None:
    w = weights.model_dump()
    parts = [(subs.get(k), w[k]) for k in SUB_KEYS if subs.get(k) is not None and w[k] > 0]
    total = sum(weight for _, weight in parts)
    if not total or subs.get("required") is None:
        return None  # without required skills there is nothing honest to rank on
    return round(sum(score * weight for score, weight in parts) / total, 1)


def build_prompt(profile_text: str, facts: list[str], job: dict, locations: list[str]) -> str:
    return "\n".join(
        [
            "CANDIDATE PROFILE:",
            profile_text,
            "CANDIDATE LOCATION FACTS:",
            *[f"- {f}" for f in facts],
            "",
            "JOB POSTING:",
            f"Title: {job['title']}",
            f"Company: {job['company_name']}",
            f"Locations: {', '.join(locations) or 'not stated'}",
            f"Work mode: {job['work_mode'] or 'not stated'}",
            f"Type: {job['job_type'] or 'not stated'}",
            "Description:",
            (job["description"] or "")[:7000],
        ]
    )
