"""The profile document: what the LLM extracts, and what the user reviews and saves."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Seniority = Literal[
    "intern", "junior", "mid", "senior", "lead", "staff", "principal", "manager", "director"
]
LanguageLevel = Literal["native", "fluent", "professional", "basic", "none"]


class ExtractedSkill(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    years: float | None = Field(None, ge=0, le=60)
    last_used: int | None = Field(None, ge=1970, le=2100)


class SpokenLanguage(BaseModel):
    language: str = Field(min_length=1, max_length=40)
    level: LanguageLevel


class ExtractedProfile(BaseModel):
    """LLM output schema. Unknown values must be null, never invented."""

    current_title: str | None = Field(None, max_length=120)
    seniority: Seniority | None = None
    years_experience: float | None = Field(None, ge=0, le=60)
    summary: str | None = Field(None, max_length=600)
    skills: list[ExtractedSkill] = Field(default_factory=list, max_length=80)
    roles: list[str] = Field(default_factory=list, max_length=20)
    domains: list[str] = Field(default_factory=list, max_length=12)
    languages: list[SpokenLanguage] = Field(default_factory=list, max_length=12)


class ProfileSkill(ExtractedSkill):
    sources: list[str] = []  # provenance, e.g. "Resume", "GitHub (14 repos)"


class ProfileData(BaseModel):
    """What gets saved per profile version, after the user's review."""

    current_title: str | None = Field(None, max_length=120)
    seniority: Seniority | None = None
    years_experience: float | None = Field(None, ge=0, le=60)
    summary: str | None = Field(None, max_length=1200)
    skills: list[ProfileSkill] = []
    roles: list[str] = []
    domains: list[str] = []
    languages: list[SpokenLanguage] = []

    @field_validator("skills")
    @classmethod
    def _unique_skills(cls, v: list[ProfileSkill]) -> list[ProfileSkill]:
        seen: set[str] = set()
        for s in v:
            key = s.name.strip().lower()
            if key in seen:
                raise ValueError(f"'{s.name}' is listed twice")
            seen.add(key)
        return v

    def as_text(self) -> str:
        """Compact description used for the profile embedding and LLM prompts."""
        skills = ", ".join(
            f"{s.name}" + (f" ({s.years:g} yrs)" if s.years else "") for s in self.skills
        )
        langs = ", ".join(f"{x.language} ({x.level})" for x in self.languages)
        return "\n".join(
            filter(
                None,
                [
                    f"Title: {self.current_title}" if self.current_title else None,
                    f"Seniority: {self.seniority}" if self.seniority else None,
                    (
                        f"Experience: {self.years_experience:g} years"
                        if self.years_experience is not None
                        else None
                    ),
                    f"Skills: {skills}" if skills else None,
                    f"Past roles: {', '.join(self.roles)}" if self.roles else None,
                    f"Domains: {', '.join(self.domains)}" if self.domains else None,
                    f"Languages: {langs}" if langs else None,
                    self.summary,
                ],
            )
        )
