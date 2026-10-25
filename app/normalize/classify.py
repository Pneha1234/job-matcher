"""Rule-based fields from posting text: job type, work mode, visa, relocation, languages,
and the India-specific fields (notice period, experience range, immediate joiner)."""

import html
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

JOB_TYPES = [
    (r"intern(ship)?\b|praktikum|stage\b|trainee|apprentice", "internship"),
    (r"freelanc|self[- ]employed|1099\b", "freelance"),
    (
        r"contract|contractor|temporary|temp\b|fixed[- ]term|befristet|tidsbegr|interim|c2c",
        "contract",
    ),
    (r"part[-_ ]?time|teilzeit|deltid|werkstudent|working student", "part-time"),
    (r"full[-_ ]?time|fulltime|permanent|vollzeit|heltid|regular|cdi\b|vast", "full-time"),
]


def job_type(*texts: str | None) -> str | None:
    """First non-empty text that names a type wins (the structured field before the title)."""
    for text in texts:
        if not text:
            continue
        for pattern, value in JOB_TYPES:
            if re.search(pattern, text, re.I):
                return value
    return None


def work_mode(remote: bool | None, *texts: str | None) -> str | None:
    joined = " ".join(t for t in texts if t)
    if re.search(r"\bhybrid\b", joined, re.I):
        return "hybrid"
    if remote:
        return "remote"
    if re.search(r"\b(on[- ]?site|in[- ]office|work from office|wfo)\b", joined, re.I):
        return "onsite"
    if re.search(r"\b(fully remote|100% remote|remote[- ]first|work from home)\b", joined, re.I):
        return "remote"
    return None


VISA_NO = re.compile(
    r"(no|not|unable to|not able to|not in a position to|cannot|can't|won't|will not|do not|"
    r"does not)\s+(currently\s+)?(offer\s+|provide\s+|support\s+)?"
    r"(visa\s+)?sponsor(?!\w* for an? export)|without (visa\s+)?sponsorship(?! for an? export)|"
    r"sponsorship is not (available|provided)|"
    r"must (already )?(have|hold) (the )?(right|authori[sz]ation) to work|"
    r"not eligible for (visa )?sponsorship",
    re.I,
)
VISA_YES = re.compile(
    r"(visa|work permit) sponsorship (is )?(available|provided|offered|possible)|"
    r"we (can |will |do )?sponsor|sponsorship (is )?available|"
    r"(offer|provide)s? (visa|work permit) sponsorship|relocation and visa",
    re.I,
)
RELOCATION = re.compile(
    r"relocation (support|assistance|package|bonus|allowance|help)|help (you )?relocat|"
    r"we (will )?(support|assist) (your )?relocation|relocation (is )?(provided|offered|covered)",
    re.I,
)


def visa(text: str) -> str | None:
    if VISA_NO.search(text):
        return "no"
    if VISA_YES.search(text):
        return "yes"
    return None


def relocation(text: str) -> int | None:
    return 1 if RELOCATION.search(text) else None


LANGS = {
    "english": "en", "german": "de", "dutch": "nl", "french": "fr", "spanish": "es",
    "italian": "it", "portuguese": "pt", "swedish": "sv", "norwegian": "no", "danish": "da",
    "finnish": "fi", "polish": "pl", "japanese": "ja", "mandarin": "zh", "chinese": "zh",
    "hindi": "hi", "nepali": "ne", "arabic": "ar", "korean": "ko", "russian": "ru",
    "czech": "cs", "turkish": "tr", "hebrew": "he", "greek": "el",
    "deutsch": "de", "nederlands": "nl", "svenska": "sv",
}  # fmt: skip
_LANG_ALT = "|".join(sorted(LANGS, key=len, reverse=True))
LANG_REQ = [
    re.compile(
        rf"\b(fluent|fluency|native|business[- ]level|professional|proficient|proficiency|"
        rf"excellent|strong|very good|full professional|c1|c2|b2)\b"
        rf"[^.\n]{{0,40}}?\b({_LANG_ALT})\b",
        re.I,
    ),
    re.compile(
        rf"\b({_LANG_ALT})\b\s*(language\s*)?(skills\s*)?(\((spoken|written)[^)]*\)\s*)?"
        rf"(is\s+|are\s+)?(required|mandatory|a must|essential|needed|is a requirement)",
        re.I,
    ),
    re.compile(rf"\b(must|need to|required to)\s+(speak|be fluent in)\s+({_LANG_ALT})\b", re.I),
]
NICE = re.compile(r"\b(plus|nice to have|bonus|advantage|preferred|desirable|beneficial)\b", re.I)


