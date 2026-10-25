"""Build a draft profile: local-LLM extraction plus skill provenance computed in code."""

import re

from app.llm import OllamaClient
from app.profile.links import GitHubEvidence
from app.profile.parse import LinkedInExport
from app.profile.schema import ExtractedProfile, ProfileData, ProfileSkill

SYSTEM = (
    "You extract a candidate profile from their resume and supporting evidence. Fill every "
    "field the text supports and use null only when the text gives no basis; never invent. "
    "Be brief. current_title: the title of the most recent role. seniority: the level that "
    "title or the experience shows (a 'Senior ...' title is senior). years_experience: total "
    "years of professional work, counted from the role dates or stated in the text. skills: "
    "at most 40, short canonical names (e.g. 'PostgreSQL', 'Django REST Framework', "
    "'Kubernetes'), most important first; 'years' counts the years of the roles that mention "
    "it, null if no role does. 'roles' are past job titles. 'domains' are industries such as "
    "Fintech, HR tech, E-commerce, Healthcare. 'languages' are spoken languages only, at the "
    "level the text states. 'summary' is one sentence in the third person."
)

# Names that GitHub, LinkedIn and resumes spell differently.
ALIASES = {
    "postgres": "postgresql",
    "postgre sql": "postgresql",
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "k8s": "kubernetes",
    "drf": "django rest framework",
    "node": "node.js",
    "nodejs": "node.js",
    "react.js": "react",
    "reactjs": "react",
    "amazon web services": "aws",
    "gcp": "google cloud",
}

# GitHub reports these as languages; they are rarely meaningful skills on their own.
GITHUB_NOISE = {"html", "css", "shell", "makefile", "dockerfile", "jupyter notebook", "scss"}


def skill_key(name: str) -> str:
    key = re.sub(r"\s+", " ", name.strip().lower())
    return ALIASES.get(key, key)


def _mentions(text: str, name: str) -> bool:
    if not text:
        return False
    pattern = r"(?<![\w+#.])" + re.escape(name.lower()) + r"(?![\w+#])"
    return re.search(pattern, text.lower()) is not None


def build_prompt(
    resume: str,
    linkedin: LinkedInExport | None,
    github: GitHubEvidence | None,
    portfolio: str | None,
) -> str:
    parts = ["RESUME:\n" + resume]
    if linkedin:
        parts.append("LINKEDIN EXPORT:\n" + linkedin.as_text()[:8000])
    if github:
        parts.append("GITHUB:\n" + github.as_text())
    if portfolio:
        parts.append("PORTFOLIO PAGE:\n" + portfolio[:4000])
    return "\n\n".join(parts)


async def extract_with_llm(client: OllamaClient, prompt: str, model: str | None = None):
    return await client.generate_json(prompt, ExtractedProfile, system=SYSTEM, model=model)


def merge(
    extracted: ExtractedProfile | None,
    resume: str,
    linkedin: LinkedInExport | None,
    github: GitHubEvidence | None,
    portfolio: str | None,
) -> ProfileData:
    """Attach provenance to every skill and add skills only the evidence shows.

    ``extracted`` is None when the user chose to fill the profile in by hand after the
    LLM failed; the result then carries only deterministic evidence, nothing invented.
    """
    linkedin_text = linkedin.as_text() if linkedin else ""
    gh_langs = {skill_key(x.name): x for x in (github.languages if github else [])}
    li_skills = {skill_key(s): s for s in (linkedin.skills if linkedin else [])}

    skills: dict[str, ProfileSkill] = {}
    for s in extracted.skills if extracted else []:
        key = skill_key(s.name)
        if key in skills:
            continue
        sources = []
        if _mentions(resume, s.name):
            sources.append("Resume")
        if key in li_skills or _mentions(linkedin_text, s.name):
            sources.append("LinkedIn export")
        if key in gh_langs:
            sources.append(f"GitHub ({gh_langs[key].repos} repos)")
        if portfolio and _mentions(portfolio, s.name):
            sources.append("Portfolio")
        skills[key] = ProfileSkill(**s.model_dump(), sources=sources or ["Model inferred"])

    for key, lang in gh_langs.items():
        if key not in skills and key not in GITHUB_NOISE:
            skills[key] = ProfileSkill(
                name=lang.name,
                last_used=lang.last_pushed_year,
                sources=[f"GitHub ({lang.repos} repos)"],
            )
    for key, name in li_skills.items():
        if key not in skills:
            skills[key] = ProfileSkill(name=name, sources=["LinkedIn export"])

    data = extracted.model_dump(exclude={"skills"}) if extracted else {}
    if not data.get("languages") and linkedin:
        data["languages"] = [
            {"language": x["name"], "level": level}
            for x in linkedin.languages
            if (level := LINKEDIN_LEVELS.get(x.get("proficiency", "").strip().lower()))
        ]
    return ProfileData(**data, skills=list(skills.values()))


# The fixed proficiency labels LinkedIn's export uses.
LINKEDIN_LEVELS = {
    "native or bilingual proficiency": "native",
    "full professional proficiency": "fluent",
    "professional working proficiency": "professional",
    "limited working proficiency": "basic",
    "elementary proficiency": "basic",
}