def language_requirements(text: str) -> list[str]:
    """ISO codes of languages the posting requires (not ones it calls a plus)."""
    found: list[str] = []
    for sentence in re.split(r"(?<=[.!?\n•])\s+", text):
        if NICE.search(sentence):
            continue
        for pattern in LANG_REQ:
            for m in pattern.finditer(sentence):
                word = next((g for g in m.groups() if g and g.lower() in LANGS), None)
                if word and LANGS[word.lower()] not in found:
                    found.append(LANGS[word.lower()])
    return found


STOPWORDS = {
    "en": {"the", "and", "you", "with", "for", "our", "will", "are", "this", "your"},
    "de": {"und", "die", "der", "mit", "für", "wir", "sie", "ist", "das", "auf"},
    "nl": {"en", "de", "het", "van", "een", "voor", "met", "wij", "je", "zijn"},
    "fr": {"et", "les", "des", "pour", "vous", "nous", "une", "avec", "dans", "est"},
    "es": {"y", "los", "las", "para", "con", "una", "del", "por", "que", "en"},
    "sv": {"och", "att", "för", "med", "som", "vi", "det", "är", "på", "av"},
    "no": {"og", "å", "for", "med", "som", "vi", "det", "er", "på", "av"},
    "pt": {"e", "os", "para", "com", "uma", "do", "da", "que", "em", "você"},
}


def posting_language(text: str, devanagari_hint: str = "hi") -> str | None:
    sample = text[:3000]
    if len(re.findall(r"[ऀ-ॿ]", sample)) > 50:
        return devanagari_hint  # Hindi and Nepali share the script; the source decides
    words = re.findall(r"[a-zäöüåéèàçñõ]+", sample.lower())
    if len(words) < 20:
        return None
    scores = {lang: sum(w in sw for w in words) for lang, sw in STOPWORDS.items()}
    lang, best = max(scores.items(), key=lambda kv: kv[1])
    return lang if best >= 5 else None


def india_fields(text: str) -> dict:
    out: dict = {}
    if m := re.search(r"notice period[^.\n]{0,20}?(\d{1,3})\s*(days|day|months?)", text, re.I):
        days = int(m.group(1)) * (30 if m.group(2).lower().startswith("month") else 1)
        out["notice_period_days"] = days
    if re.search(r"immediate (joiner|joining|starter)s?|join immediately", text, re.I):
        out["immediate_joiner"] = True
    if m := re.search(
        r"(\d{1,2})\s*(?:\+|-|–|to)\s*(\d{1,2})?\s*(?:years?|yrs?)\b[^.\n]{0,20}?experience|"
        r"experience[^.\n]{0,20}?(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:years?|yrs?)",
        text,
        re.I,
    ):
        nums = [int(g) for g in m.groups() if g]
        out["experience_min"] = nums[0]
        if len(nums) > 1:
            out["experience_max"] = nums[1]
    return out


def html_to_text(value: str | None) -> str:
    """Postings arrive as HTML, sometimes HTML-escaped HTML; return readable plain text."""
    if not value:
        return ""
    if "&lt;" in value[:500]:
        value = html.unescape(value)
    if "<" not in value:
        return html.unescape(value).strip()
    tree = HTMLParser(value)
    for tag in tree.css("script, style"):
        tag.decompose()
    for br in tree.css("br"):
        br.replace_with("\n")
    for block in tree.css("p, div, li, h1, h2, h3, h4, h5, tr"):
        if block.tag == "li":
            block.insert_before("\n• ")
        else:
            block.insert_before("\n")
    text = tree.body.text() if tree.body else tree.text()
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()
